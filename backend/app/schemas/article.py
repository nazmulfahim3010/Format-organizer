"""Article document schema for predefined designs (component 1 of 3).

Describes WHAT a research article contains: metadata, abstract, keywords, a free body of the shared content
boxes (any section structure), optional declarations and references. It says nothing about how anything looks;
that belongs to a visual design profile (`app/designs/`). Inline markup is the shared one (**bold** etc.).
"""
from __future__ import annotations

import re
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .content import Box, DocumentContent, check_schema_version

ARTICLE_SCHEMA_VERSION = 1
ORCID = re.compile(r"^(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Affiliation(_Strict):
    id: str = Field(..., min_length=1, max_length=10)       # the marker shown after author names ("1", "a")
    department: str = Field("", max_length=300)
    institution: str = Field("", max_length=300)
    city: str = Field("", max_length=120)
    country: str = Field("", max_length=120)


class ArticleAuthor(_Strict):
    name: str = Field(..., min_length=1, max_length=200)
    affiliations: List[str] = Field(default_factory=list, max_length=20)
    corresponding: bool = False
    orcid: Optional[str] = None

    @field_validator("orcid")
    @classmethod
    def _orcid(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        m = ORCID.match(v.strip())
        if not m:
            raise ValueError("ORCID must look like 0000-0002-1825-0097")
        return m.group(1)


class ArticleMetadata(_Strict):
    title: str = Field("", max_length=1000)
    authors: List[ArticleAuthor] = Field(default_factory=list, max_length=100)
    affiliations: List[Affiliation] = Field(default_factory=list, max_length=100)
    corresponding_email: str = Field("", max_length=254)
    doi: str = Field("", max_length=200)
    volume: str = Field("", max_length=40)
    issue: str = Field("", max_length=40)
    pages: str = Field("", max_length=40)
    year: str = Field("", max_length=10)
    received: str = Field("", max_length=60)
    accepted: str = Field("", max_length=60)
    published: str = Field("", max_length=60)

    @model_validator(mode="after")
    def _consistent(self) -> "ArticleMetadata":
        ids = [a.id for a in self.affiliations]
        if len(ids) != len(set(ids)):
            raise ValueError("affiliation ids must be unique")
        for au in self.authors:
            missing = [x for x in au.affiliations if x not in ids]
            if missing:
                raise ValueError(f"author '{au.name}' refers to unknown affiliation(s) {missing}")
        if sum(a.corresponding for a in self.authors) > 1:
            raise ValueError("only one corresponding author can be marked")
        return self

    @property
    def corresponding_author(self) -> Optional[ArticleAuthor]:
        return next((a for a in self.authors if a.corresponding), None)


class BackMatter(_Strict):
    """Optional closing statements; empty ones are left out of the document."""
    acknowledgements: str = Field("", max_length=20_000)
    competing_interests: str = Field("", max_length=20_000)
    ai_declaration: str = Field("", max_length=20_000)
    funding: str = Field("", max_length=20_000)


class ArticleContent(_Strict):
    schema_version: int = ARTICLE_SCHEMA_VERSION
    language: str = "en"
    metadata: ArticleMetadata = Field(default_factory=ArticleMetadata)
    abstract: str = Field("", max_length=20_000)
    keywords: List[str] = Field(default_factory=list, max_length=50)
    body: List[Box] = Field(default_factory=list)
    back_matter: BackMatter = Field(default_factory=BackMatter)
    references: List[str] = Field(default_factory=list, max_length=2000)

    @field_validator("schema_version")
    @classmethod
    def _version(cls, v: int) -> int:
        return check_schema_version(v, ARTICLE_SCHEMA_VERSION)

    @model_validator(mode="after")
    def _body_limits(self) -> "ArticleContent":
        # the same nesting/size limits as every other document
        DocumentContent(language=self.language, body=self.body)
        return self
