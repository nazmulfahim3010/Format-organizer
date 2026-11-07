"""Phase 7: database models, profile/template versioning and ownership through the API."""
import copy
import io
import os

import pytest
from docx import Document as Docx
from sqlalchemy import inspect, text

from tests.api_helpers import DOCX, auth, upload_template


def approve(client, h, t):
    r = client.post(f"/api/templates/{t['id']}/approve", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def new_doc(client, h, profile_id, title="Doc", language="en"):
    r = client.post("/api/documents", headers=h, json={"title": title, "profile_id": profile_id, "language": language})
    assert r.status_code == 200, r.text
    return r.json()


def put_content(client, h, doc_id, body):
    r = client.put(f"/api/documents/{doc_id}", headers=h, json={"title": "Doc", "language": "en", "body": body})
    assert r.status_code == 200, r.text
    return r.json()


SECTION = [{"type": "section", "title": "Introduction", "content": [{"type": "paragraph", "text": "Hello."}]}]


# ------------------------------------------------------------------ database
def test_sqlite_runs_with_foreign_keys_wal_and_busy_timeout(client):
    from app.database.session import engine
    with engine.connect() as c:
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert c.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
        assert c.execute(text("PRAGMA busy_timeout")).scalar() >= 5000


def test_all_tables_exist(client):
    from app.database.session import engine
    names = set(inspect(engine).get_table_names())
    assert {"users", "templates", "template_versions", "profile_versions", "documents",
            "generated_files", "media_assets", "validation_reports"} <= names


def test_approved_profile_rows_cannot_be_changed_even_without_the_api(client, templates):
    from app.database.session import SessionLocal
    from app.models.db import ImmutableVersionError, ProfileVersion
    h = auth(client, "immut@example.org")
    t = upload_template(client, h, templates["university"])
    pid = approve(client, h, t)["id"]
    with SessionLocal() as db:
        pv = db.get(ProfileVersion, pid)
        rules = dict(pv.rules); rules["name"] = "sneaky"
        pv.rules = rules
        with pytest.raises(ImmutableVersionError):
            db.commit()
        db.rollback()
        pv = db.get(ProfileVersion, pid)
        pv.approved = False
        with pytest.raises(ImmutableVersionError):
            db.commit()
        db.rollback()
        db.delete(db.get(ProfileVersion, pid))
        with pytest.raises(ImmutableVersionError):
            db.commit()


# ------------------------------------------------------------------ profile versioning
def test_editing_an_approved_profile_creates_a_new_draft_and_old_documents_keep_theirs(client, templates):
    h = auth(client, "edit@example.org")
    t = upload_template(client, h, templates["university"])
    v1 = approve(client, h, t)
    d = new_doc(client, h, v1["id"])
    rules = copy.deepcopy(v1["rules"]); rules["table"]["header_shading"] = "EEEEEE"
    r = client.put(f"/api/templates/{t['id']}/rules", headers=h, json=rules).json()
    assert r["version"] == 2 and r["approved"] is False and r["id"] != v1["id"]
    assert r["rules"]["origins"]["table.header_shading"] == "user"           # server records the edit
    assert r["rules"]["origins"]["table.alignment"] != "user"
    # editing the draft again changes the same draft
    rules["table"]["header_shading"] = "DDDDDD"
    r2 = client.put(f"/api/templates/{t['id']}/rules", headers=h, json=rules).json()
    assert r2["id"] == r["id"] and r2["rules"]["table"]["header_shading"] == "DDDDDD"
    # version 1 is untouched and the document still uses it
    hist = client.get(f"/api/templates/{t['id']}/profiles", headers=h).json()
    by_id = {p["id"]: p for p in hist}
    assert by_id[v1["id"]]["rules"]["table"]["header_shading"] == v1["rules"]["table"]["header_shading"] != "DDDDDD"
    assert by_id[v1["id"]]["approved"] is True and by_id[r["id"]]["approved"] is False
    assert client.get(f"/api/documents/{d['id']}", headers=h).json()["profile_id"] == v1["id"]


def test_client_cannot_forge_origins(client, templates):
    h = auth(client, "forge@example.org")
    t = upload_template(client, h, templates["university"])
    rules = t["profile"]["rules"]
    rules["origins"]["roles.heading_1"] = "user"          # nothing changed, so it must not be recorded as user
    r = client.put(f"/api/templates/{t['id']}/rules", headers=h, json=rules).json()
    assert r["rules"]["origins"]["roles.heading_1"] == "template"


def test_profile_history_lists_every_version_of_every_template_version(client, templates):
    h = auth(client, "hist@example.org")
    t = upload_template(client, h, templates["university"])
    approve(client, h, t)
    with open(templates["default"], "rb") as f:
        client.post(f"/api/templates/{t['id']}/versions", headers=h, files={"file": ("d.docx", f, DOCX)})
    hist = client.get(f"/api/templates/{t['id']}/profiles", headers=h).json()
    assert [(p["template_version"], p["version"], p["approved"]) for p in hist] == [(2, 1, False), (1, 1, True)]


def test_documents_need_an_approved_profile(client, templates):
    h = auth(client, "need@example.org")
    t = upload_template(client, h, templates["university"])
    r = client.post("/api/documents", headers=h, json={"title": "x", "profile_id": t["profile"]["id"]})
    assert r.status_code == 422


# ------------------------------------------------------------------ template versions
def test_new_template_version_carries_user_choices_and_old_documents_still_build(client, templates):
    h = auth(client, "carry@example.org")
    t = upload_template(client, h, templates["university"])
    rules = t["profile"]["rules"]; rules["labels"]["abstract"] = "Summary"; rules["table"]["header_shading"] = "EEEEEE"
    client.put(f"/api/templates/{t['id']}/rules", headers=h, json=rules)
    v1 = approve(client, h, t)
    d = new_doc(client, h, v1["id"])
    put_content(client, h, d["id"], SECTION)
    with open(templates["twocol"], "rb") as f:
        t2 = client.post(f"/api/templates/{t['id']}/versions", headers=h, files={"file": ("2.docx", f, DOCX)}).json()
    assert t2["version"] == 2 and t2["profile"]["approved"] is False
    carried = t2["profile"]["rules"]
    assert carried["labels"]["abstract"] == "Summary" and carried["table"]["header_shading"] == "EEEEEE"
    assert carried["origins"]["labels.abstract"] == "user"
    # the old document is still built from template version 1 (one column), not the new two-column file
    g = client.post(f"/api/documents/{d['id']}/generate", headers=h).json()
    data = client.get(f"/api/documents/{d['id']}/files/{g['file_id']}/download", headers=h).content
    cols = Docx(io.BytesIO(data)).sections[-1]._sectPr.find(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}cols")
    assert cols is None or cols.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}num") in (None, "1")
    # switching the document to the new approved profile builds it with the new template
    v2 = approve(client, h, t2)
    assert client.put(f"/api/documents/{d['id']}/profile", headers=h, json={"profile_id": v2["id"]}).status_code == 200
    g2 = client.post(f"/api/documents/{d['id']}/generate", headers=h).json()
    data2 = client.get(f"/api/documents/{d['id']}/files/{g2['file_id']}/download", headers=h).content
    cols2 = Docx(io.BytesIO(data2)).sections[-1]._sectPr.find(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}cols")
    assert cols2.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}num") == "2"
    files = client.get(f"/api/documents/{d['id']}/files", headers=h).json()
    assert [f["profile_id"] for f in files] == [v2["id"], v1["id"]]       # each file remembers its profile


