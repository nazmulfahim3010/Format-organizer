"""Paste normalizer (deterministic, no AI).

Turns pasted HTML (Word, Google Docs, web), Markdown (AI chats) or plain text
into SmartDoc boxes. All source formatting (fonts, colours, sizes) is dropped;
only structure survives: headings, emphasis, lists, tables, images.

Typed numbering ("1.1 Motivation", "১.১ ভূমিকা") becomes real nesting, and typed
captions ("Table 2: Results", "চিত্র ১: ...") are attached to the nearest
table/figure with the label removed (Word regenerates the number).
"""
from __future__ import annotations

import base64
import csv
import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from lxml import etree, html as lhtml

from ..core.inline import Run, escape, parse_inline, runs_to_markup
from ..schemas.content import (Box, FigureBox, ListBox, ListItem, ParagraphBox,
                               SectionBox, TableBox)

# --------------------------------------------------------------------------- constants
DIGIT_MAP = {}
for base in (0x0660, 0x06F0, 0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0B66, 0x0BE6, 0x0C66, 0x0CE6, 0x0D66, 0x0E50):
    for i in range(10):
        DIGIT_MAP[chr(base + i)] = str(i)
DIGIT_TABLE = str.maketrans(DIGIT_MAP)

TABLE_LABELS = (r"table|tab\.?|tabelle|tableau|tabla|tabella|таблица|табл\.?|表|表格|표|جدول|"
                r"সারণি|সারণী|ছক|টেবিল|তালিকা")
FIG_LABELS = (r"figure|fig\.?|abbildung|abb\.?|figura|рисунок|рис\.?|图|圖|図|그림|شكل|الشكل|"
              r"চিত্র|ছবি|ফিগার")
CAPTION_SEP = r"([:.\-–—|)]?)"
CAPTION_NUM = r"[\(\[]?(\d+(?:[.\-]\d+)*)[\)\]]?"
TABLE_CAP = re.compile(rf"^\s*(?:{TABLE_LABELS})\s*{CAPTION_NUM}\s*{CAPTION_SEP}\s*(.*)$", re.I | re.S)
FIG_CAP = re.compile(rf"^\s*(?:{FIG_LABELS})\s*{CAPTION_NUM}\s*{CAPTION_SEP}\s*(.*)$", re.I | re.S)
SOURCE_LINE = re.compile(r"^\s*(source|sources|quelle|fuente|источник|সূত্র|উৎস|المصدر|来源)\s*[:：]\s*(.+)$", re.I | re.S)
NOTE_LINE = re.compile(r"^\s*(note|notes|anmerkung|nota|примечание|টীকা|ملاحظة|注)\s*[:：]\s*(.+)$", re.I | re.S)
NUM_DEC = re.compile(r"^\s*(\d+(?:\.\d+){0,8})[\.\)]?\s+(\S.*)$", re.S)
NUM_ALPHA = re.compile(r"^\s*(?:[IVXLC]{1,6}|[A-Z])[\.\)]\s+(\S.*)$", re.S)
CHAPTER = re.compile(r"^\s*(?:chapter|section|part|অধ্যায়|পর্ব)\s+(\d+)\s*[:.\-–—]?\s*(.*)$", re.I | re.S)
BULLET = re.compile(r"^(\s*)[•\-\*–·▪●○◦■□]\s+(\S.*)$")
ORDERED = re.compile(r"^(\s*)\(?(\d+|[a-zA-Z])[.)]\s+(\S.*)$")
SENTENCE_END = re.compile(r"[.!?।؟。]\s*$")
# "a) ...", "(b) ...", "iv. ...", "B. ...", "ক) ..." list items in plain text
ALPHA_ITEM = re.compile(r"^(\s*)\(?([a-zA-Z]|[ivxlcdm]{1,6}|[IVXLCDM]{1,6}|[কখগঘঙচছজঝঞ])[.)]\s+(\S.*)$")
BANGLA_LETTERS = "কখগঘঙচছজঝঞ"
ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
BLOCK_TAGS = {"p", "div", "section", "article", "header", "footer", "main", "aside", "nav", "blockquote",
              "pre", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "figure", "hr", "dl", "form",
              "li", "tr", "tbody", "thead", "tfoot"}
SKIP_TAGS = {"script", "style", "meta", "link", "head", "title", "noscript", "svg", "button", "iframe"}
CELL_TAGS = {"td", "th"}


def norm_digits(s: str) -> str:
    return s.translate(DIGIT_TABLE)


def _roman_value(s: str) -> Optional[int]:
    s = s.lower()
    if not s or any(c not in ROMAN for c in s):
        return None
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = ROMAN[a]
        total += -v if b in ROMAN and ROMAN[b] > v else v
    return total


