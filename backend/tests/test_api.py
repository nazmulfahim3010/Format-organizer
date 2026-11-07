"""End-to-end API tests. They need fastapi + sqlalchemy + httpx installed
(`pip install -r requirements.txt`) and are skipped otherwise.

NOTE: these were written without being able to run FastAPI in the authoring
sandbox. If one fails, treat it as a bug report on either the test or the API.
"""
import base64
import io
import os
import tempfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("httpx")

from tests.api_helpers import DOCX, auth, upload_template  # noqa: E402  (client fixture: conftest)


def test_auth_required_and_wrong_password(client):
    assert client.get("/api/templates").status_code == 401
    auth(client, "x@example.org")
    assert client.post("/api/auth/login", json={"email": "x@example.org", "password": "nope"}).status_code == 401


def test_full_flow(client, templates, image):
    h = auth(client)
    t = upload_template(client, h, templates["university"])
    assert t["analysis"]["suggested_roles"]["heading_1"] == "Heading1"
    assert t["profile"]["approved"] is False

    # cannot create a document from an unapproved profile
    r = client.post("/api/documents", headers=h, json={"title": "D", "profile_id": t["profile"]["id"]})
    assert r.status_code == 422

    # edit the rules, preview the sample with them, approve
    rules = t["profile"]["rules"]
    rules["table"]["header_shading"] = "EEEEEE"
    assert client.put(f"/api/templates/{t['id']}/rules", headers=h, json=rules).status_code == 200
    s = client.post(f"/api/templates/{t['id']}/sample", headers=h)
    assert s.status_code == 200 and s.content[:2] == b"PK"
    ap = client.post(f"/api/templates/{t['id']}/approve", headers=h)
    assert ap.status_code == 200 and ap.json()["approved"] is True

    # editing an approved profile creates a NEW draft version; the approved one stays untouched
    rules["table"]["header_shading"] = "CCCCCC"
    r2 = client.put(f"/api/templates/{t['id']}/rules", headers=h, json=rules).json()
    assert r2["version"] == 2 and r2["approved"] is False and r2["id"] != ap.json()["id"]
    # the new draft is not approved -> still can't be used; approve it
    pid = client.post(f"/api/templates/{t['id']}/approve", headers=h).json()["id"]

    d = client.post("/api/documents", headers=h, json={"title": "My paper", "profile_id": pid}).json()
    with open(image, "rb") as f:
        asset = client.post("/api/media/upload", headers=h, files={"file": ("a.png", f, "image/png")}).json()["asset_id"]

    pasted = client.post("/api/paste/normalize", headers=h, json={"text": "## 1. Intro\nHello **world**.\n\nTable 1: T\n\n| a | b |\n|--|--|\n| 1 | 2 |\n"}).json()
    assert pasted["boxes"][0]["title"] == "Intro" and pasted["boxes"][0]["content"][1]["caption"] == "T"
    content = d["content"]
    content["body"] = pasted["boxes"] + [{"type": "figure", "asset_id": asset, "caption": "Fig"}]
    content["title"] = "My paper"
    assert client.put(f"/api/documents/{d['id']}", headers=h, json=content).status_code == 200

    gen = client.post(f"/api/documents/{d['id']}/generate", headers=h).json()
    dl = client.get(f"/api/documents/{d['id']}/files/{gen['file_id']}/download", headers=h)
    assert dl.status_code == 200 and dl.content[:2] == b"PK"
    pv = client.post(f"/api/documents/{d['id']}/preview", headers=h)
    assert pv.status_code == 200 and pv.headers["content-type"].startswith(DOCX)
    rep = client.post(f"/api/documents/{d['id']}/validate", headers=h).json()
    assert not [c for c in rep["checks"] if c["status"] == "failed"], rep
    assert len(client.get(f"/api/documents/{d['id']}/files", headers=h).json()) == 1


def test_users_cannot_see_each_others_data(client, templates, image):
    a, b = auth(client, "owner@example.org"), auth(client, "other@example.org")
    t = upload_template(client, a, templates["default"])
    assert client.get(f"/api/templates/{t['id']}", headers=b).status_code == 404
    assert client.put(f"/api/templates/{t['id']}/rules", headers=b, json=t["profile"]["rules"]).status_code == 404
    with open(image, "rb") as f:
        asset = client.post("/api/media/upload", headers=a, files={"file": ("a.png", f, "image/png")}).json()["asset_id"]
    assert client.get(f"/api/media/{asset}", headers=b).status_code == 404
    assert client.get(f"/api/media/{asset}", headers=a).status_code == 200


