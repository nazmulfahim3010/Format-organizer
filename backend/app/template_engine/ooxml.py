"""Low-level OOXML helpers shared by the analyzer, generator and validator."""
from __future__ import annotations

from typing import Dict, List, Optional

from docx.oxml.ns import qn
from lxml import etree

from ..core.uploads import safe_xml

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
EMU_PER_CM = 360000
EMU_PER_TWIP = 635
TWIPS_PER_CM = 566.929

OFF_VALUES = {"0", "false", "off", "none"}


def on(el) -> bool:
    """A boolean OOXML toggle element: present and not explicitly off."""
    if el is None:
        return False
    v = el.get(qn("w:val"))
    return v is None or v.lower() not in OFF_VALUES


def tw_to_pt(v: Optional[str]) -> Optional[float]:
    return None if v is None else round(int(v) / 20, 2)


def _theme_part(doc):
    try:
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
        return doc.part.part_related_by(RT.THEME)
    except Exception:
        for part in doc.part.package.iter_parts():
            if "/theme/" in str(part.partname):
                return part
    return None


def theme_fonts(doc) -> Dict[str, object]:
    """Theme font scheme.

    {'major': latin, 'minor': latin, 'major_ea', 'minor_ea', 'major_cs', 'minor_cs',
     'major_scripts': {'Beng': 'Vrinda', ...}, 'minor_scripts': {...}}. Empty typefaces are omitted.
    """
    out: Dict[str, object] = {"major_scripts": {}, "minor_scripts": {}}
    part = _theme_part(doc)
    if part is None:
        return out
    try:
        root = safe_xml(part.blob)          # the template is user content
    except Exception:  # theme is optional; never fail analysis because of it
        return out
    for kind in ("major", "minor"):
        node = root.find(f".//{{{A_NS}}}{kind}Font")
        if node is None:
            continue
        for tag, key in (("latin", kind), ("ea", f"{kind}_ea"), ("cs", f"{kind}_cs")):
            el = node.find(f"{{{A_NS}}}{tag}")
            if el is not None and el.get("typeface"):
                out[key] = el.get("typeface")
        out[f"{kind}_scripts"] = {f.get("script"): f.get("typeface")
                                  for f in node.findall(f"{{{A_NS}}}font")
                                  if f.get("script") and f.get("typeface")}
    return out


# rFonts slot -> theme attribute. Note the spec spells the complex-script one "cstheme".
FONT_SLOTS = {"ascii": "asciiTheme", "hAnsi": "hAnsiTheme", "eastAsia": "eastAsiaTheme", "cs": "cstheme"}
_THEME_KEY = {"majorAscii": "major", "majorHAnsi": "major", "minorAscii": "minor", "minorHAnsi": "minor",
              "majorEastAsia": "major_ea", "minorEastAsia": "minor_ea",
              "majorBidi": "major_cs", "minorBidi": "minor_cs"}


