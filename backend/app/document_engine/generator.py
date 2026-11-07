"""DOCX generator.

Opens the UPLOADED TEMPLATE, clears its body, and writes the content using the
template's own styles (headers, footers, logos, numbering, page setup survive).
No AI is involved. Everything not provided by the template falls back to a
safe default style created inside the output file.

Real Word features are used instead of typed text:
  * heading numbers come from a multilevel list linked to heading styles
  * "Table 1" / "Figure 2" use SEQ fields (cached result is written too)
  * lists use real numbering definitions (restarting correctly)
"""
from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.text.run import Run as DocxRun
from lxml import etree
from PIL import Image

from ..core import placeholders
from ..core.inline import Run, parse_inline, plain
from ..schemas.content import (DocumentContent, FigureBox, ListBox, ListItem,
                               ParagraphBox, SectionBox, TableBox)
from ..schemas.profile import FormattingProfile
from ..template_engine.ooxml import (SCRIPT_LANG, StyleResolver, TWIPS_PER_CM, dominant_script,
                                     page_text_height_twips, page_text_width_twips, paragraph_text, script_of)

RPR_ORDER = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
             "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden",
             "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
             "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout",
             "specVanish", "oMath"]
PPR_ORDER = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
             "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
             "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
             "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap",
             "jc", "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl", "divId",
             "cnfStyle", "rPr", "sectPr", "pPrChange"]
TBLPR_ORDER = ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
               "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders", "shd",
               "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription"]
TCPR_ORDER = ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap", "tcMar",
              "textDirection", "tcFitText", "vAlign", "hideMark"]
SECTPR_ORDER = ["headerReference", "footerReference", "footnotePr", "endnotePr", "type", "pgSz", "pgMar",
                "paperSrc", "pgBorders", "lnNumType", "pgNumType", "cols", "formProt", "vAlign", "noEndnote",
                "titlePg", "textDirection", "bidi", "rtlGutter", "docGrid", "printerSettings", "sectPrChange"]
CONTENT_BOOKMARK = "_SmartDocContent"
RTL_LANGS = {"ar", "he", "fa", "ur", "ps", "sd", "yi", "dv", "ug"}
# language -> script, for languages whose script is not Latin
LANG_SCRIPT = {"ar": "Arab", "fa": "Arab", "ur": "Arab", "ps": "Arab", "sd": "Arab", "ug": "Arab", "ckb": "Arab",
               "he": "Hebr", "yi": "Hebr", "bn": "Beng", "as": "Beng", "hi": "Deva", "mr": "Deva", "ne": "Deva",
               "sa": "Deva", "pa": "Guru", "gu": "Gujr", "or": "Orya", "ta": "Taml", "te": "Telu", "kn": "Knda",
               "ml": "Mlym", "si": "Sinh", "th": "Thai", "lo": "Laoo", "bo": "Tibt", "my": "Mymr", "km": "Khmr",
               "zh": "Hani", "ja": "Jpan", "ko": "Hang"}
CJK_SCRIPTS = {"Hani", "Jpan", "Hang"}
# zero digit of the languages whose own digits are in common use
DIGIT_ZERO = {"bn": 0x09E6, "as": 0x09E6, "ar": 0x0660, "fa": 0x06F0, "ur": 0x06F0, "ps": 0x06F0,
              "hi": 0x0966, "mr": 0x0966, "ne": 0x0966, "sa": 0x0966}
# CT_Compat children that must precede doNotExpandShiftReturn
COMPAT_BEFORE = ["spaceForUL", "balanceSingleByteDoubleByteWidth", "doNotLeaveBackslashAlone", "ulTrailSpace"]
# CT_Settings children that follow w:compat
SETTINGS_AFTER_COMPAT = {"docVars", "rsids", "mathPr", "attachedSchema", "themeFontLang", "clrSchemeMapping",
                         "doNotIncludeSubdocsInStats", "doNotAutoCompressPictures", "forceUpgrade", "captions",
                         "readModeInkLockDown", "smartTagType", "schemaLibrary", "shapeDefaults",
                         "doNotEmbedSmartTags", "decimalSymbol", "listSeparator"}
NUMERIC = re.compile(r"^[\s$€£৳]*[-+]?[\d০-৯٠-٩,.\s]+%?\s*$")


def sort_children(el, order: List[str]) -> None:
    """Re-order children to the schema sequence (Word is strict about it)."""
    rank = {qn(f"w:{n}"): i for i, n in enumerate(order)}
    kids = list(el)
    kids.sort(key=lambda c: rank.get(c.tag, len(order)))
    for k in kids:
        el.remove(k)
    for k in kids:
        el.append(k)


def native_digits(text: str, lang_code: str) -> str:
    zero = DIGIT_ZERO.get(lang_code.split("-")[0].lower())
    if zero is None:
        return text
    return "".join(chr(zero + int(c)) if "0" <= c <= "9" else c for c in text)


def first_strong(text: str) -> Optional[bool]:
    """Unicode bidi rules P2/P3: True if the first strong character is right-to-left, False if
    left-to-right, None if the text has no strong character (digits, punctuation only)."""
    for ch in text:
        d = unicodedata.bidirectional(ch)
        if d in ("R", "AL"):
            return True
        if d == "L":
            return False
    return None


def script_runs(text: str) -> List[str]:
    """Split text where the script changes (latin / complex / rtl / east_asian). Neutral characters
    (spaces, digits, punctuation) stay with the run before them."""
    out: List[str] = []
    cur_kind: Optional[str] = None
    for ch in text:
        kind = script_of(ch) if ch.isalpha() else None
        if out and (kind is None or kind == cur_kind or cur_kind is None):
            out[-1] += ch
            if cur_kind is None:
                cur_kind = kind
        else:
            out.append(ch)
            cur_kind = kind
    return out


