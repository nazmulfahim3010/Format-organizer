"""Database models. Formatting profiles are separate from documents: one approved
profile version can be used by many documents, and each document stores the exact
profile version it was built with so old documents stay reproducible."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, event, inspect
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from ..database.session import Base


def _now() -> datetime:
    """Naive UTC (SQLite stores no zone); utcnow() is deprecated."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ImmutableVersionError(RuntimeError):
    """An approved profile version was about to be changed or deleted."""


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    versions: Mapped[List["TemplateVersion"]] = relationship(back_populates="template", order_by="TemplateVersion.version")


class TemplateVersion(Base):
    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    analysis: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    template: Mapped[Template] = relationship(back_populates="versions")


class ProfileVersion(Base):
    """The FormattingProfile entity: rules JSON, versioned per template version."""
    __tablename__ = "profile_versions"
    __table_args__ = (UniqueConstraint("template_version_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    template_version_id: Mapped[int] = mapped_column(ForeignKey("template_versions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    rules: Mapped[dict] = mapped_column(JSON)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


FROZEN_FIELDS = ("rules", "approved", "template_version_id", "version")
ALLOW_DELETE = "allow_deleting_approved_profiles"   # session.info flag: deleting a whole unused template


@event.listens_for(Session, "before_flush")
def _approved_profiles_are_immutable(session, _ctx, _instances) -> None:
    """Approved ProfileVersion rows never change. Edits go to a new draft version (rule 2).
    Enforced here, not only in the route, so no code path can rewrite history."""
    for obj in session.dirty:
        if not isinstance(obj, ProfileVersion):
            continue
        state = inspect(obj)
        was = state.attrs.approved.history
        was_approved = was.deleted[0] if was.deleted else obj.approved
        if was_approved and any(state.attrs[f].history.has_changes() for f in FROZEN_FIELDS):
            raise ImmutableVersionError(f"Profile version {obj.id} is approved and cannot be changed.")
    if not session.info.get(ALLOW_DELETE):
        for obj in session.deleted:
            if isinstance(obj, ProfileVersion) and obj.approved:
                raise ImmutableVersionError(f"Profile version {obj.id} is approved and cannot be deleted.")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    profile_version_id: Mapped[int] = mapped_column(ForeignKey("profile_versions.id"))
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class GeneratedFile(Base):
    """Every generation is kept, so earlier versions can be downloaded."""
    __tablename__ = "generated_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    profile_version_id: Mapped[int] = mapped_column(ForeignKey("profile_versions.id"))
    path: Mapped[str] = mapped_column(String(500))
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class MediaAsset(Base):
    __tablename__ = "media_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    path: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(50))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ValidationReport(Base):
    __tablename__ = "validation_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    profile_version_id: Mapped[int] = mapped_column(ForeignKey("profile_versions.id"))
    report: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# --------------------------------------------------------------------------- predefined designs (additive tables)
class DesignDocument(Base):
    """An article written with a predefined visual design. Pins the design version it was made with."""
    __tablename__ = "design_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    design_id: Mapped[str] = mapped_column(String(40))
    design_version: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(1000), default="")
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class DesignGeneratedFile(Base):
    __tablename__ = "design_generated_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    design_document_id: Mapped[int] = mapped_column(ForeignKey("design_documents.id"), index=True)
    design_version: Mapped[str] = mapped_column(String(20))
    path: Mapped[str] = mapped_column(String(500))
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
