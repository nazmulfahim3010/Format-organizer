import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from .article import ArticleContent
from .content import LANG_PATTERN, DocumentContent
from .profile import FormattingProfile

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=200)
    name: str = Field("", max_length=120)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL.match(v) or len(v) > 255:
            raise ValueError("Enter a valid email address.")
        return v


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=1024)


class UserOut(BaseModel):
    id: int
    email: str
    name: str


class TokenOut(BaseModel):
    token: str
    user: UserOut


class ProfileOut(BaseModel):
    id: int
    version: int
    approved: bool
    rules: FormattingProfile


class TemplateSummary(BaseModel):
    id: int
    name: str
    versions: int
    latest_profile_approved: bool
    approved_profile_id: Optional[int] = None
    created_at: str


class TemplateDetail(BaseModel):
    id: int
    name: str
    version: int
    template_version_id: int
    analysis: Dict[str, Any]
    profile: ProfileOut
    approved_profile_id: Optional[int] = None


class DocumentCreate(BaseModel):
    title: str = Field("", max_length=300)
    profile_id: int
    language: str = Field("en", max_length=20, pattern=LANG_PATTERN)


class ProfileHistoryItem(BaseModel):
    id: int
    template_version: int
    version: int
    approved: bool
    approved_at: Optional[str] = None
    created_at: str
    rules: FormattingProfile


class DocumentSwitchProfile(BaseModel):
    profile_id: int


class DocumentSummary(BaseModel):
    id: int
    title: str
    profile_id: int
    updated_at: str
    template_id: int
    template_name: str
    template_version: int
    profile_version: int
    latest_profile_id: Optional[int] = None       # newest approved profile of the same template


class DocumentDetail(DocumentSummary):
    content: DocumentContent
    placeholders: List[str] = []          # {{NAME}}s in the document's template (body and headers/footers)


class GenerationOut(BaseModel):
    file_id: int
    created_at: str
    warnings: List[Dict[str, str]]
    stats: Dict[str, int] = {}


class PasteIn(BaseModel):
    text: Optional[str] = Field(None, max_length=2_000_000)
    html: Optional[str] = Field(None, max_length=4_000_000)
    format: Optional[str] = None   # force "html" | "markdown" | "text"

    @field_validator("format")
    @classmethod
    def _fmt(cls, v):
        if v not in (None, "html", "markdown", "text"):
            raise ValueError("format must be html, markdown or text")
        return v


class PasteOut(BaseModel):
    boxes: List[Dict[str, Any]]
    title: str
    warnings: List[Dict[str, str]]
    source_format: str


# --------------------------------------------------------------------------- predefined designs
class DesignSummary(BaseModel):
    id: str
    version: str
    name: str
    description: str
    versions: List[str]


class DesignDocumentCreate(BaseModel):
    design_id: str = Field(..., max_length=40)
    title: str = Field("", max_length=1000)


class DesignDocumentSummary(BaseModel):
    id: int
    title: str
    design_id: str
    design_version: str
    latest_version: str
    updated_at: str


class DesignDocumentDetail(DesignDocumentSummary):
    content: ArticleContent
