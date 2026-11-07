"""Predefined visual designs (component 2 of 3).

Each design lives in `app/designs/<id>/<version>/`: `base.docx` (styles, page setup, header, footer, fonts),
`design.json` (formatting profile + first-page layout + back-matter settings) and image assets. A version folder
is never edited once published; documents remember the version they were made with.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

from ..schemas.profile import FormattingProfile

ROOT = os.path.dirname(os.path.abspath(__file__))
_VERSION = re.compile(r"^v(\d+)$")
_ID = re.compile(r"^[a-z0-9_]{1,40}$")


class DesignNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Design:
    id: str
    version: str
    name: str
    description: str
    folder: str
    data: dict

    @property
    def base_path(self) -> str:
        return os.path.join(self.folder, self.data["base"])

    def asset(self, name: str) -> str:
        path = os.path.normpath(os.path.join(self.folder, name))
        if os.path.dirname(path) != os.path.normpath(self.folder):      # assets live next to design.json only
            raise DesignNotFound(f"asset {name!r}")
        return path

    @property
    def profile(self) -> FormattingProfile:
        return FormattingProfile.model_validate(self.data["profile"])


def _versions(design_id: str) -> List[str]:
    folder = os.path.join(ROOT, design_id)
    found = [v for v in os.listdir(folder) if _VERSION.match(v) and os.path.isfile(os.path.join(folder, v, "design.json"))] \
        if os.path.isdir(folder) else []
    return sorted(found, key=lambda v: int(_VERSION.match(v).group(1)))


@lru_cache(maxsize=32)
def load(design_id: str, version: Optional[str] = None) -> Design:
    """The given version of a design, or its newest one."""
    if not _ID.match(design_id or ""):
        raise DesignNotFound(design_id)
    versions = _versions(design_id)
    if not versions or (version is not None and version not in versions):
        raise DesignNotFound(f"{design_id} {version or ''}".strip())
    v = version or versions[-1]
    folder = os.path.join(ROOT, design_id, v)
    with open(os.path.join(folder, "design.json"), encoding="utf-8") as f:
        data = json.load(f)
    return Design(id=design_id, version=v, name=data["name"], description=data["description"], folder=folder, data=data)


def available() -> List[Design]:
    out = []
    for name in sorted(os.listdir(ROOT)):
        if _ID.match(name) and _versions(name):
            out.append(load(name))
    return out


def versions(design_id: str) -> List[str]:
    return _versions(design_id)


def summary(d: Design) -> Dict[str, str]:
    return {"id": d.id, "version": d.version, "name": d.name, "description": d.description}