def test_bad_uploads_are_rejected(client):
    h = auth(client, "uploader@example.org")
    r = client.post("/api/templates/upload", headers=h, files={"file": ("evil.docx", b"MZ....", DOCX)})
    assert r.status_code == 422
    r = client.post("/api/media/upload", headers=h, files={"file": ("x.png", b"not an image", "image/png")})
    assert r.status_code == 422


def test_approval_blocks_invalid_role_mapping(client, templates):
    h = auth(client, "roles@example.org")
    t = upload_template(client, h, templates["default"])
    rules = t["profile"]["rules"]
    rules["roles"]["heading_1"] = "DoesNotExist"
    client.put(f"/api/templates/{t['id']}/rules", headers=h, json=rules)
    r = client.post(f"/api/templates/{t['id']}/approve", headers=h)
    assert r.status_code == 422 and "DoesNotExist" in r.text


def test_new_template_version_carries_profile_over_as_draft(client, templates):
    h = auth(client, "versions@example.org")
    t = upload_template(client, h, templates["university"])
    client.post(f"/api/templates/{t['id']}/approve", headers=h)
    with open(templates["messy"], "rb") as f:
        r = client.post(f"/api/templates/{t['id']}/versions", headers=h, files={"file": ("m.docx", f, DOCX)})
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["profile"]["approved"] is False


def test_pasted_data_uri_image_becomes_an_asset(client, image):
    h = auth(client, "paste@example.org")
    b64 = base64.b64encode(open(image, "rb").read()).decode()
    out = client.post("/api/paste/normalize", headers=h, json={"html": f'<p><img src="data:image/png;base64,{b64}"></p><p>Figure 1: Pic</p>'}).json()
    fig = out["boxes"][0]
    assert fig["type"] == "figure" and fig["asset_id"] and fig["caption"] == "Pic"


# ------------------------------------------------------------------ Phase 6: guards wired into the API
def test_login_is_rate_limited_per_account(client):
    auth(client, "brute@example.org")
    codes = [client.post("/api/auth/login", json={"email": "brute@example.org", "password": f"guess{i}"}).status_code
             for i in range(15)]
    assert codes[0] == 401 and 429 in codes
    assert client.post("/api/auth/login", json={"email": "brute@example.org", "password": "password123"}).status_code == 429


def test_unknown_account_costs_as_much_as_a_wrong_password(client):
    import time
    auth(client, "timing@example.org")

    def took(email):
        t0 = time.perf_counter()
        client.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
        return time.perf_counter() - t0
    took("nobody-warmup@example.org")
    known = min(took("timing@example.org") for _ in range(3))
    unknown = min(took(f"nobody{i}@example.org") for i in range(3))
    assert unknown > known * 0.5, (known, unknown)


def test_old_hashes_are_upgraded_at_login(client):
    import base64, hashlib
    from app.database.session import SessionLocal
    from app.models.db import User
    auth(client, "legacy@example.org")
    salt = os.urandom(16)
    dk = hashlib.scrypt(b"password123", salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="legacy@example.org").one()
        u.password_hash = f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"
        db.commit()
    assert client.post("/api/auth/login", json={"email": "legacy@example.org", "password": "password123"}).status_code == 200
    with SessionLocal() as db:
        assert db.query(User).filter_by(email="legacy@example.org").one().password_hash.startswith("scrypt$131072$")


def test_overlong_password_is_refused_by_validation(client):
    r = client.post("/api/auth/login", json={"email": "a@example.org", "password": "x" * 5000})
    assert r.status_code == 422


def test_hostile_template_upload_is_refused_with_a_clear_message(client, templates):
    from tests.make_attacks import attacks
    h = auth(client, "uploader@example.org")
    base = open(templates["university"], "rb").read()
    for name in ("xxe", "remote_template", "dde_split_field", "macro_vba"):
        data, filename, msg = attacks(base)[name]
        r = client.post("/api/templates/upload", headers=h, files={"file": (filename, data, DOCX)}, data={"name": name})
        assert r.status_code == 422 and msg.lower() in r.json()["detail"].lower(), (name, r.text)


def test_paste_keeps_at_most_the_configured_number_of_images(client):
    from app.config import settings
    h = auth(client, "paster@example.org")
    b = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (4, 4)).save(b, "PNG")
    uri = "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()
    html = "".join(f'<p><img src="{uri}"></p><p>Figure {i}: x</p>' for i in range(1, settings.max_paste_images + 6))
    r = client.post("/api/paste/normalize", headers=h, json={"html": html})
    assert r.status_code == 200, r.text
    assert "TOO_MANY_IMAGES" in {w["code"] for w in r.json()["warnings"]}
    figs = [b for b in r.json()["boxes"] if b["type"] == "figure" and b.get("asset_id")]
    assert len(figs) == settings.max_paste_images
