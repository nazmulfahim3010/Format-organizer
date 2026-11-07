import os
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.uploads import MAX_DOCX_BYTES, UploadRejected, check_docx
from ...database.session import get_db
from ...document_engine.generator import generate_docx
from ...document_engine.sample import sample_content, sample_image_bytes
from ...models.db import ALLOW_DELETE, Document, ProfileVersion, Template, TemplateVersion, User, _now
from ...schemas.api import ProfileHistoryItem, ProfileOut, TemplateDetail, TemplateSummary
from ...schemas.profile import FormattingProfile
from ...services import storage
from ...services.documents import temp_docx, temp_file
from ...services.profiles import carry_over, record_user_edits, validate_against_analysis
from ...template_engine.analyzer import analyze_template, build_default_profile
from ..deps import current_user, heavy, owned

router = APIRouter(prefix="/api/templates", tags=["templates"])
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _read_upload(file: UploadFile):
    data = file.file.read(MAX_DOCX_BYTES + 1)
    try:
        checked = check_docx(data, file.filename or "")
    except UploadRejected as e:
        raise HTTPException(422, str(e))
    return data, checked.sha256


def _store_and_analyze(data: bytes, user: User):
    path = storage.new_path("templates", user.id, "docx")
    with open(path, "wb") as f:
        f.write(data)
    try:
        return path, analyze_template(path)
    except Exception:
        storage.remove_quietly(path)
        raise HTTPException(422, "This file could not be read as a Word document.")


def _latest_version(t: Template) -> TemplateVersion:
    return t.versions[-1]


def _latest_profile(db: Session, tv: TemplateVersion) -> ProfileVersion:
    return db.scalars(select(ProfileVersion).where(ProfileVersion.template_version_id == tv.id)
                      .order_by(ProfileVersion.version.desc())).first()


def _detail(db: Session, t: Template) -> TemplateDetail:
    tv = _latest_version(t)
    pv = _latest_profile(db, tv)
    approved = db.scalars(select(ProfileVersion).where(ProfileVersion.template_version_id == tv.id,
                                                       ProfileVersion.approved.is_(True))
                          .order_by(ProfileVersion.version.desc())).first()
    return TemplateDetail(
        id=t.id, name=t.name, version=tv.version, template_version_id=tv.id, analysis=tv.analysis,
        profile=ProfileOut(id=pv.id, version=pv.version, approved=pv.approved,
                           rules=FormattingProfile.model_validate(pv.rules)),
        approved_profile_id=approved.id if approved else None)