class StyleResolver:
    """Resolves effective paragraph/run properties through basedOn + docDefaults."""

    def __init__(self, doc):
        self.styles_el = doc.styles.element
        self.by_id: Dict[str, etree._Element] = {
            s.get(qn("w:styleId")): s for s in self.styles_el.findall(qn("w:style"))
        }
        self.theme = theme_fonts(doc)
        dd = self.styles_el.find(qn("w:docDefaults"))
        self.dd_rpr = dd.find(f"{qn('w:rPrDefault')}/{qn('w:rPr')}") if dd is not None else None
        self.dd_ppr = dd.find(f"{qn('w:pPrDefault')}/{qn('w:pPr')}") if dd is not None else None
        self.default_par_id = next(
            (sid for sid, s in self.by_id.items()
             if s.get(qn("w:type")) == "paragraph" and s.get(qn("w:default")) == "1"),
            None,
        )

    def _based_on(self, sid: str) -> Optional[str]:
        b = self.by_id[sid].find(qn("w:basedOn"))
        return b.get(qn("w:val")) if b is not None else None

    def chain(self, style_id: Optional[str]):
        seen, out = set(), []
        sid = style_id
        while sid and sid in self.by_id and sid not in seen:
            seen.add(sid)
            out.append(self.by_id[sid])
            sid = self._based_on(sid)
        return list(reversed(out))  # base-most first

    def cycles(self) -> List[str]:
        """Style ids whose basedOn chain loops back on itself."""
        bad = []
        for start in self.by_id:
            seen, sid = set(), start
            while sid and sid in self.by_id:
                if sid in seen:
                    bad.append(start)
                    break
                seen.add(sid)
                sid = self._based_on(sid)
        return bad

    def theme_font(self, theme_attr: str) -> Optional[str]:
        v = self.theme.get(_THEME_KEY.get(theme_attr, ""))
        return v if isinstance(v, str) else None

    # -- property application -------------------------------------------------
    def _rpr(self, p: dict, rpr) -> None:
        if rpr is None:
            return
        f = rpr.find(qn("w:rFonts"))
        if f is not None:
            # per slot, last writer wins; inside one element a theme attribute beats the explicit name
            for slot, theme_attr in FONT_SLOTS.items():
                th, explicit = f.get(qn(f"w:{theme_attr}")), f.get(qn(f"w:{slot}"))
                if th:
                    p[f"font_{slot}_theme"] = th
                    p[f"font_{slot}"] = self.theme_font(th)
                elif explicit:
                    p.pop(f"font_{slot}_theme", None)
                    p[f"font_{slot}"] = explicit
        for tag, key, conv in (("w:sz", "size_pt", lambda x: int(x) / 2),
                               ("w:szCs", "size_cs_pt", lambda x: int(x) / 2)):
            el = rpr.find(qn(tag))
            if el is not None and el.get(qn("w:val")):
                p[key] = conv(el.get(qn("w:val")))
        for tag, key in (("w:b", "bold"), ("w:i", "italic"), ("w:caps", "caps"),
                         ("w:bCs", "bold_cs"), ("w:iCs", "italic_cs"), ("w:rtl", "rtl")):
            el = rpr.find(qn(tag))
            if el is not None:
                p[key] = on(el)
        col = rpr.find(qn("w:color"))
        if col is not None and col.get(qn("w:val")):
            p["color"] = col.get(qn("w:val"))
        lang = rpr.find(qn("w:lang"))
        if lang is not None:
            for k in ("val", "bidi", "eastAsia"):
                v = lang.get(qn(f"w:{k}"))
                if v:
                    p[f"lang_{k}"] = v

    def _ppr(self, p: dict, ppr) -> None:
        if ppr is None:
            return
        jc = ppr.find(qn("w:jc"))
        if jc is not None:
            m = {"both": "justify", "start": "left", "end": "right", "distribute": "justify"}
            v = jc.get(qn("w:val"))
            p["align"] = m.get(v, v)
        sp = ppr.find(qn("w:spacing"))
        if sp is not None:
            if sp.get(qn("w:before")) is not None:
                p["space_before_pt"] = tw_to_pt(sp.get(qn("w:before")))
            if sp.get(qn("w:after")) is not None:
                p["space_after_pt"] = tw_to_pt(sp.get(qn("w:after")))
            if sp.get(qn("w:line")) is not None:
                rule = sp.get(qn("w:lineRule")) or "auto"
                line = int(sp.get(qn("w:line")))
                p["line_spacing"] = round(line / 240, 2) if rule == "auto" else round(line / 20, 2)
                p["line_rule"] = rule
        ind = ppr.find(qn("w:ind"))
        if ind is not None:
            for src, key in (("left", "left_indent_pt"), ("start", "left_indent_pt"),
                             ("right", "right_indent_pt"), ("end", "right_indent_pt")):
                if ind.get(qn(f"w:{src}")) is not None:
                    p[key] = tw_to_pt(ind.get(qn(f"w:{src}")))
            # firstLine and hanging are one setting: whichever is written last replaces the other
            for src, key, other in (("firstLine", "first_line_pt", "hanging_pt"),
                                    ("hanging", "hanging_pt", "first_line_pt")):
                if ind.get(qn(f"w:{src}")) is not None:
                    p[key] = tw_to_pt(ind.get(qn(f"w:{src}")))
                    p.pop(other, None)
        ol = ppr.find(qn("w:outlineLvl"))
        if ol is not None and ol.get(qn("w:val")) is not None:
            p["outline_level"] = int(ol.get(qn("w:val")))
        np_ = ppr.find(qn("w:numPr"))
        if np_ is not None:
            nid = np_.find(qn("w:numId"))
            lvl = np_.find(qn("w:ilvl"))
            if nid is not None and nid.get(qn("w:val")) == "0":      # numId 0 = "no numbering"
                p.pop("num_id", None)
                p.pop("num_ilvl", None)
            else:
                if nid is not None:
                    p["num_id"] = nid.get(qn("w:val"))
                p["num_ilvl"] = int(lvl.get(qn("w:val"))) if lvl is not None else p.get("num_ilvl", 0)
        if on(ppr.find(qn("w:keepNext"))):
            p["keep_next"] = True
        bidi = ppr.find(qn("w:bidi"))
        if bidi is not None:
            p["bidi"] = on(bidi)

    def resolve(self, style_id: Optional[str]) -> dict:
        p: dict = {}
        self._rpr(p, self.dd_rpr)
        self._ppr(p, self.dd_ppr)
        for el in self.chain(style_id):
            self._ppr(p, el.find(qn("w:pPr")))
            self._rpr(p, el.find(qn("w:rPr")))
        p["font"] = p.get("font_ascii") or p.get("font_hAnsi")
        return p