def test_template_in_use_cannot_be_deleted(client, templates):
    h = auth(client, "deltpl@example.org")
    t = upload_template(client, h, templates["default"])
    d = new_doc(client, h, approve(client, h, t)["id"])
    assert client.delete(f"/api/templates/{t['id']}", headers=h).status_code == 409
    assert client.delete(f"/api/documents/{d['id']}", headers=h).status_code == 204
    assert client.delete(f"/api/templates/{t['id']}", headers=h).status_code == 204
    assert client.get(f"/api/templates/{t['id']}", headers=h).status_code == 404


# ------------------------------------------------------------------ documents
def test_document_content_is_validated(client, templates):
    h = auth(client, "valid@example.org")
    t = upload_template(client, h, templates["default"])
    d = new_doc(client, h, approve(client, h, t)["id"])
    bad = client.put(f"/api/documents/{d['id']}", headers=h,
                     json={"body": [{"type": "paragraph", "text": "x", "font": "Comic Sans"}]})
    assert bad.status_code == 422
    r = client.post("/api/documents", headers=h, json={"title": "x", "profile_id": d["profile_id"], "language": 'en"><x'})
    assert r.status_code == 422


def test_generated_files_and_reports_are_capped_per_document(client, templates, monkeypatch):
    from app.config import settings
    from app.database.session import SessionLocal
    from app.models.db import GeneratedFile, ValidationReport
    monkeypatch.setattr(settings, "keep_generated_files", 3)
    h = auth(client, "cap@example.org")
    t = upload_template(client, h, templates["default"])
    d = new_doc(client, h, approve(client, h, t)["id"])
    put_content(client, h, d["id"], SECTION)
    paths = []
    for _ in range(5):
        client.post(f"/api/documents/{d['id']}/generate", headers=h)
        client.post(f"/api/documents/{d['id']}/validate", headers=h)
    with SessionLocal() as db:
        rows = db.query(GeneratedFile).filter_by(document_id=d["id"]).all()
        assert len(rows) == 3 and all(os.path.exists(r.path) for r in rows)
        assert db.query(ValidationReport).filter_by(document_id=d["id"]).count() == 3
    files = os.listdir(os.path.join(settings.data_dir, "generated", str(rows[0].path.split(os.sep)[-2])))
    assert len(files) == 3                                              # old files deleted from disk