@router.post("/upload", response_model=TemplateDetail, dependencies=[Depends(heavy)])
def upload(file: UploadFile = File(...), name: str = Form(""), user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    data, sha = _read_upload(file)
    path, analysis = _store_and_analyze(data, user)
    title = (name or os.path.splitext(file.filename or "Template")[0])[:200]
    t = Template(owner_id=user.id, name=title)
    db.add(t)
    db.flush()
    tv = TemplateVersion(template_id=t.id, version=1, file_path=path, original_filename=file.filename or "",
                         sha256=sha, analysis=analysis)
    db.add(tv)
    db.flush()
    draft = build_default_profile(analysis, title)
    db.add(ProfileVersion(template_version_id=tv.id, version=1, rules=draft.model_dump()))
    db.commit()
    db.refresh(t)
    return _detail(db, t)


@router.get("", response_model=List[TemplateSummary])
def list_templates(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for t in db.scalars(select(Template).where(Template.owner_id == user.id).order_by(Template.id.desc())):
        tv = _latest_version(t)
        pv = _latest_profile(db, tv)
        approved = db.scalars(select(ProfileVersion).where(ProfileVersion.template_version_id == tv.id,
                                                           ProfileVersion.approved.is_(True))
                              .order_by(ProfileVersion.version.desc())).first()
        out.append(TemplateSummary(id=t.id, name=t.name, versions=len(t.versions),
                                   latest_profile_approved=pv.approved,
                                   approved_profile_id=approved.id if approved else None,
                                   created_at=t.created_at.isoformat()))
    return out


@router.get("/{template_id}", response_model=TemplateDetail)
def get_template(template_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _detail(db, owned(db, Template, template_id, user))


@router.post("/{template_id}/analyze", response_model=TemplateDetail)
def reanalyze(template_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, Template, template_id, user)
    tv = _latest_version(t)
    tv.analysis = analyze_template(tv.file_path)
    db.commit()
    return _detail(db, t)


@router.get("/{template_id}/rules", response_model=ProfileOut)
def get_rules(template_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _detail(db, owned(db, Template, template_id, user)).profile


@router.put("/{template_id}/rules", response_model=ProfileOut)
def put_rules(template_id: int, rules: FormattingProfile, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    t = owned(db, Template, template_id, user)
    tv = _latest_version(t)
    pv = _latest_profile(db, tv)
    rules = record_user_edits(FormattingProfile.model_validate(pv.rules), rules)
    if pv.approved:   # approved versions are immutable: an edit starts a new draft version
        pv = ProfileVersion(template_version_id=tv.id, version=pv.version + 1, rules=rules.model_dump())
        db.add(pv)
    else:
        pv.rules = rules.model_dump()
    db.commit()
    db.refresh(pv)
    return ProfileOut(id=pv.id, version=pv.version, approved=pv.approved, rules=rules)


@router.get("/{template_id}/profiles", response_model=List[ProfileHistoryItem])
def profile_history(template_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Every profile version of every template version, newest first (documents pin one of these)."""
    t = owned(db, Template, template_id, user)
    out = []
    for tv in sorted(t.versions, key=lambda v: -v.version):
        for pv in db.scalars(select(ProfileVersion).where(ProfileVersion.template_version_id == tv.id)
                             .order_by(ProfileVersion.version.desc())):
            out.append(ProfileHistoryItem(
                id=pv.id, template_version=tv.version, version=pv.version, approved=pv.approved,
                approved_at=pv.approved_at.isoformat() if pv.approved_at else None,
                created_at=pv.created_at.isoformat(), rules=FormattingProfile.model_validate(pv.rules)))
    return out


@router.post("/{template_id}/approve", response_model=ProfileOut)
def approve(template_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, Template, template_id, user)
    tv = _latest_version(t)
    pv = _latest_profile(db, tv)
    rules = FormattingProfile.model_validate(pv.rules)
    problems = validate_against_analysis(rules, tv.analysis)
    if problems:
        raise HTTPException(422, " ".join(problems))
    if not pv.approved:
        pv.approved, pv.approved_at = True, _now()
        db.commit()
    return ProfileOut(id=pv.id, version=pv.version, approved=True, rules=rules)


@router.post("/{template_id}/versions", response_model=TemplateDetail, dependencies=[Depends(heavy)])
def new_version(template_id: int, file: UploadFile = File(...), user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    t = owned(db, Template, template_id, user)
    data, sha = _read_upload(file)
    path, analysis = _store_and_analyze(data, user)
    old_tv = _latest_version(t)
    old_pv = _latest_profile(db, old_tv)
    tv = TemplateVersion(template_id=t.id, version=old_tv.version + 1, file_path=path,
                         original_filename=file.filename or "", sha256=sha, analysis=analysis)
    db.add(tv)
    db.flush()
    draft = carry_over(FormattingProfile.model_validate(old_pv.rules), analysis)
    db.add(ProfileVersion(template_version_id=tv.id, version=1, rules=draft.model_dump()))
    db.commit()
    db.refresh(t)
    return _detail(db, t)


def _rm(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


@router.post("/{template_id}/sample", dependencies=[Depends(heavy)])
def sample(template_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Render a built-in sample with the CURRENT (even unapproved) rules so edits can be previewed."""
    t = owned(db, Template, template_id, user)
    tv = _latest_version(t)
    rules = FormattingProfile.model_validate(_latest_profile(db, tv).rules)
    img, out = temp_file(".png"), temp_docx()
    with open(img, "wb") as f:
        f.write(sample_image_bytes())
    try:
        generate_docx(tv.file_path, rules, sample_content(rules.language.code),
                      lambda aid: img if aid == "__sample__" else None, out)
        with open(out, "rb") as f:
            data = f.read()
    finally:
        _rm(img)
        _rm(out)
    return Response(content=data, media_type=DOCX)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned(db, Template, template_id, user)
    profiles = [p for tv in t.versions
                for p in db.scalars(select(ProfileVersion).where(ProfileVersion.template_version_id == tv.id))]
    ids = [p.id for p in profiles]
    used = db.scalar(select(func.count()).select_from(Document).where(Document.profile_version_id.in_(ids))) if ids else 0
    if used:
        raise HTTPException(409, f"{used} document(s) use this template. Delete them first.")
    db.info[ALLOW_DELETE] = True          # the whole template goes, and no document uses it
    for p in profiles:
        db.delete(p)
    for tv in t.versions:
        storage.remove_quietly(tv.file_path)
        db.delete(tv)
    db.delete(t)
    db.commit()
    return Response(status_code=204)
