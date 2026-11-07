"""{{PLACEHOLDER}} text in templates: find and fill, also when Word split one across several runs.

Values are plain text. The text keeps the formatting of the run where the placeholder starts.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, Iterable, List, Optional, Set

from docx.oxml.ns import qn

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_]{1,40})\s*\}\}")
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _own_texts(p) -> List:
    """w:t elements of this paragraph only (not of paragraphs nested in its text boxes)."""
    out = []
    for t in p.iter(qn("w:t")):
        anc = t.getparent()
        while anc is not None and anc.tag != qn("w:p"):
            anc = anc.getparent()
        if anc is p:
            out.append(t)
    return out


def names_in(elements: Iterable) -> List[str]:
    found: List[str] = []
    for el in elements:
        for p in ([el] if el.tag == qn("w:p") else []) + list(el.iter(qn("w:p"))):
            for m in PLACEHOLDER.finditer("".join(t.text or "" for t in _own_texts(p))):
                if m.group(1) not in found:
                    found.append(m.group(1))
    return found


def fill(elements: Iterable, values: Dict[str, str], on_value: Optional[Callable] = None) -> Set[str]:
    """Replace {{NAME}} with values[NAME] in every paragraph under `elements`. Returns names left unfilled.
    `on_value(run_element, value)` is called for each filled run (e.g. to add complex-script properties)."""
    unfilled: Set[str] = set()
    # the elements themselves, not id(): lxml proxies are recreated, and a freed proxy's id gets reused,
    # which silently skipped header paragraphs
    seen: set = set()
    for el in elements:
        for p in ([el] if el.tag == qn("w:p") else []) + list(el.iter(qn("w:p"))):
            if p in seen:
                continue
            seen.add(p)
            ts = _own_texts(p)
            text = "".join(t.text or "" for t in ts)
            matches = list(PLACEHOLDER.finditer(text))
            if not matches:
                continue
            # char offset -> (index of w:t, offset inside it)
            spans, pos = [], 0
            for t in ts:
                n = len(t.text or "")
                spans.append((pos, pos + n))
                pos += n

            def locate(offset: int, end: bool):
                for i, (a, b) in enumerate(spans):
                    if a <= offset < b or (end and a < offset <= b):
                        return i, offset - a
                return len(ts) - 1, len(ts[-1].text or "")

            for m in reversed(matches):                 # right to left keeps earlier offsets valid
                name = m.group(1)
                if name not in values:
                    unfilled.add(name)
                    continue
                value = values[name].replace("\r", "").replace("\n", " ")
                (i, a), (j, b) = locate(m.start(), False), locate(m.end(), True)
                first, last = ts[i], ts[j]
                if i == j:
                    first.text = (first.text or "")[:a] + value + (first.text or "")[b:]
                else:
                    first.text = (first.text or "")[:a] + value
                    for k in range(i + 1, j):
                        ts[k].text = ""
                    last.text = (last.text or "")[b:]
                for t in (first, last):
                    t.set(XML_SPACE, "preserve")
                if on_value is not None:
                    on_value(first.getparent(), value)
    return unfilled
