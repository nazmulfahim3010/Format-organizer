"""Workflow B: predefined visual designs + form-built articles. Separate from the custom-template routes."""
import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import designs
from ...config import settings
from ...database.session import get_db
from ...designs.generator import generate_article, to_content
from ...designs.sample import sample_article
from ...document_engine.pdf import PdfExportError, docx_to_pdf
from ...models.db import DesignDocument, DesignGeneratedFile, User
from ...schemas.api import DesignDocumentCreate, DesignDocumentDetail, DesignDocumentSummary, DesignSummary, GenerationOut
from ...schemas.article import ArticleContent, ArticleMetadata
from ...services import storage
from ...services.documents import media_resolver, temp_docx
from ...template_engine.analyzer import analyze_template
from ...validation.validator import validate_docx
from ..deps import current_user, heavy, owned

router = APIRouter(tags=["designs"])
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_ANALYSIS: dict = {}


def _design(design_id: str, version=None) -> designs.Design:
    try:
        return designs.load(design_id, version)
    except designs.DesignNotFound:
        raise HTTPException(404, "Design not found.")


def _analysis(d: designs.Design) -> dict:
    key = (d.id, d.version)
    if key not in _ANALYSIS:
        _ANALYSIS[key] = analyze_template(d.base_path)
    return _ANALYSIS[key]


