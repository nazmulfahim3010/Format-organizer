"""Formatting profile = role map + locked table/figure rules + language settings.

The generator opens the *uploaded template* and writes content using the
template's own styles. The profile only says which style plays which role and
how tables/figures/captions are laid out. Anything not set falls back safely.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .content import LANG_PATTERN, check_schema_version

ROLES = (
    ["title", "subtitle", "author", "abstract", "body", "body_first", "quote", "caption", "figure_caption",
     "note", "table_text", "figure", "list_bullet", "list_number"]
    + [f"heading_{i}" for i in range(1, 10)]
)
PROFILE_SCHEMA_VERSION = 1
HEX_COLOR = r"^[0-9A-Fa-f]{6}$"
Origin = Literal["template", "inferred", "default", "user"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# FormattingProfile fields that are bookkeeping, not formatting rules (they get no origin)
NON_RULE_FIELDS = {"schema_version", "name", "roles", "origins", "required_sections"}


def rule_paths(model: BaseModel, prefix: str = "") -> List[str]:
    """Dotted paths of every leaf rule, e.g. 'table.label', 'language.code', 'heading_numbering'."""
    out: List[str] = []
    for name in type(model).model_fields:
        if not prefix and name in NON_RULE_FIELDS:
            continue
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            out += rule_paths(value, f"{prefix}{name}.")
        else:
            out.append(f"{prefix}{name}")
    return out


class TableRule(_Strict):
    label: str = "Table"
    caption_position: Literal["above", "below"] = "above"
    alignment: Literal["left", "center", "right"] = "center"
    width_percent: int = Field(100, ge=10, le=100)
    borders: Literal["all", "horizontal", "none", "template"] = "all"
    template_style_id: Optional[str] = None      # used when borders == "template"
    header_bold: bool = True
    header_shading: Optional[str] = Field("D9D9D9", pattern=HEX_COLOR)   # hex, no '#', or None
    repeat_header: bool = True
    cell_alignment: Literal["left", "center", "right", "auto"] = "auto"
    wide_table_columns: int = Field(7, ge=1)     # >= this many columns -> smaller font
    wide_table_font_pt: float = Field(8.0, gt=0, le=72)
    cell_font_pt: Optional[float] = Field(None, gt=0, le=72)   # None = inherit from style
    note_position: Literal["below"] = "below"
    allow_override: bool = False


class FigureRule(_Strict):
    label: str = "Figure"
    caption_position: Literal["above", "below"] = "below"
    alignment: Literal["left", "center", "right"] = "center"
    max_width_percent: int = Field(100, ge=10, le=100)
    max_height_cm: float = Field(20.0, gt=0, le=100)
    allow_override: bool = False


class LanguageSettings(_Strict):
    code: str = Field("en", pattern=LANG_PATTERN)   # BCP-47, e.g. "bn-BD", "ar-SA"
    rtl: bool = False                # right-to-left paragraphs and tables
    complex_script_font: Optional[str] = None   # e.g. "Kalpurush", "Arial"
    east_asian_font: Optional[str] = None       # e.g. "SimSun"
    set_default_language: bool = True
    native_digits: bool = False      # caption numbers in the language's own digits (e.g. ১, ٢)


class Labels(_Strict):
    abstract: str = "Abstract"
    keywords: str = "Keywords"
    caption_separator: str = ": "
    source: str = "Source"
    note: str = "Note"


class FormattingProfile(_Strict):
    schema_version: int = PROFILE_SCHEMA_VERSION
    name: str = "Untitled profile"
    roles: Dict[str, str] = Field(default_factory=dict)   # role -> style_id
    heading_numbering: Literal["template", "auto", "none"] = "template"
    list_mode: Literal["template", "generated"] = "template"
    # keep the template body before its first heading (banner, boxes, logo) and fill its {{PLACEHOLDERS}}
    keep_template_layout: bool = False
    # generated heading numbers: "tab" = hanging number (default), "space" = "1. Title" inline (journal style)
    heading_number_suffix: Literal["tab", "space"] = "tab"
    table: TableRule = Field(default_factory=TableRule)
    figure: FigureRule = Field(default_factory=FigureRule)
    language: LanguageSettings = Field(default_factory=LanguageSettings)
    labels: Labels = Field(default_factory=Labels)
    required_sections: List[str] = Field(default_factory=list)
    # where each setting came from: template | inferred | default | user
    origins: Dict[str, Origin] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _version(cls, v: int) -> int:
        return check_schema_version(v, PROFILE_SCHEMA_VERSION)

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, v: Dict[str, str]) -> Dict[str, str]:
        unknown = sorted(set(v) - set(ROLES))
        if unknown:
            raise ValueError(f"unknown role(s): {', '.join(unknown)}")
        empty = sorted(k for k, sid in v.items() if not sid.strip())
        if empty:
            raise ValueError(f"role(s) mapped to an empty style id: {', '.join(empty)}")
        return v