def _to_roman(n: int, upper: bool) -> str:
    out = ""
    for v, r in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"),
                 (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out += r
            n -= v
    return out.upper() if upper else out


def _next_markers(m: str) -> set:
    """Markers that may follow `m` in a lettered / roman / Bangla-lettered list."""
    out = set()
    if len(m) == 1 and m.isascii() and m.isalpha() and m.lower() != "z":
        out.add(chr(ord(m) + 1))
    if m in BANGLA_LETTERS[:-1]:
        out.add(BANGLA_LETTERS[BANGLA_LETTERS.index(m) + 1])
    v = _roman_value(m)
    if v:
        out.add(_to_roman(v + 1, m.isupper()))
    return out


def _caption_like(plain: str) -> bool:
    """A typed caption with a label, a number and a separator ("Table 1: ...", "চিত্র ২ - ...")."""
    d = norm_digits(plain)
    return any((m := rx.match(d)) and m.group(2) for rx in (TABLE_CAP, FIG_CAP))


def _special_line(line: str) -> bool:
    """Lines that stand alone in plain text even when not separated by a blank line."""
    return bool(SOURCE_LINE.match(line) or NOTE_LINE.match(line) or _caption_like(line))


def _unbold(markup: str) -> str:
    runs = parse_inline(markup)
    for r in runs:
        r.bold = False
    return runs_to_markup(runs)


@dataclass
class PendingImage:
    index: int
    data: bytes
    mime: str


@dataclass
class NormalizeResult:
    boxes: List[Box] = field(default_factory=list)
    title: str = ""
    warnings: List[Dict[str, str]] = field(default_factory=list)
    images: List[PendingImage] = field(default_factory=list)
    source_format: str = "text"


# --------------------------------------------------------------------------- run helpers
def _merge(runs: List[Run]) -> List[Run]:
    out: List[Run] = []
    for r in runs:
        if not r.text:
            continue
        if out and (out[-1].bold, out[-1].italic, out[-1].sup, out[-1].sub) == (r.bold, r.italic, r.sup, r.sub):
            out[-1] = Run(out[-1].text + r.text, r.bold, r.italic, r.sup, r.sub)
        else:
            out.append(r)
    return out


def _tidy(runs: List[Run], keep_newlines: bool = False) -> List[Run]:
    """Collapse whitespace, trim the ends, drop empty runs."""
    runs = _merge(runs)
    pat = r"[ \t\r\f\v ]+" if keep_newlines else r"[ \t\r\n\f\v ]+"
    for r in runs:
        r.text = re.sub(pat, " ", r.text)
        if keep_newlines:
            r.text = re.sub(r" ?\n ?", "\n", r.text)
    runs = _merge(runs)
    if runs:
        runs[0].text = runs[0].text.lstrip(" \n")
        runs[-1].text = runs[-1].text.rstrip(" \n")
    return [r for r in _merge(runs) if r.text]


def _markup(runs: List[Run]) -> str:
    return runs_to_markup(runs)


def _plain(runs: List[Run]) -> str:
    return "".join(r.text for r in runs)


def _is_all_bold(runs: List[Run]) -> bool:
    return bool(runs) and all(r.bold for r in runs if r.text.strip())


# --------------------------------------------------------------------------- HTML
def _style(el) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in (el.get("style") or "").lower().split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _weight(st: Dict[str, str]) -> Optional[bool]:
    w = st.get("font-weight")
    if w is None:
        return None
    if w in ("bold", "bolder"):
        return True
    if w in ("normal", "lighter"):
        return False
    return w.isdigit() and int(w) >= 600


class _Html:
    def __init__(self, res: NormalizeResult):
        self.res = res
        self.items: List[dict] = []
        self.pending_list: List[dict] = []   # fake (Word) list paragraphs in progress

    # ---- inline ----------------------------------------------------------
    def inline(self, el, runs: List[Run], b=False, i=False, sup=False, sub=False, stop_at_lists=True,
               on_image=None) -> None:
        tag = el.tag if isinstance(el.tag, str) else None
        if tag is None:  # comment / PI
            if el.tail:
                runs.append(Run(el.tail, b, i, sup, sub))
            return
        tag = tag.lower().split(":")[-1]
        if tag in SKIP_TAGS:
            if el.tail:
                runs.append(Run(el.tail, b, i, sup, sub))
            return
        st = _style(el)
        if "mso-list" in st and "ignore" in st["mso-list"]:
            if el.tail:
                runs.append(Run(el.tail, b, i, sup, sub))
            return
        nb, ni, nsup, nsub = b, i, sup, sub
        w = _weight(st)
        if tag in ("b", "strong"):
            nb = False if w is False else True
        elif w is not None:
            nb = w
        if tag in ("i", "em", "cite", "var"):
            ni = st.get("font-style") != "normal"
        elif st.get("font-style") == "italic":
            ni = True
        elif st.get("font-style") == "normal":
            ni = False
        if tag == "sup" or st.get("vertical-align") in ("super", "sup"):
            nsup = True
        if tag == "sub" or st.get("vertical-align") == "sub":
            nsub = True
        if tag == "br":
            runs.append(Run("\n", nb, ni, nsup, nsub))
        elif tag == "img" and on_image is not None:
            on_image(el)
        else:
            if el.text:
                runs.append(Run(el.text, nb, ni, nsup, nsub))
            for ch in el:
                ctag = ch.tag.lower().split(":")[-1] if isinstance(ch.tag, str) else ""
                if stop_at_lists and ctag in ("ul", "ol"):
                    if ch.tail:
                        runs.append(Run(ch.tail, nb, ni, nsup, nsub))
                    continue
                self.inline(ch, runs, nb, ni, nsup, nsub, stop_at_lists, on_image)
        if el.tail:
            runs.append(Run(el.tail, b, i, sup, sub))

    def text_of(self, el) -> List[Run]:
        runs: List[Run] = []
        if el.text:
            runs.append(Run(el.text))
        st = _style(el)
        w = _weight(st)
        base_b = bool(w) if w is not None else False
        runs = [Run(r.text, base_b) for r in runs]
        for ch in el:
            self.inline(ch, runs, base_b)
        return _tidy(runs, keep_newlines=True)

    # ---- images ----------------------------------------------------------
    def image(self, el) -> None:
        src = el.get("src") or ""
        m = re.match(r"data:(image/[\w.+-]+);base64,(.*)$", src, re.S)
        if m:
            try:
                data = base64.b64decode(m.group(2))
                idx = len(self.res.images)
                self.res.images.append(PendingImage(idx, data, m.group(1)))
                self.items.append({"kind": "figure", "src": f"pending:{idx}", "caption": "", "alt": el.get("alt") or ""})
                return
            except Exception:
                pass
        self.res.warnings.append({"code": "FIGURE_NEEDS_UPLOAD",
                                  "message": "An image could not be copied from the clipboard (it is a link or a local file). Upload it manually."})
        self.items.append({"kind": "figure", "src": None, "caption": "", "alt": el.get("alt") or ""})

    # ---- blocks ----------------------------------------------------------
    def flush_pending_list(self) -> None:
        if self.pending_list:
            self.items.append({"kind": "list", "ordered": self.pending_list[0]["ordered"],
                               "entries": [(e["level"], e["text"]) for e in self.pending_list]})
            self.pending_list = []

    def emit_para(self, runs: List[Run], css_class: str = "") -> None:
        runs = _tidy(runs, keep_newlines=True)
        if not runs:
            return
        txt = _plain(runs)
        if not txt.strip():
            return
        kind = "title" if "msotitle" in css_class.lower() or css_class.lower() == "title" else "para"
        self.items.append({"kind": kind, "text": _markup(runs), "plain": txt, "all_bold": _is_all_bold(runs)})

    def walk(self, container) -> None:
        buf: List[Run] = []

        def flush():
            if buf:
                self.emit_para(list(buf))
                buf.clear()

        if container.text:
            buf.append(Run(container.text))
        for ch in container:
            tag = ch.tag.lower().split(":")[-1] if isinstance(ch.tag, str) else None
            if tag is None:
                if ch.tail:
                    buf.append(Run(ch.tail))
                continue
            if tag in SKIP_TAGS:
                if ch.tail:
                    buf.append(Run(ch.tail))
                continue
            st = _style(ch)
            is_fake_list = "mso-list" in st and st["mso-list"] not in ("none",) and tag == "p"
            if tag not in BLOCK_TAGS:
                if tag == "img":
                    flush(); self.flush_pending_list(); self.image(ch)
                    if ch.tail:
                        buf.append(Run(ch.tail))
                    continue
                # a wrapper span/b/font that itself contains blocks (Google Docs: <b id=docs-internal-guid>)
                if any(isinstance(c.tag, str) and c.tag.lower().split(":")[-1] in BLOCK_TAGS for c in ch):
                    flush(); self.walk(ch)
                    if ch.tail:
                        buf.append(Run(ch.tail))
                    continue
                self.inline(ch, buf)
                continue
            # block-level
            if not is_fake_list:
                self.flush_pending_list()
            flush()
            self.block(ch, is_fake_list, st)
            if ch.tail and ch.tail.strip():
                buf.append(Run(ch.tail))
        flush()
        self.flush_pending_list()

    def block(self, el, is_fake_list: bool, st: Dict[str, str]) -> None:
        tag = el.tag.lower().split(":")[-1]
        cls = el.get("class") or ""
        if re.fullmatch(r"h[1-6]", tag):
            runs = self.text_of(el)
            for r in runs:
                r.bold = r.italic = False
            runs = _merge(runs)
            if runs:
                self.items.append({"kind": "heading", "level": int(tag[1]), "text": _markup(runs), "plain": _plain(runs)})
        elif tag in ("ul", "ol"):
            self.html_list(el, 0)
        elif tag == "table":
            self.html_table(el)
        elif tag == "figure":
            before = len(self.items)
            for ch in el:
                t = ch.tag.lower() if isinstance(ch.tag, str) else ""
                if t == "figcaption":
                    cap = _plain(self.text_of(ch))
                    figs = [it for it in self.items[before:] if it["kind"] == "figure"]
                    if figs:
                        figs[-1]["caption"] = cap
                elif t == "img":
                    self.image(ch)
                else:
                    self.walk(ch)
        elif tag == "hr":
            return
        elif is_fake_list:
            self.word_list_item(el, st)
        elif tag == "pre":
            runs = [Run(el.text_content())]
            runs = _tidy(runs, keep_newlines=True)
            if runs:
                self.items.append({"kind": "para", "text": _markup(runs), "plain": _plain(runs), "all_bold": False})
        elif tag in ("li", "tr", "tbody", "thead", "tfoot"):
            self.walk(el)
        else:
            # p, div, section, blockquote ... : paragraphs and nested blocks
            has_block = any(isinstance(c.tag, str) and c.tag.lower().split(":")[-1] in BLOCK_TAGS | {"img"} for c in el)
            has_img = any(True for _ in el.iter("img"))
            if has_block and tag != "p":
                self.walk(el)
            elif has_img:
                runs: List[Run] = []
                if el.text:
                    runs.append(Run(el.text))
                for c in el:
                    ctag = c.tag.lower() if isinstance(c.tag, str) else ""
                    if ctag == "img":
                        self.emit_para(runs); runs = []; self.image(c)
                        if c.tail:
                            runs.append(Run(c.tail))
                    else:
                        self.inline(c, runs, on_image=lambda im: (self.emit_para(list(runs)), runs.clear(), self.image(im)))
                self.emit_para(runs)
            else:
                self.emit_para(self.text_of(el), cls)

    # ---- lists -----------------------------------------------------------
    def html_list(self, el, depth: int, ordered: Optional[bool] = None) -> None:
        ordered = (el.tag.lower() == "ol") if ordered is None else ordered
        entries: List[Tuple[int, str]] = []

        def collect(lst, d):
            for li in lst:
                if isinstance(li.tag, str) and li.tag.lower() in ("ul", "ol"):
                    collect(li, d + 1)          # Google Docs: <ul><li/><ul><li/></ul></ul>
                    continue
                if not isinstance(li.tag, str) or li.tag.lower() != "li":
                    continue
                level = d
                al = li.get("aria-level")
                if al and al.isdigit():
                    level = max(0, int(al) - 1)
                runs: List[Run] = []
                if li.text:
                    runs.append(Run(li.text))
                for c in li:
                    ctag = c.tag.lower() if isinstance(c.tag, str) else ""
                    if ctag in ("ul", "ol"):
                        continue
                    self.inline(c, runs)
                text = _markup(_tidy(runs, keep_newlines=True))
                if text.strip():
                    entries.append((level, text))
                for c in li:
                    if isinstance(c.tag, str) and c.tag.lower() in ("ul", "ol"):
                        collect(c, d + 1)

        collect(el, depth)
        if entries:
            last = self.items[-1] if self.items else None
            if last and last["kind"] == "list" and last["ordered"] == ordered and last.get("from_html"):
                last["entries"].extend(entries)       # Google Docs emits one <ul> per level change
            else:
                self.items.append({"kind": "list", "ordered": ordered, "entries": entries, "from_html": True})

    def word_list_item(self, el, st: Dict[str, str]) -> None:
        m = re.search(r"level(\d+)", st.get("mso-list", ""))
        level = int(m.group(1)) - 1 if m else 0
        marker = ""
        for span in el.iter("span"):
            if "ignore" in _style(span).get("mso-list", ""):
                marker = span.text_content().strip()
                break
        ordered = bool(re.match(r"^[\(\[]?[0-9a-zA-Zivxl০-৯]+[.)\]]", marker)) and marker not in ("o", "·", "§")
        runs = self.text_of(el)
        text = _markup(runs)
        if text.strip():
            self.pending_list.append({"ordered": ordered, "level": level, "text": text})

    # ---- tables ----------------------------------------------------------
    def html_table(self, el) -> None:
        rows_el = [tr for tr in el.iter("tr") if self._owner_table(tr) is el]
        grid: List[List[str]] = []
        carry: Dict[int, Tuple[int, str]] = {}   # col -> (remaining rows, "")
        merged = False
        header_rows = 0
        thead_rows = {tr for tr in el.xpath("./thead/tr")}
        for ri, tr in enumerate(rows_el):
            row: List[str] = []
            ci = 0
            cells = [c for c in tr if isinstance(c.tag, str) and c.tag.lower() in CELL_TAGS]

            def fill_carry():
                nonlocal ci
                while ci in carry and carry[ci][0] > 0:
                    row.append("")
                    rem, v = carry[ci]
                    carry[ci] = (rem - 1, v)
                    ci += 1

            for c in cells:
                fill_carry()
                runs: List[Run] = []
                if c.text:
                    runs.append(Run(c.text))
                for ch in c:
                    self.inline(ch, runs, stop_at_lists=False)
                text = _markup(_tidy(runs, keep_newlines=True))
                cs = int(c.get("colspan") or 1) if (c.get("colspan") or "1").isdigit() else 1
                rs = int(c.get("rowspan") or 1) if (c.get("rowspan") or "1").isdigit() else 1
                row.append(text); ci += 1
                for _ in range(cs - 1):
                    row.append(""); ci += 1; merged = True
                if rs > 1:
                    merged = True
                    for k in range(cs):
                        carry[ci - cs + k] = (rs - 1, "")
            fill_carry()
            if row and any(x.strip() for x in row):
                grid.append(row)
                if tr in thead_rows or all(isinstance(c.tag, str) and c.tag.lower() == "th" for c in cells) and cells:
                    if header_rows == len(grid) - 1:
                        header_rows += 1
        if not grid:
            return
        width = max(len(r) for r in grid)
        grid = [r + [""] * (width - len(r)) for r in grid]
        cap_el = el.find("caption")
        caption = _markup(self.text_of(cap_el)) if cap_el is not None else ""
        if merged:
            self.res.warnings.append({"code": "TABLE_MERGED_CELLS",
                                      "message": "A table had merged cells; they were split into separate cells."})
        self.items.append({"kind": "table", "data": grid, "header_rows": header_rows or 1, "caption": caption})

    @staticmethod
    def _owner_table(tr):
        p = tr.getparent()
        while p is not None and p.tag != "table":
            p = p.getparent()
        return p


def _collapse_source_newlines(root) -> None:
    """In HTML a newline in the source is just a space; only <br> breaks a line. <pre> keeps its own."""
    def in_pre(el) -> bool:
        while el is not None:
            if isinstance(el.tag, str) and el.tag.lower() in ("pre", "textarea"):
                return True
            el = el.getparent()
        return False
    for el in root.iter():
        if el.text and "\n" in el.text and not in_pre(el):
            el.text = re.sub(r"[\r\n]+", " ", el.text)
        if el.tail and "\n" in el.tail and not in_pre(el.getparent()):
            el.tail = re.sub(r"[\r\n]+", " ", el.tail)


def parse_html(src: str, res: NormalizeResult) -> List[dict]:
    src = re.sub(r"<!--\s*(Start|End)Fragment\s*-->", "", src)
    try:
        root = lhtml.fromstring(src)
    except Exception:
        root = lhtml.fromstring(f"<div>{src}</div>")
    body = root.find("body") if root.tag != "body" else root
    if body is None:
        body = root
    _collapse_source_newlines(root)
    h = _Html(res)
    # a bare fragment like "<b>text</b>" parses to the element itself
    if body is root and root.tag.lower() not in ("body", "div", "html") and isinstance(root.tag, str):
        wrapper = etree.Element("div"); wrapper.append(root); body = wrapper
    h.walk(body)
    return h.items


# --------------------------------------------------------------------------- Markdown
def md_inline(text: str) -> List[Run]:
    runs: List[Run] = []
    i, n = 0, len(text)
    bold = italic = False
    buf: List[str] = []

    def flush():
        if buf:
            runs.append(Run("".join(buf), bold, italic))
            buf.clear()

    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            buf.append(text[i + 1]); i += 2
        elif text.startswith("**", i) or text.startswith("__", i):
            flush(); bold = not bold; i += 2
        elif c == "*" and i + 1 < n and text[i + 1] != " ":
            flush(); italic = not italic; i += 1
        elif c == "*" and italic:
            flush(); italic = False; i += 1
        elif c == "_" and (i == 0 or not text[i - 1].isalnum()) and i + 1 < n and text[i + 1] != " ":
            flush(); italic = True; i += 1
        elif c == "_" and italic and (i + 1 >= n or not text[i + 1].isalnum()):
            flush(); italic = False; i += 1
        elif c == "`":
            j = text.find("`", i + 1)
            if j > 0:
                buf.append(text[i + 1:j]); i = j + 1
            else:
                buf.append(c); i += 1
        elif c == "[":
            m = re.match(r"\[([^\]]*)\]\(([^)]*)\)", text[i:])
            if m:
                buf.append(m.group(1)); i += m.end()
            else:
                buf.append(c); i += 1
        elif text.startswith("~~", i):
            i += 2
        else:
            buf.append(c); i += 1
    flush()
    return _tidy(runs)


TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _split_row(line: str) -> List[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def parse_markdown(src: str, res: NormalizeResult) -> List[dict]:
    items: List[dict] = []
    lines = src.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    para: List[str] = []
    list_entries: List[Tuple[int, str]] = []
    list_ordered = False
    indent_stack: List[int] = []
    i = 0

    def flush_para():
        if para:
            text = " ".join(s.strip() for s in para)
            runs = md_inline(text)
            if runs:
                items.append({"kind": "para", "text": _markup(runs), "plain": _plain(runs), "all_bold": _is_all_bold(runs)})
            para.clear()

    def flush_list():
        nonlocal list_entries, indent_stack
        if list_entries:
            items.append({"kind": "list", "ordered": list_ordered, "entries": list_entries})
        list_entries, indent_stack = [], []

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush_para(); flush_list(); i += 1; continue
        if line.strip().startswith("```"):
            flush_para(); flush_list()
            j = i + 1; code = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                code.append(lines[j]); j += 1
            runs = _tidy([Run("\n".join(code))], keep_newlines=True)
            if runs:
                items.append({"kind": "para", "text": _markup(runs), "plain": _plain(runs), "all_bold": False})
            i = j + 1; continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m:
            flush_para(); flush_list()
            runs = md_inline(m.group(2))
            for r in runs:
                r.bold = r.italic = False
            runs = _merge(runs)
            items.append({"kind": "heading", "level": len(m.group(1)), "text": _markup(runs), "plain": _plain(runs)})
            i += 1; continue
        if "|" in line and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
            flush_para(); flush_list()
            rows = [[_markup(md_inline(c)) for c in _split_row(line)]]
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                rows.append([_markup(md_inline(c)) for c in _split_row(lines[j])]); j += 1
            w = max(len(r) for r in rows)
            items.append({"kind": "table", "data": [r + [""] * (w - len(r)) for r in rows], "header_rows": 1, "caption": ""})
            i = j; continue
        m = re.match(r"^\s*!\[(.*?)\]\((.*?)\)\s*$", line)
        if m:
            flush_para(); flush_list()
            alt, url = m.group(1), m.group(2).split(" ")[0]
            dm = re.match(r"data:(image/[\w.+-]+);base64,(.*)$", url, re.S)
            if dm:
                try:
                    idx = len(res.images)
                    res.images.append(PendingImage(idx, base64.b64decode(dm.group(2)), dm.group(1)))
                    items.append({"kind": "figure", "src": f"pending:{idx}", "caption": "", "alt": alt})
                    i += 1; continue
                except Exception:
                    pass
            res.warnings.append({"code": "FIGURE_NEEDS_UPLOAD", "message": f"Image '{alt or url[:40]}' is a link; upload the file manually."})
            items.append({"kind": "figure", "src": None, "caption": "", "alt": alt})
            i += 1; continue
        if re.match(r"^\s*([-*_])(\s*\1){2,}\s*$", line):
            flush_para(); flush_list(); i += 1; continue
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            flush_para()
            ordered = m.group(2)[0].isdigit()
            if list_entries and ordered != list_ordered and not m.group(1):
                flush_list()
            list_ordered = ordered if not list_entries else list_ordered
            ind = len(m.group(1).replace("\t", "    "))
            while indent_stack and ind < indent_stack[-1]:
                indent_stack.pop()
            if not indent_stack or ind > indent_stack[-1]:
                indent_stack.append(ind)
            list_entries.append((len(indent_stack) - 1, _markup(md_inline(m.group(3)))))
            i += 1; continue
        if line.startswith(">"):
            flush_para(); flush_list()
            para.append(line.lstrip("> ")); i += 1; continue
        if list_entries and line.startswith((" ", "\t")):   # lazy continuation of a list item
            lvl, txt = list_entries[-1]
            list_entries[-1] = (lvl, txt + " " + _markup(md_inline(line.strip())))
            i += 1; continue
        flush_list()
        para.append(line); i += 1
    flush_para(); flush_list()
    return items


# --------------------------------------------------------------------------- plain text
def _tab_block(lines: List[str], start: int) -> Tuple[List[List[str]], int]:
    """Read tab-separated rows from `start`, honouring Excel quoting ("a\nb", ""quoted""). Returns
    (rows, index after the block)."""
    j, chunk, quotes = start, [], 0
    while j < len(lines):
        line = lines[j]
        if quotes % 2 == 0 and (not line.strip() or "\t" not in line):
            break
        chunk.append(line)
        quotes += line.count('"')
        j += 1
    rows = [[c.strip() for c in row] for row in csv.reader(io.StringIO("\n".join(chunk)), delimiter="\t")]
    return [r for r in rows if any(r)], j


def parse_text(src: str, res: NormalizeResult) -> List[dict]:
    items: List[dict] = []
    lines = src.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    para: List[str] = []
    entries: List[Tuple[int, str]] = []
    ordered = False
    alpha_next: set = set()          # markers that would continue the current lettered list

    def flush_para():
        if para:
            text = re.sub(r"\s+", " ", " ".join(para)).strip()
            para.clear()
            if text:
                items.append({"kind": "para", "text": _markup([Run(text)]), "plain": text, "all_bold": False})

    def flush_list():
        nonlocal entries, alpha_next
        if entries:
            items.append({"kind": "list", "ordered": ordered, "entries": entries})
        entries, alpha_next = [], set()

    def add_item(is_ordered: bool, indent: str, text: str) -> None:
        nonlocal ordered
        flush_para()
        if entries and ordered != is_ordered:
            flush_list()
        ordered = is_ordered
        entries.append((min(len(indent.replace("\t", "    ")) // 2, 8), _markup([Run(text.strip())])))

    idx = 0
    while idx < len(lines):
        line = lines[idx].rstrip("\r")
        nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
        if not line.strip():
            flush_para(); flush_list(); idx += 1; continue
        if "\t" in line.strip("\n") and line.strip():
            rows, end = _tab_block(lines, idx)
            if len(rows) >= 2:
                flush_para(); flush_list()
                w = max(len(r) for r in rows)
                items.append({"kind": "table", "data": [[_markup([Run(c)]) for c in r] + [""] * (w - len(r)) for r in rows],
                              "header_rows": 1, "caption": ""})
                res.warnings.append({"code": "TABLE_FROM_TEXT", "message": "Tab-separated text was converted to a table. Check the header row."})
                idx = end; continue
            line = re.sub(r"\t+", " ", line)
        mb = BULLET.match(line)
        if mb:
            add_item(False, mb.group(1), mb.group(2)); idx += 1; continue
        mo = ORDERED.match(line)
        prev_ordered = bool(entries) and ordered and not alpha_next
        if mo and mo.group(2).isdigit() and not re.match(r"^\s*\d+\.\d", line):
            n = int(mo.group(2))
            nm = ORDERED.match(nxt)
            if prev_ordered or (nm and nm.group(2).isdigit() and int(nm.group(2)) == n + 1):
                add_item(True, mo.group(1), mo.group(3)); idx += 1; continue
        ma = ALPHA_ITEM.match(line)
        if ma:
            marker = ma.group(2)
            na = ALPHA_ITEM.match(nxt)
            continues = marker in alpha_next or (entries and ordered and ma.group(1))   # nested under a numbered item
            starts = na is not None and na.group(2) in _next_markers(marker)
            if continues or starts:
                if not continues:
                    flush_list()
                add_item(True, ma.group(1), ma.group(3))
                alpha_next = _next_markers(marker)
                idx += 1; continue
        flush_list()
        if _special_line(line):                 # captions, Source:, Note: stand alone
            flush_para(); para.append(line); flush_para(); idx += 1; continue
        d = norm_digits(line)
        md = NUM_DEC.match(d)
        words = len(line.split())
        if md and words <= 15 and not SENTENCE_END.search(line.rstrip()):
            depth = md.group(1).count(".") + 1
            flush_para()
            title = line[len(d) - len(md.group(2)):]   # same length as d: digits are mapped 1:1
            items.append({"kind": "heading", "level": depth, "text": _markup([Run(title.strip())]), "plain": title.strip(), "typed": True})
            idx += 1; continue
        mc = CHAPTER.match(d)
        if mc and words <= 15 and not SENTENCE_END.search(line.rstrip()):
            flush_para()
            title = line[len(d) - len(mc.group(2)):] if mc.group(2) else line.strip()
            items.append({"kind": "heading", "level": 1, "text": _markup([Run(title.strip())]), "plain": title.strip(), "typed": True})
            idx += 1; continue
        para.append(line)
        idx += 1
    flush_para(); flush_list()
    return items


# --------------------------------------------------------------------------- post-processing
def _strip_heading_number(plain: str, markup: str) -> Tuple[str, Optional[int]]:
    """Remove typed numbering from a heading. Returns (markup, depth or None)."""
    d = norm_digits(markup.lstrip())
    m = NUM_DEC.match(d)
    if m:
        cut = len(d) - len(m.group(2))
        return markup.lstrip()[cut:].strip(), m.group(1).count(".") + 1
    m = CHAPTER.match(d)
    if m and m.group(2):
        return markup.lstrip()[len(d) - len(m.group(2)):].strip(), 1
    m = NUM_ALPHA.match(markup)
    if m:
        return m.group(1).strip(), None
    return markup, None


def _is_caption(item: dict, kind: str) -> Optional[Tuple[str, str]]:
    """Return (caption markup without the typed label/number, 'caption') or None."""
    if item["kind"] != "para":
        return None
    d = norm_digits(item["plain"])
    rx = TABLE_CAP if kind == "table" else FIG_CAP
    m = rx.match(d)
    if not m:
        return None
    sep, rest = m.group(2), m.group(3).strip()
    if not sep and (SENTENCE_END.search(rest) or len(rest.split()) > 10):
        return None                      # "Table 2 shows the results." is a sentence, not a caption
    mk = item["text"]
    dm = norm_digits(mk).rstrip()
    if rest and dm.endswith(rest):       # slice the ORIGINAL markup (digits/emphasis preserved)
        return mk.rstrip()[len(dm) - len(rest):].strip(), "caption"
    return rest, "caption"


def postprocess(items: List[dict], res: NormalizeResult, expect_title: bool = True) -> List[Box]:
    # 1. headings: strip typed numbers, guess headings from numbered/bold paragraphs --------------
    out: List[dict] = []
    for it in items:
        if it["kind"] == "heading":
            text, depth = _strip_heading_number(it["plain"], it["text"])
            it = dict(it, text=text, num_depth=depth)
        elif it["kind"] == "para" and it.get("all_bold") and len(it["plain"].split()) <= 12 \
                and not SENTENCE_END.search(it["plain"]) and len(it["plain"]) > 1 \
                and not _caption_like(it["plain"]):
            text, depth = _strip_heading_number(it["plain"], escape(it["plain"]))
            res.warnings.append({"code": "HEADING_GUESSED", "message": f"Treated bold line '{it['plain'][:50]}' as a heading."})
            it = {"kind": "heading", "level": None, "text": text, "plain": it["plain"], "num_depth": depth, "guessed": True}
        elif it["kind"] == "para":
            d = norm_digits(it["plain"])
            m = NUM_DEC.match(d)
            if m and m.group(1).count(".") >= 1 and len(it["plain"].split()) <= 15 and not SENTENCE_END.search(it["plain"]):
                text, depth = _strip_heading_number(it["plain"], it["text"])
                res.warnings.append({"code": "HEADING_GUESSED", "message": f"Treated numbered line '{it['plain'][:50]}' as a heading."})
                it = {"kind": "heading", "level": depth, "text": text, "plain": it["plain"], "num_depth": depth, "guessed": True}
        elif it["kind"] == "title":
            if not res.title:
                res.title = it["plain"]
            continue
        out.append(it)
    items = out

    # a short first paragraph directly followed by a heading is the title (Google Docs "Title", plain text)
    if expect_title and not res.title and len(items) >= 2 and items[0]["kind"] == "para" \
            and items[1]["kind"] == "heading" and len(items[0]["plain"].split()) <= 20 \
            and not SENTENCE_END.search(items[0]["plain"]) and not _caption_like(items[0]["plain"]) \
            and "\n" not in items[0]["plain"]:
        t = items.pop(0)
        res.title = t["plain"]
        res.warnings.append({"code": "TITLE_DETECTED", "message": f"Used '{t['plain'][:60]}' as the document title."})

    # 2. headings: decide levels ----------------------------------------------------------------
    heads = [it for it in items if it["kind"] == "heading"]
    for h in heads:
        if h.get("num_depth"):
            h["level"] = h["num_depth"]
    tagged = [h["level"] for h in heads if h.get("level")]
    # a first un-numbered heading followed by numbered ones is the document title
    if expect_title and heads and items.index(heads[0]) == 0 and not heads[0].get("num_depth") \
            and any(h.get("num_depth") for h in heads[1:]):
        t = items.pop(0)
        res.title = res.title or t["plain"]
        res.warnings.append({"code": "TITLE_DETECTED", "message": f"Used '{t['plain'][:60]}' as the document title."})
        heads = heads[1:]
        tagged = [h["level"] for h in heads if h.get("level")]
    last = 0
    for h in heads:
        if not h.get("level"):
            h["level"] = (last + 1) if last else 1
        last = h["level"]
    if tagged or heads:
        mn = min(h["level"] for h in heads) if heads else 1
        for h in heads:
            h["level"] = h["level"] - (mn - 1)

    # 3. captions and sources -------------------------------------------------------------------
    items = list(items)
    # a typed figure caption with no image next to it (plain text cannot carry images): a figure slot
    for k, it in enumerate(items):
        near = {items[j]["kind"] for j in (k - 1, k + 1) if 0 <= j < len(items)}
        if it["kind"] == "para" and "figure" not in near and _caption_like(it["plain"]) \
                and FIG_CAP.match(norm_digits(it["plain"])):
            got = _is_caption(it, "figure")
            if got:
                items[k] = {"kind": "figure", "src": None, "caption": got[0], "alt": ""}
                res.warnings.append({"code": "FIGURE_NEEDS_UPLOAD",
                                     "message": f"Figure '{got[0][:40]}' was typed as a caption only. Upload the image."})
    i = 0
    while i < len(items):
        it = items[i]
        if it["kind"] in ("table", "figure"):
            kind = it["kind"]
            have = bool(it.get("caption", "").strip())
            if not have:
                order = (-1, 1) if kind == "table" else (1, -1)
                for off in order:
                    j = i + off
                    if 0 <= j < len(items):
                        got = _is_caption(items[j], kind)
                        if got:
                            it["caption"] = got[0]
                            items.pop(j)
                            if j < i:
                                i -= 1
                            have = True
                            break
            # source / note lines directly after
            while i + 1 < len(items) and items[i + 1]["kind"] == "para":
                nxt = items[i + 1]
                ms = SOURCE_LINE.match(nxt["plain"])
                mn_ = NOTE_LINE.match(nxt["plain"])
                if ms:
                    it["source"] = nxt["text"][len(nxt["text"]) - len(ms.group(2)):] if nxt["text"].endswith(ms.group(2)) else ms.group(2)
                elif mn_ and kind == "table":
                    it["note"] = nxt["text"][len(nxt["text"]) - len(mn_.group(2)):] if nxt["text"].endswith(mn_.group(2)) else mn_.group(2)
                else:
                    break
                items.pop(i + 1)
            if not have and kind == "figure" and it.get("alt", "").strip():
                it["caption"] = it["alt"].strip()
                have = True
            if not have:
                res.warnings.append({"code": "CAPTION_MISSING", "message": f"A pasted {kind} has no caption. Add one in the editor."})
        i += 1

    # 4. build tree -----------------------------------------------------------------------------
    root: List[Box] = []
    stack: List[SectionBox] = []

    def target() -> List[Box]:
        return stack[-1].content if stack else root

    for it in items:
        k = it["kind"]
        if k == "heading":
            lvl = max(1, it["level"])
            if lvl > len(stack) + 1:
                res.warnings.append({"code": "HEADING_LEVEL_SKIPPED",
                                     "message": f"Heading '{it['plain'][:40]}' skipped a level; it was moved up."})
                lvl = len(stack) + 1
            del stack[lvl - 1:]
            sec = SectionBox(title=it["text"])
            target().append(sec)
            stack.append(sec)
        elif k == "para":
            target().append(ParagraphBox(text=it["text"]))
        elif k == "list":
            target().append(_build_list(it["entries"], it["ordered"]))
        elif k == "table":
            hdr = it.get("header_rows", 1)
            data = [[_unbold(c) for c in row] if r < hdr else row for r, row in enumerate(it["data"])]
            target().append(TableBox(caption=it.get("caption", ""), data=data, header_rows=hdr,
                                     note=it.get("note", ""), source=it.get("source", "")))
        elif k == "figure":
            target().append(FigureBox(caption=it.get("caption", ""), source=it.get("source", ""), src=it.get("src")))
    _assign_ids(root)
    return root


def _build_list(entries: List[Tuple[int, str]], ordered: bool) -> ListBox:
    root: List[ListItem] = []
    stack: List[Tuple[int, List[ListItem]]] = [(-1, root)]
    prev_level = -1
    for level, text in entries:
        level = min(level, prev_level + 1)            # no jumping over a level
        while stack[-1][0] >= level:
            stack.pop()
        item = ListItem(text=text)
        stack[-1][1].append(item)
        stack.append((level, item.children))
        prev_level = level
    return ListBox(ordered=ordered, items=root)


def _assign_ids(boxes: List[Box], prefix: str = "s") -> None:
    n = 0
    for b in boxes:
        if isinstance(b, SectionBox):
            n += 1
            b.id = f"{prefix}{n}"
            _assign_ids(b.content, f"{b.id}.")


# --------------------------------------------------------------------------- entry point
MD_HINT = re.compile(r"(^|\n)\s{0,3}#{1,6}\s|```|\*\*[^*\n]+\*\*|\|\s*:?-{2,}|!\[[^\]]*\]\(|\[[^\]]+\]\([^)]+\)|(^|\n)>\s")
HTML_STRUCT = re.compile(r"<\s*(h[1-6]|p|ul|ol|li|table|tr|img|div|br|b|strong|i|em|span)\b", re.I)


def normalize(text: Optional[str] = None, html: Optional[str] = None,
              fmt: Optional[str] = None) -> NormalizeResult:
    """Normalize pasted content. `fmt` forces 'html' | 'markdown' | 'text'."""
    res = NormalizeResult()
    if fmt is None:
        if html and HTML_STRUCT.search(html):
            fmt = "html"
        elif text and MD_HINT.search(text):
            fmt = "markdown"
        else:
            fmt = "text"
    res.source_format = fmt
    if fmt == "html":
        items = parse_html(html or text or "", res)
    elif fmt == "markdown":
        items = parse_markdown(text or "", res)
    else:
        items = parse_text(text or "", res)
    res.boxes = postprocess(items, res)
    return res