def _rm(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _summary(doc: DesignDocument) -> DesignDocumentSummary:
    return DesignDocumentSummary(id=doc.id, title=doc.title, design_id=doc.design_id, design_version=doc.design_version,
                                 latest_version=designs.versions(doc.design_id)[-1], updated_at=doc.updated_at.isoformat())


def _detail(doc: DesignDocument) -> DesignDocumentDetail:
    return DesignDocumentDetail(**_summary(doc).model_dump(), content=ArticleContent.model_validate(doc.content))


def _build(db: Session, doc: DesignDocument, out: str):
    """Always with the design version the document is pinned to."""
    d = _design(doc.design_id, doc.design_version)
    art = ArticleContent.model_validate(doc.content)
    return d, art, generate_article(d, art, media_resolver(db, doc.owner_id), out)


# ------------------------------------------------------------------ designs
@router.get("/api/designs", response_model=List[DesignSummary])
def list_designs(user: User = Depends(current_user)):
    return [DesignSummary(**designs.summary(d), versions=designs.versions(d.id)) for d in designs.available()]


@router.post("/api/designs/{design_id}/sample", dependencies=[Depends(heavy)])
def design_sample(design_id: str, user: User = Depends(current_user)):
    """The design rendered with a neutral sample article, for the gallery preview."""
    d = _design(design_id)
    out = temp_docx()
    try:
        generate_article(d, sample_article(), lambda _: None, out)
        with open(out, "rb") as f:
            data = f.read()
    finally:
        _rm(out)
    return Response(content=data, media_type=DOCX)


# ------------------------------------------------------------------ articles
@router.post("/api/design-documents", response_model=DesignDocumentDetail)
def create(body: DesignDocumentCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = _design(body.design_id)
    content = ArticleContent(metadata=ArticleMetadata(title=body.title))
    doc = DesignDocument(owner_id=user.id, design_id=d.id, design_version=d.version, title=body.title[:1000],
                         content=content.model_dump())
    db.add(doc)
    db.commit()
    return _detail(doc)


@router.get("/api/design-documents", response_model=List[DesignDocumentSummary])
def list_documents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(DesignDocument).where(DesignDocument.owner_id == user.id)
                      .order_by(DesignDocument.updated_at.desc()))
    return [_summary(r) for r in rows]


@router.get("/api/design-documents/{doc_id}", response_model=DesignDocumentDetail)
def get_document(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _detail(owned(db, DesignDocument, doc_id, user))


@router.put("/api/design-documents/{doc_id}", response_model=DesignDocumentDetail)
def save(doc_id: int, content: ArticleContent, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned(db, DesignDocument, doc_id, user)
    doc.content = content.model_dump()
    doc.title = content.metadata.title[:1000]
    db.commit()
    return _detail(doc)


@router.post("/api/design-documents/{doc_id}/upgrade", response_model=DesignDocumentDetail)
def upgrade(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Move the document to the newest version of its design (otherwise it keeps the one it was made with)."""
    doc = owned(db, DesignDocument, doc_id, user)
    doc.design_version = designs.versions(doc.design_id)[-1]
    db.commit()
    return _detail(doc)


@router.delete("/api/design-documents/{doc_id}", status_code=204)
def delete(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned(db, DesignDocument, doc_id, user)
    for g in db.scalars(select(DesignGeneratedFile).where(DesignGeneratedFile.design_document_id == doc.id)):
        storage.remove_quietly(g.path)
        db.delete(g)
    db.flush()                 # children first: the foreign key is enforced
    db.delete(doc)
    db.commit()
    return Response(status_code=204)


@router.post("/api/design-documents/{doc_id}/preview", dependencies=[Depends(heavy)])
def preview(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned(db, DesignDocument, doc_id, user)
    out = temp_docx()
    try:
        _, _, res = _build(db, doc, out)
        with open(out, "rb") as f:
            data = f.read()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Preview failed: {type(e).__name__}.")
    finally:
        _rm(out)
    return Response(content=data, media_type=DOCX, headers={"X-SmartDoc-Warnings": str(len(res.warnings))})


@router.post("/api/design-documents/{doc_id}/generate", response_model=GenerationOut, dependencies=[Depends(heavy)])
def generate(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned(db, DesignDocument, doc_id, user)
    out = storage.new_path("generated", user.id, "docx")
    try:
        _, _, res = _build(db, doc, out)
    except HTTPException:
        storage.remove_quietly(out)
        raise
    except Exception as e:
        storage.remove_quietly(out)
        raise HTTPException(500, f"Document generation failed: {type(e).__name__}. Your content is saved.")
    g = DesignGeneratedFile(design_document_id=doc.id, design_version=doc.design_version, path=out, warnings=res.warnings)
    db.add(g)
    db.flush()
    rows = list(db.scalars(select(DesignGeneratedFile).where(DesignGeneratedFile.design_document_id == doc.id)
                           .order_by(DesignGeneratedFile.id.desc())))
    for old in rows[settings.keep_generated_files:]:
        storage.remove_quietly(old.path)
        db.delete(old)
    db.commit()
    return GenerationOut(file_id=g.id, created_at=g.created_at.isoformat(), warnings=res.warnings, stats=res.stats)


@router.get("/api/design-documents/{doc_id}/files")
def files(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned(db, DesignDocument, doc_id, user)
    rows = db.scalars(select(DesignGeneratedFile).where(DesignGeneratedFile.design_document_id == doc.id)
                      .order_by(DesignGeneratedFile.id.desc()))
    return [{"file_id": g.id, "created_at": g.created_at.isoformat(), "design_version": g.design_version,
             "warnings": len(g.warnings or [])} for g in rows]


@router.get("/api/design-documents/{doc_id}/files/{file_id}/download")
def download(doc_id: int, file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned(db, DesignDocument, doc_id, user)
    g = db.get(DesignGeneratedFile, file_id)
    if g is None or g.design_document_id != doc.id or not os.path.exists(g.path):
        raise HTTPException(404, "Not found.")
    name = "".join(c for c in (doc.title or "article") if c.isalnum() or c in " -_")[:60].strip() or "article"
    return FileResponse(g.path, media_type=DOCX, filename=f"{name}.docx")


@router.post("/api/design-documents/{doc_id}/validate", dependencies=[Depends(heavy)])
def validate(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned(db, DesignDocument, doc_id, user)
    out = temp_docx()
    try:
        d, art, res = _build(db, doc, out)
        a = _analysis(d)
        report = validate_docx(out, d.profile, to_content(art, d), a["page"], analysis=a)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Validation failed: {type(e).__name__}.")
    finally:
        _rm(out)
    report["generation_warnings"] = res.warnings
    return report


@router.post("/api/design-documents/{doc_id}/pdf", dependencies=[Depends(heavy)])
def pdf(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned(db, DesignDocument, doc_id, user)
    docx_path, pdf_path = temp_docx(), temp_docx() + ".pdf"
    try:
        _build(db, doc, docx_path)
        docx_to_pdf(docx_path, pdf_path)
        with open(pdf_path, "rb") as f:
            data = f.read()
    except PdfExportError as e:
        raise HTTPException(503, str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"PDF export failed: {type(e).__name__}.")
    finally:
        for p in (docx_path, pdf_path):
            _rm(p)
    return Response(content=data, media_type="application/pdf",
                    headers={"X-SmartDoc-Note": "Rendered by LibreOffice; Word may paginate slightly differently."})