def _w(tag: str, **attrs) -> OxmlElement:
    el = OxmlElement(f"w:{tag}")
    for k, v in attrs.items():
        el.set(qn(f"w:{k}"), str(v))
    return el


@dataclass
class GenerationResult:
    path: str
    warnings: List[Dict[str, str]] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)


# role -> (style name, size_pt, bold, italic, align, space_before, space_after)
FALLBACK_STYLES = {
    "title": ("Title", 20, True, False, "center", 0, 12),
    "subtitle": ("Subtitle", 13, False, True, "center", 0, 10),
    "author": ("SmartDoc Author", None, False, False, "center", 0, 8),
    "abstract": ("SmartDoc Abstract", None, False, False, "justify", 6, 6),
    "caption": ("Caption", 9, False, True, None, 6, 6),
    "note": ("SmartDoc Note", 9, False, False, None, 2, 6),
    "table_text": ("SmartDoc Table Text", None, False, False, None, 2, 2),
    "figure": ("SmartDoc Figure", None, False, False, "center", 6, 4),
    "quote": ("Quote", None, False, True, None, 6, 6),
    "list_bullet": ("List Paragraph", None, False, False, None, 0, 2),
    "list_number": ("List Paragraph", None, False, False, None, 0, 2),
}
HEADING_FALLBACK = {1: 16, 2: 14, 3: 12, 4: 11, 5: 11, 6: 10, 7: 10, 8: 10, 9: 10}


