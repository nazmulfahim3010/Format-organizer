import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import settings
from ...database.session import get_db
from ...document_engine.pdf import PdfExportError, docx_to_pdf
from ...models.db import Document, GeneratedFile, ProfileVersion, TemplateVersion, Template, User, ValidationReport
from ...schemas.api import (DocumentCreate, DocumentDetail, DocumentSummary, DocumentSwitchProfile, GenerationOut)
from ...schemas.content import DocumentContent
from ...services import storage
from ...services.documents import build_docx, load_context, temp_docx
from ...validation.validator import validate_docx
from ..deps import current_user, heavy, owned

router = APIRouter(prefix="/api/documents", tags=["documents"])
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _approved_profile(db: Session, profile_id: int, user: User) -> ProfileVersion:
    pv = db.get(ProfileVersion, profile_id)
    tv = db.get(TemplateVersion, pv.template_version_id) if pv else None
    t = db.get(Template, tv.template_id) if tv else None
    if pv is None or t is None or t.owner_id != user.id:
        raise HTTPException(404, "Profile not found.")
    if not pv.approved:
        raise HTTPException(422, "Approve the formatting profile before creating documents with it.")
    return pv


def _prune(db: Session, model, doc_id: int, path_attr: str = "") -> None:
    """Keep the newest `keep_generated_files` rows per document (and their files on disk)."""
    rows = list(db.scalars(select(model).where(model.document_id == doc_id).order_by(model.id.desc())))
    for old in rows[settings.keep_generated_files:]:
        if path_attr:
            storage.remove_quietly(getattr(old, path_attr))
        db.delete(old)


def _summary(db: Session, d: Document) -> DocumentSummary:
    """Which template / version the document is built with, and the newest approved profile of
    that template (so the editor can offer an upgrade)."""
    pv = db.get(ProfileVersion, d.profile_version_id)
    tv = db.get(TemplateVersion, pv.template_version_id)
    t = db.get(Template, tv.template_id)
    latest = db.scalars(select(ProfileVersion).join(TemplateVersion, ProfileVersion.template_version_id == TemplateVersion.id)
                        .where(TemplateVersion.template_id == t.id, ProfileVersion.approved.is_(True))
                        .order_by(TemplateVersion.version.desc(), ProfileVersion.version.desc())).first()
    return DocumentSummary(id=d.id, title=d.title, profile_id=d.profile_version_id, updated_at=d.updated_at.isoformat(),
                           template_id=t.id, template_name=t.name, template_version=tv.version,
                           profile_version=pv.version, latest_profile_id=latest.id if latest else None)


def _detail(db: Session, d: Document) -> DocumentDetail:
    tv = db.get(TemplateVersion, db.get(ProfileVersion, d.profile_version_id).template_version_id)
    names = [p["name"] for p in (tv.analysis or {}).get("placeholders", [])]
    return DocumentDetail(**_summary(db, d).model_dump(), content=DocumentContent.model_validate(d.content),
                          placeholders=names)


@router.post("", response_model=DocumentDetail)
def create(body: DocumentCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    pv = _approved_profile(db, body.profile_id, user)
    content = DocumentContent(language=body.language, title=body.title)
    d = Document(owner_id=user.id, title=body.title, profile_version_id=pv.id, content=content.model_dump())
    db.add(d)
    db.commit()
    return _detail(db, d)


@router.get("", response_model=List[DocumentSummary])
def list_documents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_summary(db, d) for d in db.scalars(select(Document).where(Document.owner_id == user.id)
                                            .order_by(Document.updated_at.desc()))]