def page_text_width_twips(sect_pr) -> int:
    """Usable width of ONE text column in twips (handles multi-column layouts)."""
    pg = sect_pr.find(qn("w:pgSz"))
    mar = sect_pr.find(qn("w:pgMar"))
    w = int(pg.get(qn("w:w"))) if pg is not None and pg.get(qn("w:w")) else 11906
    left = int(mar.get(qn("w:left"))) if mar is not None and mar.get(qn("w:left")) else 1440
    right = int(mar.get(qn("w:right"))) if mar is not None and mar.get(qn("w:right")) else 1440
    gutter = int(mar.get(qn("w:gutter"))) if mar is not None and mar.get(qn("w:gutter")) else 0
    usable = w - left - right - gutter
    cols = sect_pr.find(qn("w:cols"))
    n = int(cols.get(qn("w:num"))) if cols is not None and cols.get(qn("w:num")) else 1
    space = int(cols.get(qn("w:space"))) if cols is not None and cols.get(qn("w:space")) else 720
    explicit = [int(c.get(qn("w:w"))) for c in cols.findall(qn("w:col")) if c.get(qn("w:w"))] \
        if cols is not None and cols.get(qn("w:equalWidth")) in ("0", "false") else []
    if explicit:
        usable = min(explicit)            # unequal columns: content must fit the narrowest one
    elif n > 1:
        usable = int((usable - space * (n - 1)) / n)
    return max(usable, 1440)


def page_text_height_twips(sect_pr) -> int:
    """Usable text height of a page in twips."""
    pg = sect_pr.find(qn("w:pgSz"))
    mar = sect_pr.find(qn("w:pgMar"))
    h = int(pg.get(qn("w:h"))) if pg is not None and pg.get(qn("w:h")) else 16838

    def m(attr: str) -> int:
        v = mar.get(qn(f"w:{attr}")) if mar is not None else None
        return abs(int(v)) if v else 1440           # negative margins mean "exact"; size is the same
    return max(h - m("top") - m("bottom"), 1440)


def has_field(el, name: str) -> bool:
    """True if the element contains a field whose instruction starts with `name`."""
    for it in el.iter(qn("w:instrText")):
        if (it.text or "").strip().upper().startswith(name.upper()):
            return True
    for fs in el.iter(qn("w:fldSimple")):
        if (fs.get(qn("w:instr")) or "").strip().upper().startswith(name.upper()):
            return True
    return False