class Generator:
    def __init__(self, template_path: str, profile: FormattingProfile,
                 content: DocumentContent, media_path: Callable[[str], Optional[str]]):
        self.doc = Document(template_path)
        self.profile = profile
        self.content = content
        self.media_path = media_path
        self.warnings: List[Dict[str, str]] = []
        self.seq = {"Table": 0, "Figure": 0}
        self.stats = {"sections": 0, "paragraphs": 0, "lists": 0, "tables": 0, "figures": 0}
        # the document's own language wins over the template's default language
        self.profile = profile = profile.model_copy(deep=True)
        if content.language:
            profile.language.code = content.language
        self.rtl = profile.language.rtl or content.language.split("-")[0].lower() in RTL_LANGS
        self.sr = StyleResolver(self.doc)
        self._kept: List = []                 # template body elements kept in layout mode
        self._kept_names: set = set()         # placeholders inside them
        self._prepare_body()
        self.styles: Dict[str, object] = {s.style_id: s for s in self.doc.styles}
        self.sect_pr = self.doc.element.body.get_or_add_sectPr()
        self.text_width = page_text_width_twips(self.sect_pr)
        self.text_height = page_text_height_twips(self.sect_pr)
        self._style_cache: Dict[str, str] = {}
        self._last_was_table = False
        self._after_heading = False
        self._heading_num_suppress: set = set()
        self._completed: Dict[tuple, int] = {}       # (template abstractNumId, kind) -> completed copy
        self._completed_num: Dict[int, int] = {}     # completed abstractNumId -> shared bullet numId

    # ------------------------------------------------------------------ utils
    def warn(self, code: str, message: str) -> None:
        self.warnings.append({"code": code, "message": message})

    def _prepare_body(self) -> None:
        body = self.doc.element.body
        sect = body.get_or_add_sectPr()
        if sect.find(qn("w:pgSz")) is None:
            sect.append(_w("pgSz", w=11906, h=16838))
        if sect.find(qn("w:pgMar")) is None:
            sect.append(_w("pgMar", top=1440, right=1440, bottom=1440, left=1440,
                           header=708, footer=708, gutter=0))
        sort_children(sect, SECTPR_ORDER)
        children = [c for c in body if c is not sect]
        keep = self._layout_end(children) if self.profile.keep_template_layout else 0
        if keep is None:
            self.warn("LAYOUT_NOT_KEPT", "The template has no heading in its body, so SmartDoc cannot tell its "
                      "first-page layout from its sample text. The whole body was replaced.")
            keep = 0
        self._kept = children[:keep]
        self._kept_names = set(placeholders.names_in(self._kept))
        for child in children[keep:]:
            body.remove(child)
        if self._kept:
            # hidden bookmark where the user's content starts, so the validator can tell layout from content
            ids = [int(b.get(qn("w:id"))) for b in body.iter(qn("w:bookmarkStart")) if (b.get(qn("w:id")) or "").isdigit()]
            bid = max(ids, default=0) + 1
            sect.addprevious(_w("bookmarkStart", id=bid, name=CONTENT_BOOKMARK))
            sect.addprevious(_w("bookmarkEnd", id=bid))

    def _layout_end(self, children) -> Optional[int]:
        """Index of the template's first heading paragraph: what comes before it is the kept layout."""
        heading_ids = {sid for role, sid in self.profile.roles.items() if role.startswith("heading_")}
        for i, el in enumerate(children):
            if el.tag != qn("w:p"):
                continue
            ps = el.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
            sid = ps.get(qn("w:val")) if ps is not None else None
            # an empty heading-styled paragraph is spacing inside the layout, not the article's first heading
            if sid and (sid in heading_ids or self.sr.resolve(sid).get("outline_level") is not None) \
                    and paragraph_text(el).strip():
                return i
        return None

    def _placeholder_values(self) -> Dict[str, str]:
        c = self.content
        values = {"TITLE": plain(c.title), "SUBTITLE": plain(c.subtitle),
                  "AUTHORS": ", ".join(a.name for a in c.authors if a.name.strip()),
                  "ABSTRACT": plain(c.abstract), "KEYWORDS": ", ".join(k.strip() for k in c.keywords if k.strip())}
        values = {k: v for k, v in values.items() if v.strip()}
        values.update(c.fields)                        # the user's template fields win
        return values

    def _fill_placeholders(self) -> None:
        targets = list(self._kept)
        for rel in self.doc.part.rels.values():
            if rel.reltype.endswith(("/header", "/footer")):
                targets.append(rel.target_part.element)

        def script(run_el, value):
            self._script_props(DocxRun(run_el, None), value, False, False, {}, None)
        missing = placeholders.fill(targets, self._placeholder_values(), on_value=script)
        if missing:
            listed = ", ".join("{{" + n + "}}" for n in sorted(missing))
            self.warn("PLACEHOLDER_UNFILLED", f"Not filled: {listed}. Enter values under 'Template fields'.")

    # ------------------------------------------------------------------ styles
    def _new_style(self, name: str, base_id: Optional[str]):
        # real templates contain styles without a w:name (e.g. table styles "a", "a0")
        existing = next((s for s in self.doc.styles if (s.name or "").lower() == name.lower()
                         and s.type == WD_STYLE_TYPE.PARAGRAPH), None)
        if existing is not None:
            return existing
        st = self.doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        if base_id and base_id in self.styles:
            st.base_style = self.styles[base_id]
        self.styles[st.style_id] = st
        self.sr.by_id[st.style_id] = st.element
        return st

    def style_for(self, role: str) -> Optional[str]:
        """Return a style id for a role, creating a safe fallback when needed."""
        if role in self._style_cache:
            return self._style_cache[role]
        sid = self.profile.roles.get(role)
        if sid and sid not in self.styles:
            self.warn("STYLE_NOT_FOUND", f"Style '{sid}' mapped to role '{role}' does not exist in the template; using a fallback.")
            sid = None
        if sid is None:
            sid = self._fallback(role)
        self._style_cache[role] = sid
        return sid

    def _body_id(self) -> Optional[str]:
        sid = self.profile.roles.get("body")
        if sid in self.styles:
            return sid
        return self.sr.default_par_id

    def _fallback(self, role: str) -> Optional[str]:
        if role == "body":
            return self._body_id()
        if role.startswith("heading_"):
            lvl = int(role.split("_")[1])
            for k in range(lvl - 1, 0, -1):   # nearest defined lower level
                s = self.profile.roles.get(f"heading_{k}")
                if s in self.styles:
                    return s
            for k in range(lvl + 1, 10):      # or nearest deeper one
                s = self.profile.roles.get(f"heading_{k}")
                if s in self.styles:
                    return s
            st = self._new_style(f"Heading {lvl}", self._body_id())
            st.font.bold = True
            st.font.size = Pt(HEADING_FALLBACK[lvl])
            self._mirror_cs(st)
            st.paragraph_format.first_line_indent = Cm(0)
            st.paragraph_format.keep_with_next = True
            st.paragraph_format.space_before = Pt(12)
            st.paragraph_format.space_after = Pt(6)
            ppr = st.element.get_or_add_pPr()
            for old in ppr.findall(qn("w:outlineLvl")):
                ppr.remove(old)
            ppr.append(_w("outlineLvl", val=lvl - 1))
            sort_children(ppr, PPR_ORDER)
            self.warn("HEADING_STYLE_CREATED", f"Created a clean 'Heading {lvl}' style (the template had none).")
            return st.style_id
        spec = FALLBACK_STYLES.get(role)
        if spec is None:
            return self._body_id()
        name, size, bold, italic, align, before, after = spec
        st = self._new_style(name, self._body_id())
        if size:
            st.font.size = Pt(size)
        if bold:
            st.font.bold = True
        if italic:
            st.font.italic = True
        self._mirror_cs(st)
        pf = st.paragraph_format
        pf.space_before, pf.space_after = Pt(before), Pt(after)
        pf.first_line_indent = Cm(0)
        pf.left_indent = Cm(0)
        if role in ("table_text", "note", "caption"):
            pf.line_spacing = 1.0
        if align:
            from docx.enum.text import WD_ALIGN_PARAGRAPH as A
            pf.alignment = {"center": A.CENTER, "justify": A.JUSTIFY, "left": A.LEFT}[align]
        if role == "figure":
            pf.keep_with_next = True
        if role == "quote":
            pf.left_indent = Cm(1)
        return st.style_id

    @staticmethod
    def _mirror_cs(st) -> None:
        """Bold/italic/size on a style we create also apply to complex-script text (bCs/iCs/szCs)."""
        rpr = st.element.rPr
        if rpr is None:
            return
        for latin, cs in (("b", "bCs"), ("i", "iCs")):
            if rpr.find(qn(f"w:{latin}")) is not None and rpr.find(qn(f"w:{cs}")) is None:
                rpr.append(_w(cs))
        sz = rpr.find(qn("w:sz"))
        if sz is not None and rpr.find(qn("w:szCs")) is None:
            rpr.append(_w("szCs", val=sz.get(qn("w:val"))))
        sort_children(rpr, RPR_ORDER)

    # --------------------------------------------------------------- numbering
    def _numbering(self):
        return self.doc.part.numbering_part.element

    def _next_id(self, tag: str, attr: str) -> int:
        ids = [int(e.get(qn(f"w:{attr}"))) for e in self._numbering().findall(qn(f"w:{tag}"))]
        return (max(ids) + 1) if ids else 1

    def _add_abstract(self, abstract_el) -> int:
        root = self._numbering()
        aid = self._next_id("abstractNum", "abstractNumId")
        abstract_el.set(qn("w:abstractNumId"), str(aid))
        first_num = root.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(abstract_el)
        else:
            root.append(abstract_el)
        return aid

    def _add_num(self, abstract_id: int, restart: bool = False) -> int:
        nid = self._next_id("num", "numId")
        num = _w("num", numId=nid)
        num.append(_w("abstractNumId", val=abstract_id))
        if restart:
            ov = _w("lvlOverride", ilvl=0)
            ov.append(_w("startOverride", val=1))
            num.append(ov)
        self._numbering().append(num)
        return nid

    def _abstract_of(self, num_id: str) -> Optional[int]:
        for n in self._numbering().findall(qn("w:num")):
            if n.get(qn("w:numId")) == str(num_id):
                a = n.find(qn("w:abstractNumId"))
                return int(a.get(qn("w:val"))) if a is not None else None
        return None

    @staticmethod
    def _generated_level(kind: str, lvl: int, left: int, hanging: int):
        fmts = ["decimal", "lowerLetter", "lowerRoman"]
        bullets = ["•", "–", "▪"]
        lv = _w("lvl", ilvl=lvl)
        lv.append(_w("start", val=1))
        if kind == "number":
            lv.append(_w("numFmt", val=fmts[lvl % 3]))
            lv.append(_w("lvlText", val=f"%{lvl + 1}."))
        else:
            lv.append(_w("numFmt", val="bullet"))
            lv.append(_w("lvlText", val=bullets[lvl % 3]))
        lv.append(_w("lvlJc", val="left"))
        ppr = _w("pPr")
        ppr.append(_w("ind", left=left, hanging=hanging))
        lv.append(ppr)
        return lv

    def _generated_abstract(self, kind: str) -> int:
        a = _w("abstractNum")
        a.append(_w("multiLevelType", val="hybridMultilevel"))
        for lvl in range(9):
            a.append(self._generated_level(kind, lvl, 567 * (lvl + 1), 283))
        return self._add_abstract(a)

    def _complete_abstract(self, abstract_id: int, kind: str, depth: int) -> int:
        """Template list numbering is often singleLevel; nested items would hit undefined
        levels and render as decimals. Clone it and fill the missing levels."""
        src = None
        for a in self._numbering().findall(qn("w:abstractNum")):
            if a.get(qn("w:abstractNumId")) == str(abstract_id):
                src = a
        if src is None:
            return self._generated_abstract(kind)
        levels = {int(l.get(qn("w:ilvl"))): l for l in src.findall(qn("w:lvl"))}
        if all(l in levels for l in range(depth)):
            return abstract_id
        key = (abstract_id, kind)
        if key in self._completed:
            return self._completed[key]
        left, hanging = 567, 283
        ind = levels[0].find(f"{qn('w:pPr')}/{qn('w:ind')}") if 0 in levels else None
        if ind is not None:
            left = int(ind.get(qn("w:left")) or ind.get(qn("w:start")) or left)
            hanging = int(ind.get(qn("w:hanging")) or hanging)
        a = _w("abstractNum")
        a.append(_w("multiLevelType", val="hybridMultilevel"))
        for lvl in range(9):
            if lvl in levels:
                lv = copy.deepcopy(levels[lvl])
                for ps in lv.findall(qn("w:pStyle")):   # the template's own list keeps the style link
                    lv.remove(ps)
            else:
                lv = self._generated_level(kind, lvl, left + 567 * lvl, hanging)
            a.append(lv)
        self._completed[key] = self._add_abstract(a)
        return self._completed[key]

    def _setup_heading_numbering(self) -> None:
        mode = self.profile.heading_numbering
        if mode == "auto":
            # a style reused for several levels (fallback) is linked to its first level only
            level_of: Dict[str, int] = {}
            for lvl in range(1, 10):
                sid = self.style_for(f"heading_{lvl}")
                if sid and sid not in level_of:
                    level_of[sid] = lvl
            # a style may be linked to one list only: unlink it from the template's own heading list
            for old in self._numbering().findall(qn("w:abstractNum")):
                for lv in old.findall(qn("w:lvl")):
                    ps = lv.find(qn("w:pStyle"))
                    if ps is not None and ps.get(qn("w:val")) in level_of:
                        lv.remove(ps)
            a = _w("abstractNum")
            a.append(_w("multiLevelType", val="multilevel"))
            for lvl in range(9):
                lv = _w("lvl", ilvl=lvl)
                lv.append(_w("start", val=1))
                lv.append(_w("numFmt", val="decimal"))
                sid = self.style_for(f"heading_{lvl + 1}")
                if sid and level_of.get(sid) == lvl + 1:
                    lv.append(_w("pStyle", val=sid))
                if self.profile.heading_number_suffix == "space":
                    lv.append(_w("suff", val="space"))
                lv.append(_w("lvlText", val=".".join(f"%{i + 1}" for i in range(lvl + 1)) + ("." if lvl == 0 else "")))
                lv.append(_w("lvlJc", val="left"))
                ppr = _w("pPr")
                # room for "1." at heading size up to "1.1.1.1.1" (1.0 cm, +0.3 cm per level);
                # the linked heading style gets the same indent below
                hang = 567 + 170 * lvl if self.profile.heading_number_suffix == "tab" else 0
                ppr.append(_w("ind", left=hang, hanging=hang))
                lv.append(ppr)
                a.append(lv)
            aid = self._add_abstract(a)
            nid = self._add_num(aid)
            for sid, lvl in level_of.items():
                st = self.styles.get(sid)
                if st is None:
                    continue
                ppr = st.element.get_or_add_pPr()
                for old in ppr.findall(qn("w:numPr")):
                    ppr.remove(old)
                np_ = _w("numPr")
                np_.append(_w("ilvl", val=lvl - 1))
                np_.append(_w("numId", val=nid))
                ppr.append(np_)
                # a style's own indent overrides its numbering level's; make them the same
                for old in ppr.findall(qn("w:ind")):
                    ppr.remove(old)
                width = 567 + 170 * (lvl - 1) if self.profile.heading_number_suffix == "tab" else 0
                ppr.append(_w("ind", left=width, hanging=width))
                sort_children(ppr, PPR_ORDER)
        elif mode == "none":
            for lvl in range(1, 10):
                sid = self.style_for(f"heading_{lvl}")
                if sid and self.sr.resolve(sid).get("num_id") not in (None, "0"):
                    self._heading_num_suppress.add(sid)

    def _apply_language_defaults(self) -> None:
        if self.rtl:
            sect = self.sect_pr
            if sect.find(qn("w:bidi")) is None:
                sect.append(_w("bidi"))
                sort_children(sect, SECTPR_ORDER)
        self._dont_stretch_soft_breaks()
        lang = self.profile.language
        if not lang.set_default_language:
            return
        root = self.doc.styles.element
        dd = root.find(qn("w:docDefaults"))
        if dd is None:
            dd = _w("docDefaults")
            root.insert(0, dd)
        pr = dd.find(qn("w:rPrDefault"))
        if pr is None:
            pr = _w("rPrDefault"); dd.insert(0, pr)
        rpr = pr.find(qn("w:rPr"))
        if rpr is None:
            rpr = _w("rPr"); pr.append(rpr)
        old = rpr.find(qn("w:lang"))
        keep = {k: old.get(qn(f"w:{k}")) for k in ("val", "bidi", "eastAsia")} if old is not None else {}
        for el in rpr.findall(qn("w:lang")):
            rpr.remove(el)
        # w:val is the language of Latin text, w:bidi of complex-script/RTL text, w:eastAsia of CJK text;
        # only the slot that matches the document's script is changed
        script = LANG_SCRIPT.get(lang.code.split("-")[0].lower())
        slot = "val" if script is None else ("eastAsia" if script in CJK_SCRIPTS else "bidi")
        keep[slot] = lang.code
        rpr.append(_w("lang", **{k: v for k, v in keep.items() if v}))
        sort_children(rpr, RPR_ORDER)

    def _dont_stretch_soft_breaks(self) -> None:
        """A line ending in a manual line break must not be justified across the column."""
        settings = self.doc.settings.element
        compat = settings.find(qn("w:compat"))
        if compat is None:
            compat = _w("compat")
            after = next((c for c in settings if etree.QName(c).localname in SETTINGS_AFTER_COMPAT), None)
            (after.addprevious(compat) if after is not None else settings.append(compat))
        if compat.find(qn("w:doNotExpandShiftReturn")) is not None:
            return
        el = _w("doNotExpandShiftReturn")
        before = [c for c in compat if etree.QName(c).localname in COMPAT_BEFORE]
        (before[-1].addnext(el) if before else compat.insert(0, el))

    # ---------------------------------------------------------- paragraph ops
    def _ppr(self, p):
        return p._p.get_or_add_pPr()

    def _finish_ppr(self, p) -> None:
        ppr = p._p.pPr
        if ppr is not None:
            sort_children(ppr, PPR_ORDER)

    def _style_obj(self, sid: Optional[str]):
        return self.styles.get(sid) if sid else None

    def _direction(self, ppr, sid: Optional[str], text: Optional[str]) -> None:
        """Paragraph direction: the first strong character of its text, else the document's direction.
        When the paragraph style is already RTL and the text is LTR, say so explicitly."""
        rtl = first_strong(text) if text is not None else None
        if rtl is None:
            rtl = self.rtl
        for old in ppr.findall(qn("w:bidi")):
            ppr.remove(old)
        if rtl:
            ppr.append(_w("bidi"))
        elif sid and self.sr.resolve(sid).get("bidi"):
            ppr.append(_w("bidi", val=0))

    def new_par(self, sid: Optional[str], keep_next: bool = False, align: Optional[str] = None,
                suppress_num: bool = False, text: Optional[str] = None):
        p = self.doc.add_paragraph(style=self._style_obj(sid))
        ppr = self._ppr(p)
        self._direction(ppr, sid, plain(text) if text is not None else None)
        if keep_next:
            ppr.append(_w("keepNext"))
        if align:
            ppr.append(_w("jc", val={"justify": "both"}.get(align, align)))
        if suppress_num or (sid in self._heading_num_suppress):
            np_ = _w("numPr"); np_.append(_w("ilvl", val=0)); np_.append(_w("numId", val=0))
            ppr.append(np_)
        self._finish_ppr(p)
        return p

    def add_text(self, p, text: str, sid: Optional[str], size_override: Optional[float] = None,
                 force_bold: bool = False) -> None:
        resolved = self.sr.resolve(sid) if sid else {}
        for r in parse_inline(text):
            for i, line in enumerate(r.text.split("\n")):
                if i > 0:
                    p.add_run().add_break()
                for piece in script_runs(line):
                    self._styled_run(p, piece, r, force_bold, size_override, resolved)

    def _styled_run(self, p, piece: str, r, force_bold: bool, size_override, resolved) -> None:
        run = p.add_run(piece)
        bold = r.bold or force_bold
        if bold:
            run.bold = True
        if r.italic:
            run.italic = True
        if r.sup:
            run.font.superscript = True
        if r.sub:
            run.font.subscript = True
        if size_override:
            run.font.size = Pt(size_override)
        self._script_props(run, piece, bold, r.italic, resolved, size_override)

    def _script_props(self, run, text, bold, italic, resolved, size_override) -> None:
        kind = script_of(text)
        if kind == "latin":
            return
        rpr = run._r.get_or_add_rPr()
        lang = self.profile.language
        if kind in ("complex", "rtl"):
            if lang.complex_script_font:
                f = rpr.find(qn("w:rFonts"))
                if f is None:
                    f = _w("rFonts"); rpr.append(f)
                f.set(qn("w:cs"), lang.complex_script_font)
            # style bold/italic must also reach complex-script text (bCs/iCs)
            if bold or (resolved.get("bold") and not resolved.get("bold_cs")):
                rpr.append(_w("bCs"))
            if italic or (resolved.get("italic") and not resolved.get("italic_cs")):
                rpr.append(_w("iCs"))
            size = size_override or resolved.get("size_pt")
            if size and (size_override or not resolved.get("size_cs_pt")):
                rpr.append(_w("szCs", val=int(size * 2)))
            if kind == "rtl":
                rpr.append(_w("rtl"))
            rpr.append(_w("lang", bidi=self._run_lang(text)))
        elif kind == "east_asian" and lang.east_asian_font:
            f = rpr.find(qn("w:rFonts"))
            if f is None:
                f = _w("rFonts"); rpr.append(f)
            f.set(qn("w:eastAsia"), lang.east_asian_font)
        sort_children(rpr, RPR_ORDER)

    def _run_lang(self, text: str) -> str:
        """The document's language when the run is in its script, else the run's script's language."""
        code = self.profile.language.code or "en"
        script = dominant_script(text)
        if script is None or LANG_SCRIPT.get(code.split("-")[0].lower()) == script:
            return code
        return SCRIPT_LANG.get(script, code)

    def par(self, role: str, text: str, **kw):
        sid = self.style_for(role)
        p = self.new_par(sid, text=text, **{k: v for k, v in kw.items() if k in ("keep_next", "align")})
        self.add_text(p, text, sid)
        return p

    # ----------------------------------------------------------------- fields
    def _fld(self, p, kind: str, resolved: Optional[dict] = None) -> None:
        def run_with(child):
            r = OxmlElement("w:r"); r.append(child); p._p.append(r); return r
        run_with(_w("fldChar", fldCharType="begin"))
        it = _w("instrText"); it.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        it.text = f" SEQ {kind} \\* ARABIC "
        run_with(it)
        run_with(_w("fldChar", fldCharType="separate"))
        number = str(self.seq[kind])
        if self.profile.language.native_digits:
            number = native_digits(number, self.profile.language.code)
        t = _w("t"); t.text = number
        result = run_with(t)
        # native digits are complex-script text: same cs font and language as the label next to them
        self._script_props(DocxRun(result, p), number, False, False, resolved or {}, None)
        run_with(_w("fldChar", fldCharType="end"))

    def caption(self, kind: str, text: str, keep_next: bool) -> None:
        rule = self.profile.table if kind == "Table" else self.profile.figure
        self.seq[kind] += 1
        # a separate figure-caption style only when the profile maps one (predefined designs)
        sid = (self.profile.roles["figure_caption"] if kind == "Figure" and self.profile.roles.get("figure_caption") in self.styles
               else self.style_for("caption"))
        label = rule.label + " "
        p = self.new_par(sid, keep_next=keep_next, text=label + text)
        run = p.add_run(label)
        self._script_props(run, label, False, False, self.sr.resolve(sid), None)
        self._fld(p, kind, self.sr.resolve(sid))
        sep = self.profile.labels.caption_separator if text.strip() else ""
        self.add_text(p, sep + text, sid)
        if not text.strip():
            self.warn("CAPTION_EMPTY", f"{kind} {self.seq[kind]} has no caption text.")

    def note_lines(self, box) -> None:
        sid = self.style_for("note")
        for label, text in ((self.profile.labels.note, getattr(box, "note", "")),
                            (self.profile.labels.source, getattr(box, "source", ""))):
            if text and text.strip():
                p = self.new_par(sid, text=f"{label} {text}")
                run = p.add_run(label + ": ")
                run.bold = True
                self._script_props(run, label, True, False, self.sr.resolve(sid), None)
                self.add_text(p, text, sid)

    # ------------------------------------------------------------------ blocks
    def add_title_block(self) -> None:
        c = self.content
        placed = self._kept_names                       # the kept layout already shows these
        if c.title.strip() and "TITLE" not in placed:
            self.par("title", c.title)
        if c.subtitle.strip() and "SUBTITLE" not in placed:
            self.par("subtitle", c.subtitle)
        for a in ([] if placed & {"AUTHORS", "AUTHOR", "AUTHOR_1"} else c.authors):
            if not (a.name or a.affiliation or a.email):
                continue
            sid = self.style_for("author")
            lines = [x for x in (a.name, a.affiliation, a.email) if x.strip()]
            p = self.new_par(sid, text=" ".join(lines))
            for i, line in enumerate(lines):
                if i:
                    p.add_run().add_break()
                self.add_text(p, line, sid, force_bold=(i == 0))
        sid = self.style_for("abstract")
        if c.abstract.strip() and "ABSTRACT" not in placed:
            p = self.new_par(sid, text=self.profile.labels.abstract + " " + c.abstract)
            lab = self.profile.labels.abstract + " — "
            run = p.add_run(lab); run.bold = True
            self._script_props(run, lab, True, False, self.sr.resolve(sid), None)
            self.add_text(p, c.abstract, sid)
        if any(k.strip() for k in c.keywords) and "KEYWORDS" not in placed:
            p = self.new_par(sid, text=self.profile.labels.keywords + " " + " ".join(c.keywords))
            lab = self.profile.labels.keywords + ": "
            run = p.add_run(lab); run.bold = True
            self._script_props(run, lab, True, False, self.sr.resolve(sid), None)
            self.add_text(p, ", ".join(k.strip() for k in c.keywords if k.strip()), sid)

    def add_boxes(self, boxes, depth: int) -> None:
        for b in boxes:
            if not isinstance(b, (SectionBox, ParagraphBox)):
                self._after_heading = False
            if isinstance(b, SectionBox):
                self.add_section(b, depth)
            elif isinstance(b, ParagraphBox):
                self.add_paragraph(b)
            elif isinstance(b, ListBox):
                self.add_list(b)
            elif isinstance(b, TableBox):
                self.add_table(b)
            elif isinstance(b, FigureBox):
                self.add_figure(b)

    def add_section(self, b: SectionBox, depth: int) -> None:
        self.stats["sections"] += 1
        lvl = min(depth, 9)
        if depth > 9:
            self.warn("DEPTH_LIMIT", f"Section '{plain(b.title)}' is nested deeper than 9 levels; using Heading 9.")
        if not b.title.strip():
            self.warn("SECTION_NO_TITLE", "A section has an empty title.")
        sid = self.style_for(f"heading_{lvl}")
        p = self.new_par(sid, keep_next=False, text=b.title)
        self.add_text(p, b.title, sid)
        self._last_was_table = False
        self._after_heading = True
        self.add_boxes(b.content, depth + 1)

    def _spacer_if_table(self) -> None:
        if self._last_was_table:   # avoid two tables merging into one
            self.new_par(self.style_for("body"))
        self._last_was_table = False

    def add_paragraph(self, b: ParagraphBox) -> None:
        if not b.text.strip():
            return
        self._spacer_if_table()
        self.stats["paragraphs"] += 1
        # journal convention: the first paragraph after a heading has its own style (no first-line indent)
        first = self._after_heading and self.profile.roles.get("body_first") in self.styles
        self.par("body_first" if first else "body", b.text)
        self._after_heading = False

    def add_list(self, b: ListBox) -> None:
        if not b.items:
            return
        self._spacer_if_table()
        self.stats["lists"] += 1
        role = "list_number" if b.ordered else "list_bullet"
        sid = self.style_for(role)
        style_num = None
        if self.profile.list_mode == "template" and sid:
            n = self.sr.resolve(sid).get("num_id")
            style_num = n if n not in (None, "0") else None
        def depth_of(items: List[ListItem]) -> int:
            return 1 + max((depth_of(it.children) for it in items if it.children), default=0)

        depth = min(depth_of(b.items), 9)
        kind = "number" if b.ordered else "bullet"
        abstract = self._abstract_of(style_num) if style_num else None
        if abstract is None:
            num_id = self._add_num(self._generated_abstract(kind), restart=b.ordered)
        else:
            full = self._complete_abstract(abstract, kind, depth)
            if b.ordered:
                num_id = self._add_num(full, restart=True)
            elif full == abstract:
                num_id = int(style_num)
            else:
                if full not in self._completed_num:
                    self._completed_num[full] = self._add_num(full)
                num_id = self._completed_num[full]

        def emit(items: List[ListItem], level: int) -> None:
            for it in items:
                p = self.new_par(sid)
                ppr = self._ppr(p)
                np_ = _w("numPr"); np_.append(_w("ilvl", val=min(level, 8))); np_.append(_w("numId", val=num_id))
                ppr.append(np_)
                self._finish_ppr(p)
                self.add_text(p, it.text, sid)
                if it.children:
                    emit(it.children, level + 1)
        emit(b.items, 0)

    # -------------------------------------------------------------------- table
    def _col_widths(self, data: List[List[str]], total: int) -> List[int]:
        cols = len(data[0])
        weights = []
        for c in range(cols):
            longest = max((len(plain(row[c])) for row in data), default=1)
            longest_word = max((len(w) for row in data for w in plain(row[c]).split()), default=1)
            weights.append(max(4, min(40, longest), min(longest_word, 20)))
        s = sum(weights)
        widths = [int(total * w / s) for w in weights]
        floor = min(720, total // cols)
        widths = [max(w, floor) for w in widths]
        scale = total / sum(widths)
        widths = [int(w * scale) for w in widths]
        widths[-1] += total - sum(widths)
        return widths

    def add_table(self, b: TableBox) -> None:
        if not b.data or not b.data[0]:
            self.warn("TABLE_EMPTY", "A table has no data and was skipped.")
            return
        rule = self.profile.table
        rows, cols = len(b.data), len(b.data[0])
        self.stats["tables"] += 1
        if self._last_was_table:
            self.new_par(self.style_for("body"))
        above = rule.caption_position == "above"
        if above:
            self.caption("Table", b.caption, keep_next=True)
        elif not b.caption.strip():
            self.warn("CAPTION_EMPTY", "A table has no caption text.")
        tbl = self.doc.add_table(rows=rows, cols=cols)
        self._style_table(tbl, b, rule, rows, cols)
        self._last_was_table = True
        if not above:
            for p_el in tbl.rows[-1]._tr.iter(qn("w:p")):      # keep the last row with its caption
                ppr = p_el.get_or_add_pPr()
                if ppr.find(qn("w:keepNext")) is None:
                    ppr.append(_w("keepNext"))
                    sort_children(ppr, PPR_ORDER)
            self.caption("Table", b.caption, keep_next=False)
            self._last_was_table = False
        if b.note.strip() or b.source.strip():
            self.note_lines(b)
            self._last_was_table = False

    def _style_table(self, tbl, b: TableBox, rule, rows: int, cols: int) -> None:
        t = tbl._tbl
        pr = t.tblPr
        for tag in ("tblW", "jc", "tblLayout", "tblStyle", "tblBorders", "bidiVisual"):
            for old in pr.findall(qn(f"w:{tag}")):
                pr.remove(old)
        use_tpl = rule.borders == "template" and rule.template_style_id in self.styles
        borders = None if use_tpl else rule.borders
        if use_tpl:
            pr.append(_w("tblStyle", val=rule.template_style_id))
        elif rule.borders == "template":
            self.warn("TABLE_STYLE_NOT_FOUND",
                      f"Table style '{rule.template_style_id}' not found; using direct borders.")
            borders = "all"
        if borders in ("all", "horizontal"):
            bd = _w("tblBorders")
            names = ["top", "left", "bottom", "right", "insideH", "insideV"] if borders == "all" \
                else ["top", "bottom", "insideH"]
            for n in names:
                bd.append(_w(n, val="single", sz=4, space=0, color="000000"))
            pr.append(bd)
        total = int(self.text_width * rule.width_percent / 100)
        pr.append(_w("tblW", w=total, type="dxa"))
        pr.append(_w("jc", val=rule.alignment))
        pr.append(_w("tblLayout", type="fixed"))
        if self.rtl:
            pr.append(_w("bidiVisual"))
        sort_children(pr, TBLPR_ORDER)

        widths = self._col_widths(b.data, total)
        grid = t.find(qn("w:tblGrid"))
        for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
            gc.set(qn("w:w"), str(w))

        sid = self.style_for("table_text")
        resolved = self.sr.resolve(sid)
        size = rule.cell_font_pt
        if cols >= rule.wide_table_columns:
            size = rule.wide_table_font_pt
            self.warn("TABLE_WIDE", f"A table with {cols} columns uses {size} pt text to fit the page.")
        hdr = max(0, min(b.header_rows, rows))
        for ri, row in enumerate(tbl.rows):
            trpr = row._tr.get_or_add_trPr()
            trpr.append(_w("cantSplit"))
            if ri < hdr and rule.repeat_header:
                trpr.append(_w("tblHeader"))
            for ci, cell in enumerate(row.cells):
                tcpr = cell._tc.get_or_add_tcPr()
                for old in tcpr.findall(qn("w:tcW")):
                    tcpr.remove(old)
                tcpr.append(_w("tcW", w=widths[ci], type="dxa"))
                if ri < hdr and rule.header_shading:
                    tcpr.append(_w("shd", val="clear", color="auto", fill=rule.header_shading))
                sort_children(tcpr, TCPR_ORDER)
                p = cell.paragraphs[0]
                p.style = self._style_obj(sid)
                ppr = self._ppr(p)
                self._direction(ppr, sid, plain(b.data[ri][ci]))
                align = None
                if ri < hdr:
                    align = "center"
                elif rule.cell_alignment != "auto":
                    align = rule.cell_alignment
                elif NUMERIC.match(plain(b.data[ri][ci])):
                    align = "center"
                if align:
                    ppr.append(_w("jc", val=align))
                sort_children(ppr, PPR_ORDER)
                self.add_text(p, b.data[ri][ci], sid, size_override=size,
                              force_bold=(ri < hdr and rule.header_bold))

    # ------------------------------------------------------------------- figure
    def add_figure(self, b: FigureBox) -> None:
        self._spacer_if_table()
        rule = self.profile.figure
        self.stats["figures"] += 1
        above = rule.caption_position == "above"
        path = self.media_path(b.asset_id) if b.asset_id else None
        if above:
            self.caption("Figure", b.caption, keep_next=True)
        sid = self.style_for("figure")
        p = self.new_par(sid, keep_next=(not above), align=rule.alignment)
        # no first-line indent from body styles
        ppr = self._ppr(p)
        ppr.append(_w("ind", left=0, firstLine=0))
        sort_children(ppr, PPR_ORDER)
        if path is None:
            self.warn("FIGURE_MISSING", "A figure has no image; a placeholder line was inserted.")
            p.add_run("[image missing]")
        else:
            try:
                with Image.open(path) as im:
                    wpx, hpx = im.size
                    dpi = im.info.get("dpi", (96, 96))[0] or 96
                nat_w = wpx / dpi * 2.54
                nat_h = hpx / dpi * 2.54
                max_w = self.text_width * rule.max_width_percent / 100 / TWIPS_PER_CM
                # leave room for the caption line(s) on the same page
                max_h = min(rule.max_height_cm, self.text_height / TWIPS_PER_CM * 0.85)
                scale = min(1.0, max_w / nat_w, max_h / nat_h)
                p.add_run().add_picture(path, width=Cm(nat_w * scale), height=Cm(nat_h * scale))
            except Exception as e:   # corrupt image must not kill generation
                self.warn("FIGURE_UNREADABLE", f"Image could not be inserted: {e}")
                p.add_run("[image unreadable]")
        if not above:
            self.caption("Figure", b.caption, keep_next=False)
        if b.source.strip():
            self.note_lines(b)

    # --------------------------------------------------------------------- run
    # relationship types that only the (cleared) body could have used
    _BODY_ONLY_RELS = ("/image", "/hyperlink", "/oleObject", "/package", "/chart", "/diagramData",
                       "/diagramLayout", "/diagramQuickStyle", "/diagramColors", "/video", "/audio", "/media")

    def _drop_unused_body_relationships(self) -> None:
        """The template's sample body is removed, but its images, charts and links stayed in the package
        (a 4 MB journal template gave 4 MB documents). Drop relationships nothing refers to any more;
        headers and footers have their own relationships and are not touched."""
        r_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
        used = {v for el in self.doc.element.iter() for k, v in el.attrib.items() if k.startswith(r_ns)}
        part = self.doc.part
        for rid, rel in list(part.rels.items()):
            if rid not in used and rel.reltype.endswith(self._BODY_ONLY_RELS):
                part.rels.pop(rid)

    def _normalize_style_order(self) -> None:
        """Templates are not always schema-ordered; Word refuses a file whose styles are not."""
        root = self.doc.styles.element
        for tag, order in (("pPr", PPR_ORDER), ("rPr", RPR_ORDER)):
            for el in root.iter(qn(f"w:{tag}")):
                sort_children(el, order)

    def add_back_matter(self) -> None:
        """Hook for subclasses (predefined designs add declarations and references). Nothing by default."""

    def build(self) -> None:
        self._apply_language_defaults()
        self._setup_heading_numbering()
        self.add_title_block()
        self.add_boxes(self.content.body, 1)
        self.add_back_matter()
        self._fill_placeholders()
        self._normalize_style_order()
        self._drop_unused_body_relationships()
        # keep the document valid even if empty: Word requires >= 1 block
        cp = self.doc.core_properties
        cp.title = plain(self.content.title) or cp.title
        names = [a.name for a in self.content.authors if a.name]
        if names:
            cp.author = ", ".join(names)
        cp.language = self.profile.language.code


def generate_docx(template_path: str, profile: FormattingProfile, content: DocumentContent,
                  media_path: Callable[[str], Optional[str]], out_path: str) -> GenerationResult:
    g = Generator(template_path, profile, content, media_path)
    g.build()
    g.doc.save(out_path)
    return GenerationResult(path=out_path, warnings=g.warnings, stats=g.stats)