@router.get("/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _detail(db, owned(db, Document, doc_id, user))


@router.put("/{doc_id}", response_model=DocumentDetail)
def save(doc_id: int, content: DocumentContent, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, doc_id, user)
    d.content = content.model_dump()
    d.title = (content.title or d.title)[:300]
    db.commit()
    return _detail(db, d)


@router.put("/{doc_id}/profile", response_model=DocumentDetail)
def switch_profile(doc_id: int, body: DocumentSwitchProfile, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Same content, different template: the point of separating content from formatting."""
    d = owned(db, Document, doc_id, user)
    d.profile_version_id = _approved_profile(db, body.profile_id, user).id
    db.commit()
    return _detail(db, d)


@router.delete("/{doc_id}", status_code=204)
def delete(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, doc_id, user)
    for g in db.scalars(select(GeneratedFile).where(GeneratedFile.document_id == d.id)):
        storage.remove_quietly(g.path)
        db.delete(g)
    for r in db.scalars(select(ValidationReport).where(ValidationReport.document_id == d.id)):
        db.delete(r)
    db.delete(d)
    db.commit()
    return Response(status_code=204)


@router.post("/{doc_id}/generate", response_model=GenerationOut, dependencies=[Depends(heavy)])
def generate(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, doc_id, user)
    out = storage.new_path("generated", user.id, "docx")
    try:
        res = build_docx(db, d, out)
    except Exception as e:   # a failed generation must never lose the user's content
        storage.remove_quietly(out)
        raise HTTPException(500, f"Document generation failed: {type(e).__name__}. Your content is saved.")
    g = GeneratedFile(document_id=d.id, profile_version_id=d.profile_version_id, path=out, warnings=res.warnings)
    db.add(g)
    db.flush()
    _prune(db, GeneratedFile, d.id, "path")
    db.commit()
    return GenerationOut(file_id=g.id, created_at=g.created_at.isoformat(), warnings=res.warnings, stats=res.stats)


@router.post("/{doc_id}/preview", dependencies=[Depends(heavy)])
def preview(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Generate a throw-away DOCX for the live preview pane (not stored as a version)."""
    d = owned(db, Document, doc_id, user)
    out = temp_docx()
    try:
        res = build_docx(db, d, out)
        with open(out, "rb") as f:
            data = f.read()
    except Exception as e:
        raise HTTPException(500, f"Preview failed: {type(e).__name__}.")
    finally:
        try:
            os.remove(out)
        except OSError:
            pass
    return Response(content=data, media_type=DOCX,
                    headers={"X-SmartDoc-Warnings": str(len(res.warnings))})


@router.post("/{doc_id}/validate", dependencies=[Depends(heavy)])
def validate(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, doc_id, user)
    pv, tv, profile, content = load_context(db, d)
    out = temp_docx()
    try:
        res = build_docx(db, d, out)
        report = validate_docx(out, profile, content, tv.analysis["page"], analysis=tv.analysis)
    except Exception as e:
        raise HTTPException(500, f"Validation failed: {type(e).__name__}.")
    finally:
        try:
            os.remove(out)
        except OSError:
            pass
    report["generation_warnings"] = res.warnings
    db.add(ValidationReport(document_id=d.id, profile_version_id=pv.id, report=report))
    db.flush()
    _prune(db, ValidationReport, d.id)
    db.commit()
    return report


@router.get("/{doc_id}/files")
def files(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, doc_id, user)
    rows = db.scalars(select(GeneratedFile).where(GeneratedFile.document_id == d.id).order_by(GeneratedFile.id.desc()))
    return [{"file_id": g.id, "created_at": g.created_at.isoformat(), "profile_id": g.profile_version_id,
             "warnings": len(g.warnings or [])} for g in rows]


@router.get("/{doc_id}/files/{file_id}/download")
def download(doc_id: int, file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, doc_id, user)
    g = db.get(GeneratedFile, file_id)
    if g is None or g.document_id != d.id or not os.path.exists(g.path):
        raise HTTPException(404, "Not found.")
    name = "".join(c for c in (d.title or "document") if c.isalnum() or c in " -_")[:60].strip() or "document"
    return FileResponse(g.path, media_type=DOCX, filename=f"{name}.docx")


@router.post("/{doc_id}/pdf", dependencies=[Depends(heavy)])
def pdf(doc_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = owned(db, Document, doc_id, user)
    docx_path, pdf_path = temp_docx(), temp_docx() + ".pdf"
    try:
        build_docx(db, d, docx_path)
        docx_to_pdf(docx_path, pdf_path)
        with open(pdf_path, "rb") as f:
            data = f.read()
    except PdfExportError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"PDF export failed: {type(e).__name__}.")
    finally:
        for p in (docx_path, pdf_path):
            try:
                os.remove(p)
            except OSError:
                pass
    return Response(content=data, media_type="application/pdf",
                    headers={"X-SmartDoc-Note": "Rendered by LibreOffice; Word may paginate slightly differently."})