def paragraph_text(p_el) -> str:
    return "".join(t.text or "" for t in p_el.iter(qn("w:t")))


# Unicode blocks of complex / RTL / East-Asian scripts -------------------------
def script_of(text: str) -> str:
    """'rtl' | 'complex' | 'east_asian' | 'latin' for a piece of text."""
    kind = "latin"
    for ch in text:
        o = ord(ch)
        if 0x0590 <= o <= 0x08FF or 0xFB1D <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
            return "rtl"  # Hebrew, Arabic, Syriac, Thaana, N'Ko ...
        if 0x0900 <= o <= 0x0DFF or 0x0E00 <= o <= 0x0EFF or 0x0F00 <= o <= 0x0FFF or 0x1000 <= o <= 0x109F or 0x1780 <= o <= 0x17FF:
            kind = "complex"  # Devanagari, Bengali, Gurmukhi, Tamil, Thai, Tibetan, Myanmar, Khmer...
        elif (0x2E80 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF):
            if kind == "latin":
                kind = "east_asian"
    return kind


# script detection -------------------------------------------------------------
# (first, last, ISO 15924) for the scripts SmartDoc cares about; anything else alphabetic counts as Latin
_SCRIPT_RANGES = [
    (0x0590, 0x05FF, "Hebr"), (0xFB1D, 0xFB4F, "Hebr"),
    (0x0600, 0x06FF, "Arab"), (0x0750, 0x077F, "Arab"), (0x08A0, 0x08FF, "Arab"),
    (0xFB50, 0xFDFF, "Arab"), (0xFE70, 0xFEFF, "Arab"),
    (0x0900, 0x097F, "Deva"), (0x0980, 0x09FF, "Beng"), (0x0A00, 0x0A7F, "Guru"), (0x0A80, 0x0AFF, "Gujr"),
    (0x0B00, 0x0B7F, "Orya"), (0x0B80, 0x0BFF, "Taml"), (0x0C00, 0x0C7F, "Telu"), (0x0C80, 0x0CFF, "Knda"),
    (0x0D00, 0x0D7F, "Mlym"), (0x0D80, 0x0DFF, "Sinh"), (0x0E00, 0x0E7F, "Thai"), (0x0E80, 0x0EFF, "Laoo"),
    (0x0F00, 0x0FFF, "Tibt"), (0x1000, 0x109F, "Mymr"), (0x1780, 0x17FF, "Khmr"),
    (0x0400, 0x04FF, "Cyrl"), (0x0370, 0x03FF, "Grek"),
    (0x3040, 0x30FF, "Jpan"), (0xAC00, 0xD7AF, "Hang"), (0x4E00, 0x9FFF, "Hani"), (0x3400, 0x4DBF, "Hani"),
]
RTL_SCRIPTS = {"Arab", "Hebr"}
SCRIPT_LANG = {"Arab": "ar", "Hebr": "he", "Deva": "hi", "Beng": "bn", "Guru": "pa", "Gujr": "gu", "Orya": "or",
               "Taml": "ta", "Telu": "te", "Knda": "kn", "Mlym": "ml", "Sinh": "si", "Thai": "th", "Laoo": "lo",
               "Tibt": "bo", "Mymr": "my", "Khmr": "km", "Cyrl": "ru", "Grek": "el", "Jpan": "ja", "Hang": "ko",
               "Hani": "zh"}


def dominant_script(text: str) -> Optional[str]:
    """ISO 15924 code of the most frequent script among letters ('Latn' for Latin), None if no letters."""
    counts: Dict[str, int] = {}
    for ch in text:
        if not ch.isalpha():
            continue
        o = ord(ch)
        sc = next((code for lo, hi, code in _SCRIPT_RANGES if lo <= o <= hi), "Latn")
        counts[sc] = counts.get(sc, 0) + 1
    if not counts:
        return None
    if "Jpan" in counts and "Hani" in counts:          # kana + kanji is Japanese
        counts["Jpan"] += counts.pop("Hani")
    return max(counts, key=counts.get)
