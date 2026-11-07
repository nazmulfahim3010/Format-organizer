"""Tiny inline markup <-> runs.   **bold**  *italic*  ^sup^  ~sub~   (\\ escapes)

Rules (so pasted prose with stray symbols stays literal):
- A marker only formats when it pairs with a later marker of the same kind. Unpaired markers are text.
- An opener must be followed by a non-space, a closer preceded by a non-space ("2 * 3 * 4" stays literal).
- ^sup^ and ~sub~ content may not contain whitespace; write "\\ " for a space inside them.
- Backslash escapes *, ^, ~, \\ and whitespace. A backslash before anything else is literal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

SPECIAL = "*^~\\"
MARKS = ("**", "*", "^", "~")
_ATTR = {"**": "bold", "*": "italic", "^": "sup", "~": "sub"}
_NO_SPACE_INSIDE = ("^", "~")


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    sup: bool = False
    sub: bool = False


@dataclass
class _Tok:
    text: str                 # literal text, or the marker itself
    mark: Optional[str] = None
    escaped: bool = False
    paired: bool = False

    @property
    def is_space(self) -> bool:
        return self.mark is None and not self.escaped and self.text.isspace()


def _tokenize(text: str) -> List[_Tok]:
    toks: List[_Tok] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and (text[i + 1] in SPECIAL or text[i + 1].isspace()):
            toks.append(_Tok(text[i + 1], escaped=True)); i += 2
        elif text.startswith("**", i):
            toks.append(_Tok("**", "**")); i += 2
        elif c in "*^~":
            toks.append(_Tok(c, c)); i += 1
        else:
            toks.append(_Tok(c)); i += 1
    return toks


def _pair(toks: List[_Tok]) -> None:
    """Mark markers that open/close a span; everything else stays literal."""
    open_at: Dict[str, Optional[int]] = {m: None for m in MARKS}
    for idx, t in enumerate(toks):
        if t.is_space:
            for m in _NO_SPACE_INSIDE:
                open_at[m] = None
            continue
        if t.mark is None:
            continue
        can_open = idx + 1 < len(toks) and not toks[idx + 1].is_space
        can_close = idx > 0 and not toks[idx - 1].is_space
        start = open_at[t.mark]
        if start is not None and can_close:
            toks[start].paired = t.paired = True
            open_at[t.mark] = None
        elif can_open:
            open_at[t.mark] = idx
        # else: literal


def parse_inline(text: str) -> List[Run]:
    toks = _tokenize(text)
    _pair(toks)
    runs: List[Run] = []
    buf: List[str] = []
    state = {"bold": False, "italic": False, "sup": False, "sub": False}

    def flush() -> None:
        if buf:
            runs.append(Run("".join(buf), **state))
            buf.clear()

    for t in toks:
        if t.mark and t.paired:
            flush()
            attr = _ATTR[t.mark]
            state[attr] = not state[attr]
        else:
            buf.append(t.text)
    flush()
    return runs or [Run("")]


def escape(text: str) -> str:
    return "".join("\\" + c if c in SPECIAL else c for c in text)


def _key(r: Run) -> Tuple[bool, bool, bool, bool]:
    return (r.bold, r.italic, r.sup, r.sub)


def _normalize(parts: List[Run]) -> List[Run]:
    """Move styling off leading/trailing whitespace, drop empties, merge equal neighbours."""
    split: List[Run] = []
    for r in parts:
        if not r.text:
            continue
        core = r.text.strip()
        if not core or not any(_key(r)):
            split.append(Run(r.text))
            continue
        lead = r.text[: len(r.text) - len(r.text.lstrip())]
        trail = r.text[len(r.text.rstrip()):]
        split += [Run(lead), Run(core, *_key(r)), Run(trail)]
    out: List[Run] = []
    for r in split:
        if not r.text:
            continue
        if out and _key(out[-1]) == _key(r):
            out[-1] = Run(out[-1].text + r.text, *_key(r))
        else:
            out.append(r)
    return out


def runs_to_markup(parts: List[Run]) -> str:
    """Inverse of parse_inline. Emits one marker per attribute change, so output always re-parses."""
    out: List[str] = []
    cur = (False, False, False, False)
    for r in _normalize(parts):
        new = _key(r)
        # close what ends before opening what starts: "NO~3~^−^" reads better than "NO~3^~−^"
        out.append("".join(m for m, a, b in zip(MARKS, cur, new) if a and not b))
        out.append("".join(m for m, a, b in zip(MARKS, cur, new) if b and not a))
        tight = r.sup or r.sub
        out.append("".join("\\" + c if c in SPECIAL or (tight and c.isspace()) else c for c in r.text))
        cur = new
    out.append("".join(m for m, a in zip(MARKS, cur) if a))
    return "".join(out)


def plain(text: str) -> str:
    return "".join(r.text for r in parse_inline(text))
