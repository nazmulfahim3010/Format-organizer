"""Glue between database rows and the generation/validation engines."""
import os
import tempfile
from typing import Callable, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..document_engine.generator import GenerationResult, generate_docx
from ..models.db import Document, MediaAsset, ProfileVersion, TemplateVersion
from ..schemas.content import DocumentContent
from ..schemas.profile import FormattingProfile


def load_context(db: Session, doc: Document):
    pv = db.get(ProfileVersion, doc.profile_version_id)
    tv = db.get(TemplateVersion, pv.template_version_id)
    if not os.path.exists(tv.file_path):
        raise HTTPException(500, "The template file is missing on the server.")
    return pv, tv, FormattingProfile.model_validate(pv.rules), DocumentContent.model_validate(doc.content)


def media_resolver(db: Session, owner_id: int) -> Callable[[str], Optional[str]]:
    def resolve(asset_id: str) -> Optional[str]:
        a = db.get(MediaAsset, asset_id)
        return a.path if a is not None and a.owner_id == owner_id and os.path.exists(a.path) else None
    return resolve


def build_docx(db: Session, doc: Document, out_path: str) -> GenerationResult:
    pv, tv, profile, content = load_context(db, doc)
    return generate_docx(tv.file_path, profile, content, media_resolver(db, doc.owner_id), out_path)


def temp_file(suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="smartdoc-")
    os.close(fd)
    return path


def temp_docx() -> str:
    return temp_file(".docx")