# ------------------------------------------------------------------ ownership: every route answers 404 to strangers
def test_every_resource_route_hides_other_users_data(client, templates, image):
    a, b = auth(client, "alice-own@example.org"), auth(client, "bob-own@example.org")
    t = upload_template(client, a, templates["default"])
    pv = approve(client, a, t)
    d = new_doc(client, a, pv["id"])
    put_content(client, a, d["id"], SECTION)
    g = client.post(f"/api/documents/{d['id']}/generate", headers=a).json()
    with open(image, "rb") as f:
        asset = client.post("/api/media/upload", headers=a, files={"file": ("a.png", f, "image/png")}).json()["asset_id"]
    tid, did = t["id"], d["id"]
    calls = [
        ("get", f"/api/templates/{tid}", None), ("post", f"/api/templates/{tid}/analyze", None),
        ("get", f"/api/templates/{tid}/rules", None), ("put", f"/api/templates/{tid}/rules", pv["rules"]),
        ("post", f"/api/templates/{tid}/approve", None), ("get", f"/api/templates/{tid}/profiles", None),
        ("post", f"/api/templates/{tid}/sample", None), ("delete", f"/api/templates/{tid}", None),
        ("get", f"/api/documents/{did}", None), ("put", f"/api/documents/{did}", {"body": []}),
        ("post", f"/api/documents/{did}/generate", None), ("post", f"/api/documents/{did}/preview", None),
        ("post", f"/api/documents/{did}/validate", None), ("get", f"/api/documents/{did}/files", None),
        ("get", f"/api/documents/{did}/files/{g['file_id']}/download", None),
        ("post", f"/api/documents/{did}/pdf", None), ("delete", f"/api/documents/{did}", None),
        ("put", f"/api/documents/{did}/profile", {"profile_id": pv["id"]}),
        ("get", f"/api/media/{asset}", None),
    ]
    for method, url, body in calls:
        r = getattr(client, method)(url, headers=b, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (method, url, r.status_code)
    # Bob cannot build a document on Alice's approved profile either
    r = client.post("/api/documents", headers=b, json={"title": "x", "profile_id": pv["id"]})
    assert r.status_code == 404
    # nor point his own document at it
    tb = upload_template(client, b, templates["default"])
    db_ = new_doc(client, b, approve(client, b, tb)["id"])
    assert client.put(f"/api/documents/{db_['id']}/profile", headers=b, json={"profile_id": pv["id"]}).status_code == 404
    # and Alice's things are all still there
    assert client.get(f"/api/documents/{did}", headers=a).status_code == 200
    assert client.get(f"/api/media/{asset}", headers=a).status_code == 200


def test_another_users_asset_in_my_content_is_not_embedded(client, templates, image):
    a, b = auth(client, "alice-img@example.org"), auth(client, "bob-img@example.org")
    with open(image, "rb") as f:
        asset = client.post("/api/media/upload", headers=a, files={"file": ("a.png", f, "image/png")}).json()["asset_id"]
    t = upload_template(client, b, templates["default"])
    d = new_doc(client, b, approve(client, b, t)["id"])
    put_content(client, b, d["id"], [{"type": "figure", "asset_id": asset, "caption": "Stolen"}])
    g = client.post(f"/api/documents/{d['id']}/generate", headers=b).json()
    assert "FIGURE_MISSING" in {w["code"] for w in g["warnings"]}


def test_document_reports_its_template_and_newer_approved_version(client, templates):
    h = auth(client, "upgrade@example.org")
    t = upload_template(client, h, templates["university"], name="Thesis")
    v1 = approve(client, h, t)
    d = new_doc(client, h, v1["id"])
    assert (d["template_id"], d["template_name"], d["template_version"], d["profile_version"], d["latest_profile_id"]) == \
        (t["id"], "Thesis", 1, 1, v1["id"])
    with open(templates["twocol"], "rb") as f:
        t2 = client.post(f"/api/templates/{t['id']}/versions", headers=h, files={"file": ("2.docx", f, DOCX)}).json()
    assert client.get(f"/api/documents/{d['id']}", headers=h).json()["latest_profile_id"] == v1["id"]   # v2 not approved yet
    v2 = approve(client, h, t2)
    listed = {x["id"]: x for x in client.get("/api/documents", headers=h).json()}
    assert listed[d["id"]]["latest_profile_id"] == v2["id"] and listed[d["id"]]["profile_id"] == v1["id"]


def test_document_lists_template_placeholders_and_saves_fields(client, templates):
    h = auth(client, "fields@example.org")
    t = upload_template(client, h, templates["journal"], name="Journal")
    assert t["profile"]["rules"]["keep_template_layout"] is True
    d = new_doc(client, h, approve(client, h, t)["id"])
    assert {"TITLE", "AUTHORS", "DOI", "VOLUME", "ISSUE"} <= set(d["placeholders"])
    r = client.put(f"/api/documents/{d['id']}", headers=h,
                   json={"title": "T", "fields": {"DOI": "10.1/x", "VOLUME": "2", "ISSUE": "3"}, "body": []})
    assert r.status_code == 200 and r.json()["content"]["fields"]["DOI"] == "10.1/x"
    g = client.post(f"/api/documents/{d['id']}/generate", headers=h).json()
    data = client.get(f"/api/documents/{d['id']}/files/{g['file_id']}/download", headers=h).content
    assert Docx(io.BytesIO(data)).sections[0].header.paragraphs[0].text == "DOI: 10.1/x | Vol. 2, Issue 3"
