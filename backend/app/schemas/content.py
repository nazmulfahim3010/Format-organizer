"""Content model: the document is a tree of *boxes*.

Content never carries formatting. Inline emphasis uses a tiny markup that the
generator turns into runs:  **bold**  *italic*  ^sup^  ~sub~  (backslash escapes).
"""
from __future__ import annotations

import re
from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1
MAX_LIST_DEPTH = 9          # Word list levels 0..8
MAX_SECTION_DEPTH = 20      # headings stop at 9 (generator clamps and warns); this only stops recursion bombs
MAX_TABLE_COLUMNS = 63      # Word's maximum
MAX_TABLE_ROWS = 10000
# BCP-47-shaped: "en", "bn-BD", "zh-Hans-CN"
LANG_PATTERN = r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}$"
FIELD_KEY = re.compile(r"^[A-Za-z0-9_]{1,40}$")


class _Strict(BaseModel):
    """Content carries data only: unknown keys (fonts, colours, sizes...) are rejected, never stored."""
    model_config = ConfigDict(extra="forbid")


def check_schema_version(v: int, latest: int = SCHEMA_VERSION) -> int:
    if not 1 <= v <= latest:
        raise ValueError(f"schema_version {v} is not supported (this server understands 1..{latest})")
    return v


class Author(_Strict):
    name: str = ""
    affiliation: str = ""
    email: str = ""


class ParagraphBox(_Strict):
    type: Literal["paragraph"] = "paragraph"
    text: str = ""


class ListItem(_Strict):
    text: str = ""
    children: List["ListItem"] = Field(default_factory=list)


class ListBox(_Strict):
    type: Literal["list"] = "list"
    ordered: bool = False
    items: List[ListItem] = Field(default_factory=list)


class TableBox(_Strict):
    """User supplies data + caption only. Look comes from the profile."""
    type: Literal["table"] = "table"
    caption: str = ""
    data: List[List[str]] = Field(default_factory=list, max_length=MAX_TABLE_ROWS)
    header_rows: int = Field(1, ge=0)
    note: str = ""
    source: str = ""

    @field_validator("data")
    @classmethod
    def _rectangular(cls, v: List[List[str]]) -> List[List[str]]:
        if not v:
            return v
        width = max(len(r) for r in v)
        if width > MAX_TABLE_COLUMNS:
            raise ValueError(f"a table may have at most {MAX_TABLE_COLUMNS} columns (got {width})")
        return [list(r) + [""] * (width - len(r)) for r in v]

    @model_validator(mode="after")
    def _clamp_header_rows(self) -> "TableBox":
        self.header_rows = min(self.header_rows, len(self.data))
        return self


class FigureBox(_Strict):
    """User supplies the image + caption only."""
    type: Literal["figure"] = "figure"
    asset_id: Optional[str] = None
    caption: str = ""
    source: str = ""
    # set by the paste normalizer when an image could not be captured
    src: Optional[str] = None


class SectionBox(_Strict):
    type: Literal["section"] = "section"
    id: str = ""
    title: str = ""
    content: List["Box"] = Field(default_factory=list)


Box = Annotated[
    Union[SectionBox, ParagraphBox, ListBox, TableBox, FigureBox],
    Field(discriminator="type"),
]

ListItem.model_rebuild()
SectionBox.model_rebuild()


class DocumentContent(_Strict):
    schema_version: int = SCHEMA_VERSION
    language: str = Field("en", pattern=LANG_PATTERN)
    title: str = ""
    subtitle: str = ""
    authors: List[Author] = Field(default_factory=list)
    abstract: str = ""
    keywords: List[str] = Field(default_factory=list)
    body: List[Box] = Field(default_factory=list)
    # values for the template's {{PLACEHOLDERS}} (DOI, VOLUME, RECEIVED_DATE ...); plain text
    fields: Dict[str, str] = Field(default_factory=dict, max_length=200)

    @field_validator("fields")
    @classmethod
    def _fields(cls, v: Dict[str, str]) -> Dict[str, str]:
        for k, val in v.items():
            if not FIELD_KEY.match(k):
                raise ValueError(f"template field name '{k[:40]}' may only use letters, digits and _")
            if len(val) > 10_000:
                raise ValueError(f"template field '{k}' is too long")
        return v

    @field_validator("schema_version")
    @classmethod
    def _version(cls, v: int) -> int:
        return check_schema_version(v)

    @model_validator(mode="after")
    def _depth_limits(self) -> "DocumentContent":
        def items(xs, depth):
            for it in xs:
                if depth > MAX_LIST_DEPTH:
                    raise ValueError(f"lists may nest at most {MAX_LIST_DEPTH} levels")
                items(it.children, depth + 1)

        def boxes(bs, depth):
            for b in bs:
                if isinstance(b, SectionBox):
                    if depth > MAX_SECTION_DEPTH:
                        raise ValueError(f"sections may nest at most {MAX_SECTION_DEPTH} levels")
                    boxes(b.content, depth + 1)
                elif isinstance(b, ListBox):
                    items(b.items, 1)

        boxes(self.body, 1)
        return self


def iter_boxes(boxes, depth: int = 1):
    """Yield (box, depth) for every box in document order."""
    for b in boxes:
        yield b, depth
        if isinstance(b, SectionBox):
            yield from iter_boxes(b.content, depth + 1)
