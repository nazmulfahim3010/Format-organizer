"""Workflow B through the API: predefined designs and form-built articles."""
import io

import pytest
from docx import Document as Docx

from tests import design_articles as A
from tests.api_helpers import auth
from tests.conftest import needs_soffice


def new_article(client, h, title="My Article"):
    r = client.post("/api/design-documents", headers=h, json={"design_id": "ijpcr", "title": title})
    assert r.status_code == 200, r.text
    return r.json()


def test_designs_are_listed(client):
    h = auth(client, "designs-list@example.org")
    r = client.get("/api/designs", headers=h).json()
    assert [d["id"] for d in r] == ["ijpcr"] and r[0]["versions"] == ["v1"] and r[0]["name"] == "IJPCR research paper"
    assert client.get("/api/designs").status_code == 401


def test_sample_preview_is_a_docx(client):
    h = auth(client, "designs-sample@example.org")
    r = client.post("/api/designs/ijpcr/sample", headers=h)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert client.post("/api/designs/nope/sample", headers=h).status_code == 404


def test_full_article_flow(client, image):
    h = auth(client, "designs-flow@example.org")
    d = new_article(client, h)
    assert d["design_version"] == "v1" and d["content"]["metadata"]["title"] == "My Article"
    with open(image, "rb") as f:
        asset = client.post("/api/media/upload", headers=h, files={"file": ("a.png", f, "image/png")}).json()["asset_id"]
    content = A.multi_sections()
    fig = content["body"][3]["content"][1]["content"][1]                         # "Analysis" -> the figure
    assert fig["type"] == "figure"
    fig["asset_id"] = asset
    r = client.put(f"/api/design-documents/{d['id']}", headers=h, json=content)
    assert r.status_code == 200 and r.json()["title"].startswith("Water Scarcity")
    pv = client.post(f"/api/design-documents/{d['id']}/preview", headers=h)
    assert pv.status_code == 200 and pv.content[:2] == b"PK"
    g = client.post(f"/api/design-documents/{d['id']}/generate", headers=h).json()
    assert "FIGURE_MISSING" not in {w["code"] for w in g["warnings"]}
    data = client.get(f"/api/design-documents/{d['id']}/files/{g['file_id']}/download", headers=h).content
    doc = Docx(io.BytesIO(data))
    assert doc.tables[0].rows[0].cells[0].text == "RESEARCH ARTICLE"
    assert [p.text for p in doc.paragraphs if p.style.style_id == "IJPCRHeading1"][0] == "Introduction"
    rep = client.post(f"/api/design-documents/{d['id']}/validate", headers=h).json()
    assert not [c for c in rep["checks"] if c["status"] == "failed"], [c for c in rep["checks"] if c["status"] == "failed"]
    assert client.get(f"/api/design-documents/{d['id']}/files", headers=h).json()[0]["design_version"] == "v1"
    listed = client.get("/api/design-documents", headers=h).json()
    assert [x["id"] for x in listed] == [d["id"]]


def test_custom_template_documents_are_separate(client):
    h = auth(client, "designs-separate@example.org")
    new_article(client, h)
    assert client.get("/api/documents", headers=h).json() == []                  # Workflow A list unchanged


def test_invalid_article_content_is_rejected(client):
    h = auth(client, "designs-invalid@example.org")
    d = new_article(client, h)
    bad = {"metadata": {"title": "T", "authors": [{"name": "A", "affiliations": ["9"]}]}}
    assert client.put(f"/api/design-documents/{d['id']}", headers=h, json=bad).status_code == 422
    assert client.put(f"/api/design-documents/{d['id']}", headers=h, json={"font": "Arial"}).status_code == 422
    assert client.post("/api/design-documents", headers=h, json={"design_id": "../x"}).status_code == 404


def test_documents_keep_their_design_version_until_upgraded(client, monkeypatch):
    from app import designs
    h = auth(client, "designs-version@example.org")
    d = new_article(client, h)
    real = designs.versions
    monkeypatch.setattr(designs, "versions", lambda i: real(i) + ["v2"])         # a newer version is published
    got = client.get(f"/api/design-documents/{d['id']}", headers=h).json()
    assert got["design_version"] == "v1" and got["latest_version"] == "v2"
    up = client.post(f"/api/design-documents/{d['id']}/upgrade", headers=h).json()
    assert up["design_version"] == "v2"


def test_other_users_get_404_everywhere(client):
    a, b = auth(client, "designs-alice@example.org"), auth(client, "designs-bob@example.org")
    d = new_article(client, a)
    client.put(f"/api/design-documents/{d['id']}", headers=a, json=A.short_intro())
    g = client.post(f"/api/design-documents/{d['id']}/generate", headers=a).json()
    did = d["id"]
    for method, url, body in [("get", f"/api/design-documents/{did}", None),
                              ("put", f"/api/design-documents/{did}", A.short_intro()),
                              ("post", f"/api/design-documents/{did}/preview", None),
                              ("post", f"/api/design-documents/{did}/generate", None),
                              ("post", f"/api/design-documents/{did}/validate", None),
                              ("post", f"/api/design-documents/{did}/pdf", None),
                              ("post", f"/api/design-documents/{did}/upgrade", None),
                              ("get", f"/api/design-documents/{did}/files", None),
                              ("get", f"/api/design-documents/{did}/files/{g['file_id']}/download", None),
                              ("delete", f"/api/design-documents/{did}", None)]:
        r = getattr(client, method)(url, headers=b, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (method, url, r.status_code)
    assert client.get(f"/api/design-documents/{did}", headers=a).status_code == 200


def test_delete_removes_generated_files(client):
    from app.database.session import SessionLocal
    from app.models.db import DesignGeneratedFile
    h = auth(client, "designs-delete@example.org")
    d = new_article(client, h)
    client.post(f"/api/design-documents/{d['id']}/generate", headers=h)
    assert client.delete(f"/api/design-documents/{d['id']}", headers=h).status_code == 204
    with SessionLocal() as db:
        assert db.query(DesignGeneratedFile).filter_by(design_document_id=d["id"]).count() == 0
    assert client.get(f"/api/design-documents/{d['id']}", headers=h).status_code == 404


@needs_soffice
def test_pdf_export(client):
    h = auth(client, "designs-pdf@example.org")
    d = new_article(client, h)
    client.put(f"/api/design-documents/{d['id']}", headers=h, json=A.short_intro())
    r = client.post(f"/api/design-documents/{d['id']}/pdf", headers=h)
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
