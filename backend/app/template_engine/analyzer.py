"""Template analyzer: reads ANY .docx and reports what it found.

No AI. Output is a plain dict (JSON-serialisable):
  page, styles, suggested_roles, role_evidence, health, header_footer, tables, figures, language
Roles are detected by outline level / style id / exact style names in several
languages (with native digits), never by English style names alone.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Dict, List, Optional, Tuple

from docx import Document
from docx.oxml.ns import qn

from ..schemas.profile import FigureRule, FormattingProfile, Labels, LanguageSettings, TableRule, rule_paths
from ..core.placeholders import names_in
from .ooxml import (EMU_PER_CM, RTL_SCRIPTS, SCRIPT_LANG, StyleResolver, dominant_script, has_field, on,
                    paragraph_text, script_of)

# Exact style names (case-folded) per role, several languages. Style IDs and
# outline levels are checked first; names are the fallback.
KEYWORDS = {
    "title": ["title", "titel", "titre", "título", "titulo", "titolo", "заголовок документа", "标题", "عنوان المستند", "শিরোনাম"],
    "subtitle": ["subtitle", "untertitel", "sous-titre", "subtítulo", "sottotitolo", "副标题", "উপশিরোনাম"],
    "caption": ["caption", "beschriftung", "légende", "leyenda", "didascalia", "подпись", "题注", "تسمية توضيحية", "ক্যাপশন"],
    "abstract": ["abstract", "zusammenfassung", "résumé", "resumen", "riassunto", "аннотация", "摘要", "ملخص", "সারসংক্ষেপ", "সারাংশ"],
    "author": ["author", "autor", "auteur", "autore", "автор", "作者", "مؤلف", "লেখক"],
    "quote": ["quote", "zitat", "citation", "cita", "citazione", "цитата", "引用", "اقتباس", "উদ্ধৃতি"],
    # the first paragraph after a heading (journal convention: no first-line indent). Not Word's
    # "Body Text First Indent", which is a first-line indent style.
    "body_first": ["body first", "first paragraph", "body text first", "first para"],
    "list_bullet": ["list bullet", "aufzählungszeichen", "liste à puces", "viñetas", "elenco puntato", "项目符号", "বুলেট"],
    "list_number": ["list number", "listennummer", "liste numérotée", "lista numerada", "elenco numerato", "编号", "সংখ্যা তালিকা"],
    "note": ["table note", "figure note", "note", "source", "quelle", "fuente", "tablenote"],
    "table_text": ["table text", "tabletext", "table body", "tablecontents", "table contents"],
    "figure": ["figure", "abbildung", "figura", "image", "picture"],
}
ID_HINTS = {
    "title": ["Title"], "subtitle": ["Subtitle"], "caption": ["Caption"],
    "abstract": ["Abstract"], "author": ["Author"], "quote": ["Quote"],
    "list_bullet": ["ListBullet"], "list_number": ["ListNumber"],
    "table_text": ["TableText", "TableContents", "TableParagraph"],
    "figure": ["Figure"], "note": ["TableNote", "FigureNote", "Source"],
}
# "Heading 1" in other Word UI languages; the level may be written in any script's digits
HEADING_WORDS = ["heading", "überschrift", "titre", "título", "titulo", "titolo", "kop", "nagłówek",
                 "заголовок", "标题", "標題", "見出し", "제목", "عنوان", "כותרת", "শিরোনাম", "शीर्षक",
                 "başlık", "rubrik", "otsikko", "overskrift", "nadpis", "cím"]
HEADING_NAME = re.compile(r"^(?:%s)\s*(\d+)$" % "|".join(map(re.escape, HEADING_WORDS)))
# "IJPCR Heading 2", "Thesis heading 1": a heading word + level at the end of a longer name
HEADING_NAME_SUFFIX = re.compile(r"(?:^|[\s_\-])(?:%s)\s*(\d+)$" % "|".join(map(re.escape, HEADING_WORDS)))
PLACEHOLDER = re.compile(r"\{\{\s*[^{}\s][^{}]{0,40}\}\}|«[^«»]{1,40}»")
CAPTION_LABEL = re.compile(
    r"^\s*(table|tab\.|figure|fig\.|tabelle|abbildung|tableau|figura|tabla|表|图|圖|"
    r"চিত্র|সারণি|ছক|টেবিল|الشكل|شكل|الجدول|جدول|рисунок|таблица)\b", re.I)
SEPARATORS = ":.-–—"

# Default caption/heading labels per language (used when the template shows none)
LANGUAGE_LABELS = {
    "en": dict(abstract="Abstract", keywords="Keywords", table="Table", figure="Figure", source="Source", note="Note"),
    "bn": dict(abstract="সারসংক্ষেপ", keywords="মূলশব্দ", table="সারণি", figure="চিত্র", source="উৎস", note="টীকা"),
    "ar": dict(abstract="الملخص", keywords="الكلمات المفتاحية", table="جدول", figure="شكل", source="المصدر", note="ملاحظة"),
    "hi": dict(abstract="सारांश", keywords="मुख्य शब्द", table="तालिका", figure="चित्र", source="स्रोत", note="टिप्पणी"),
    "fr": dict(abstract="Résumé", keywords="Mots-clés", table="Tableau", figure="Figure", source="Source", note="Remarque"),
    "de": dict(abstract="Zusammenfassung", keywords="Schlüsselwörter", table="Tabelle", figure="Abbildung", source="Quelle", note="Hinweis"),
    "es": dict(abstract="Resumen", keywords="Palabras clave", table="Tabla", figure="Figura", source="Fuente", note="Nota"),
}
# languages whose own digits are in everyday use in documents (the user can switch it off)
NATIVE_DIGIT_LANGS = {"bn", "as", "ar", "fa", "ur", "ps", "hi", "mr", "ne"}
TEMPLATE_ORIGIN = {"outline_level", "style_id", "style_name", "default_style"}


def _name(el) -> str:
    n = el.find(qn("w:name"))
    return n.get(qn("w:val")) if n is not None else ""


def heading_level_from_name(name: str, anywhere: bool = False) -> Optional[int]:
    """'Heading 2' / 'শিরোনাম ২' -> 2. With anywhere=True also 'IJPCR Heading 2' (custom prefix)."""
    text = (name or "").strip().casefold()
    m = (HEADING_NAME_SUFFIX.search(text) if anywhere else HEADING_NAME.match(text))
    if not m:
        return None
    try:
        lvl = int("".join(str(unicodedata.digit(c)) for c in m.group(1)))
    except (TypeError, ValueError):
        return None
    return lvl if 1 <= lvl <= 9 else None


def analyze_template(path: str) -> dict:
    doc = Document(path)
    sr = StyleResolver(doc)
    body = doc.element.body
    paragraphs = list(body.iter(qn("w:p")))
    body_pars = [p for p in body.findall(qn("w:p"))]

    # --- usage counts ------------------------------------------------------
    usage: Counter = Counter()
    direct_runs = total_runs = 0
    for p in paragraphs:
        ps = p.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
        sid = ps.get(qn("w:val")) if ps is not None else sr.default_par_id
        if paragraph_text(p).strip():
            usage[sid] += 1
        for r in p.findall(qn("w:r")):
            if not "".join(t.text or "" for t in r.iter(qn("w:t"))).strip():
                continue
            total_runs += 1
            rpr = r.find(qn("w:rPr"))
            if rpr is not None and any(rpr.find(qn(t)) is not None for t in
                                       ("w:rFonts", "w:sz", "w:color", "w:b", "w:i")):
                direct_runs += 1

    # --- styles --------------------------------------------------------------
    styles: List[dict] = []
    for sid, el in sr.by_id.items():
        kind = el.get(qn("w:type"))
        if kind not in ("paragraph", "character", "table", "numbering"):
            continue
        res = sr.resolve(sid) if kind in ("paragraph", "character") else {}
        b = el.find(qn("w:basedOn"))
        styles.append({
            "id": sid, "name": _name(el), "type": kind,
            "based_on": b.get(qn("w:val")) if b is not None else None,
            "default": el.get(qn("w:default")) == "1",
            "builtin_hidden": el.find(qn("w:semiHidden")) is not None,
            "quick_style": el.find(qn("w:qFormat")) is not None,
            "used": usage.get(sid, 0),
            "outline_level": res.get("outline_level"),
            "resolved": {k: v for k, v in res.items()
                         if k in ("font", "font_cs", "font_eastAsia", "size_pt", "size_cs_pt", "bold", "italic",
                                  "bold_cs", "italic_cs", "rtl", "color", "align", "space_before_pt",
                                  "space_after_pt", "line_spacing", "left_indent_pt", "right_indent_pt",
                                  "first_line_pt", "hanging_pt", "num_id", "num_ilvl", "bidi", "keep_next")},
        })

    roles, evidence = _suggest_roles(styles, sr)
    num_ids = _num_ids(doc)

    page = _page(doc)
    header_footer = _header_footer(doc)
    tables = _tables(body, sr, roles)
    figures = _figures(body, roles)
    language = _language(sr, body, page)

    health = _health(doc, sr, styles, roles, usage, direct_runs, total_runs, page,
                     language, body, num_ids)

    return {
        "page": page,
        "styles": styles,
        "suggested_roles": roles,
        "role_evidence": evidence,
        "header_footer": header_footer,
        "tables": tables,
        "figures": figures,
        "language": language,
        "heading_numbering_in_template": _headings_numbered(roles, sr, num_ids),
        "placeholders": _placeholders(doc),
        "stats": {
            "paragraphs": len(body_pars),
            "tables": len(doc.tables),
            "runs_with_direct_formatting": direct_runs,
            "runs_total": total_runs,
            "sections": len(doc.sections),
        },
        "health": health,
    }


# ---------------------------------------------------------------------------
def _suggest_roles(styles: List[dict], sr: StyleResolver) -> Tuple[Dict[str, str], Dict[str, dict]]:
    paras = [s for s in styles if s["type"] == "paragraph"]
    roles: Dict[str, str] = {}
    evidence: Dict[str, dict] = {}

    def assign(role: str, sid: str, by: str) -> None:
        roles[role] = sid
        evidence[role] = {"style_id": sid, "by": by}

    # headings: style id / localized name / custom-prefixed name / outline level. A style the template's
    # own sample content USES beats an unused built-in (real journal templates keep Word's unused
    # Heading 1..9 next to their own "Journal Heading 1..3").
    for lvl in range(1, 10):
        cands = []
        for s in paras:
            if s["id"].upper().startswith("TOC"):
                continue
            score, by = 0.0, None
            if s["outline_level"] == lvl - 1:
                score, by = 4, "outline_level"
            if re.fullmatch(rf"(?i)heading\s?{lvl}", s["id"]):
                score, by = score + 5, "style_id"
            elif heading_level_from_name(s["name"]) == lvl:
                score, by = score + 5, "style_name"
            elif heading_level_from_name(s["name"], anywhere=True) == lvl:
                score, by = score + 4, "style_name"
            if score:
                score += (3 if s["used"] else 0) + min(s["used"], 3) * 0.1 + (0.5 if s["quick_style"] else 0)
                cands.append((score, s["id"], by))
        if cands:
            _, sid, by = max(cands)
            assign(f"heading_{lvl}", sid, by)
    heading_ids = set(roles.values())

    free = [s for s in paras if s["id"] not in heading_ids]

    def contained_role(s: dict) -> Optional[str]:
        """The role whose keyword is the longest whole-word part of the style name ('Journal Figure
        Caption' -> caption, not figure)."""
        nm = f" {(s['name'] or '').strip().casefold()} "
        if "indent" in nm:
            return None
        best, length = None, 0
        for role, kws in KEYWORDS.items():
            for k in kws:
                if f" {k} " in nm and len(k) > length:
                    best, length = role, len(k)
        return best

    def pick(role: str) -> Optional[Tuple[str, str]]:
        """Exact id / exact name match, or (only for styles the template uses) a name that contains
        the role's keyword. Used styles win over unused ones; exact beats contained."""
        cands = []
        hints = {h.casefold() for h in ID_HINTS.get(role, [])}
        kws = KEYWORDS.get(role, [])
        for s in free:
            nm = (s["name"] or "").strip().casefold()
            if s["id"].casefold() in hints:
                cands.append((s["used"] > 0, 2, s["used"], s["id"], "style_id"))
            elif any(nm == k or nm == k.replace(" ", "") for k in kws):
                cands.append((s["used"] > 0, 2, s["used"], s["id"], "style_name"))
            elif s["used"] and contained_role(s) == role:
                cands.append((True, 1, s["used"], s["id"], "style_name"))
        if not cands:
            return None
        best = max(cands, key=lambda c: c[:3])
        return best[3], best[4]

    for role in ("title", "subtitle", "caption", "abstract", "author", "quote", "body_first",
                 "list_bullet", "list_number", "table_text", "figure", "note"):
        found = pick(role)
        if found:
            assign(role, *found)

    # body: a real Body Text style when used, else the most-used other paragraph style, else the default
    taken = set(roles.values())
    body = next(((s["id"], "style_id") for s in paras
                 if s["id"].casefold() in ("bodytext", "textbody", "bodytext1") and s["used"] > 0), None)
    if body is None:      # a used custom "... Body Text" style (journal templates)
        named = sorted((s for s in paras if s["used"] and s["id"] not in taken
                        and " body text " in f" {(s['name'] or '').casefold()} "
                        and "first" not in (s["name"] or "").casefold()), key=lambda s: -s["used"])
        if named:
            body = (named[0]["id"], "style_name")
    if body is None:
        ranked = sorted((s for s in paras if s["id"] not in taken), key=lambda s: -s["used"])
        if ranked and ranked[0]["used"] > 0:
            by = "default_style" if ranked[0]["id"] == sr.default_par_id else "usage"
            body = (ranked[0]["id"], by)
        elif sr.default_par_id:
            body = (sr.default_par_id, "default_style")
    if body:
        assign("body", *body)
    return roles, evidence


def _num_ids(doc) -> set:
    try:
        numbering = doc.part.numbering_part.element
    except Exception:
        return set()
    return {n.get(qn("w:numId")) for n in numbering.findall(qn("w:num"))}


def _cm(v) -> Optional[float]:
    return round(v / EMU_PER_CM, 2) if v is not None else None


def _page(doc) -> dict:
    sect = doc.sections[-1]
    sp = sect._sectPr
    cols = sp.find(qn("w:cols"))
    ncols = int(cols.get(qn("w:num"))) if cols is not None and cols.get(qn("w:num")) else 1
    space = cols.get(qn("w:space")) if cols is not None else None
    pgnum = sp.find(qn("w:pgNumType"))
    return {
        "width_cm": _cm(sect.page_width), "height_cm": _cm(sect.page_height),
        "orientation": "landscape" if sect.orientation == 1 else "portrait",
        "margins_cm": {"top": _cm(sect.top_margin), "bottom": _cm(sect.bottom_margin),
                       "left": _cm(sect.left_margin), "right": _cm(sect.right_margin)},
        "gutter_cm": _cm(sect.gutter),
        "header_distance_cm": _cm(sect.header_distance), "footer_distance_cm": _cm(sect.footer_distance),
        "columns": ncols,
        "column_space_cm": round(int(space) / 566.929, 2) if space else None,
        "different_first_page": bool(sect.different_first_page_header_footer),
        "rtl_section": on(sp.find(qn("w:bidi"))),
        "page_number_format": (pgnum.get(qn("w:fmt")) if pgnum is not None else None) or "decimal",
        "page_number_start": int(pgnum.get(qn("w:start"))) if pgnum is not None and pgnum.get(qn("w:start")) else None,
    }


def _header_footer(doc) -> dict:
    sect = doc.sections[-1]
    sp = sect._sectPr

    def txt(part) -> str:
        try:
            return " | ".join(p.text for p in part.paragraphs if p.text.strip())
        except Exception:
            return ""

    def present(tag: str) -> set:
        return {r.get(qn("w:type")) for r in sp.findall(qn(f"w:{tag}"))}

    hdr = {"default": sect.header, "first": sect.first_page_header, "even": sect.even_page_header}
    ftr = {"default": sect.footer, "first": sect.first_page_footer, "even": sect.even_page_footer}
    hkinds, fkinds = present("headerReference"), present("footerReference")
    headers = {k: txt(v) for k, v in hdr.items() if k in hkinds}
    footers = {k: txt(v) for k, v in ftr.items() if k in fkinds}

    def any_field(parts: dict, kinds: set) -> bool:
        return any(has_field(v._element, "PAGE") for k, v in parts.items() if k in kinds)

    settings = doc.settings.element
    return {
        "header_text": headers.get("default", ""), "footer_text": footers.get("default", ""),
        "kinds": headers, "footer_kinds": footers,
        "even_and_odd": on(settings.find(qn("w:evenAndOddHeaders"))),
        "footer_has_page_number": any_field(ftr, fkinds),
        "header_has_page_number": any_field(hdr, hkinds),
        "header_has_image": any(bool(list(v._element.iter(qn("w:drawing")))) for k, v in hdr.items() if k in hkinds),
        "footer_has_image": any(bool(list(v._element.iter(qn("w:drawing")))) for k, v in ftr.items() if k in fkinds),
    }


def _is_caption(sib, kind_label: str, roles: Dict[str, str]) -> bool:
    if sib is None or sib.tag != qn("w:p"):
        return False
    ps = sib.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
    if ps is not None and ps.get(qn("w:val")) == roles.get("caption"):
        return True
    return has_field(sib, f"SEQ {kind_label}") or bool(CAPTION_LABEL.match(paragraph_text(sib)))


def caption_parts(text: str) -> Tuple[Optional[str], Optional[str]]:
    """'Table 1: Results' -> ('Table', ': ');  'চিত্র ১: কাঠামো' -> ('চিত্র', ': ')."""
    m = re.match(r"^\s*(\D+?)\s*(\d+(?:[.\-]\d+)*)(.*)$", text)
    if not m:
        return None, None
    label, rest = m.group(1).strip(), m.group(3)
    if not label or len(label) > 30 or len(label.split()) > 3 or ":" in label:
        return None, None
    sep_m = re.match(r"^(\s*)([%s]?)(\s*)" % re.escape(SEPARATORS), rest)
    punct = sep_m.group(2)
    sep = f"{punct} " if punct else " "
    return label, sep


def _caption(el, kind_label: str, roles: Dict[str, str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(position, label, separator) of the caption next to a table or drawing paragraph."""
    prev, nxt = el.getprevious(), el.getnext()
    above, below = _is_caption(prev, kind_label, roles), _is_caption(nxt, kind_label, roles)
    if above == below:
        return None, None, None
    cap = prev if above else nxt
    label, sep = caption_parts(paragraph_text(cap))
    return ("above" if above else "below"), label, sep


def _table_style_header_bold(sr: StyleResolver, style_id: Optional[str]) -> bool:
    for el in reversed(sr.chain(style_id)):
        for cond in el.findall(qn("w:tblStylePr")):
            if cond.get(qn("w:type")) == "firstRow":
                b = cond.find(f"{qn('w:rPr')}/{qn('w:b')}")
                if b is not None:
                    return on(b)
    return False


def _first_row_look(pr) -> bool:
    look = pr.find(qn("w:tblLook")) if pr is not None else None
    if look is None:
        return True
    if look.get(qn("w:firstRow")) is not None:
        return on(look) and look.get(qn("w:firstRow")) not in ("0", "false")
    val = look.get(qn("w:val"))
    return bool(int(val, 16) & 0x0020) if val else True


def _tables(body, sr: StyleResolver, roles) -> List[dict]:
    out = []
    jc_map = {"start": "left", "end": "right"}
    for tbl in body.findall(qn("w:tbl"))[:5]:
        pr = tbl.find(qn("w:tblPr"))
        style = pr.find(qn("w:tblStyle")) if pr is not None else None
        style_id = style.get(qn("w:val")) if style is not None else None
        jc = pr.find(qn("w:jc")) if pr is not None else None
        w = pr.find(qn("w:tblW")) if pr is not None else None
        borders = pr.find(qn("w:tblBorders")) if pr is not None else None
        rows = tbl.findall(qn("w:tr"))
        first = rows[0] if rows else None
        fill, hbold = None, False
        if first is not None:
            shd = first.find(f".//{qn('w:tcPr')}/{qn('w:shd')}")
            if shd is not None and shd.get(qn("w:fill")) not in (None, "auto"):
                fill = shd.get(qn("w:fill"))
            runs = [r for r in first.iter(qn("w:r")) if "".join(t.text or "" for t in r.iter(qn("w:t"))).strip()]
            hbold = bool(runs) and all(on(r.find(f"{qn('w:rPr')}/{qn('w:b')}")) for r in runs)
        if not hbold and _first_row_look(pr):
            hbold = _table_style_header_bold(sr, style_id)
        pos, label, sep = _caption(tbl, "Table", roles)
        align = jc.get(qn("w:val")) if jc is not None else None
        out.append({
            "style_id": style_id,
            "alignment": jc_map.get(align, align),
            "width": {"type": w.get(qn("w:type")), "value": w.get(qn("w:w"))} if w is not None else None,
            "has_direct_borders": borders is not None,
            "header_fill": fill, "header_bold": hbold,
            "rows": len(rows),
            "cols": len(tbl.findall(f"{qn('w:tblGrid')}/{qn('w:gridCol')}")),
            "caption_position": pos, "caption_label": label, "caption_separator": sep,
        })
    return out


def _figures(body, roles) -> List[dict]:
    out = []
    jc_map = {"start": "left", "end": "right"}
    for p in body.findall(qn("w:p")):
        ext = next(p.iter("{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent"), None)
        if ext is None:
            continue
        jc = p.find(f"{qn('w:pPr')}/{qn('w:jc')}")
        align = jc.get(qn("w:val")) if jc is not None else None
        pos, label, sep = _caption(p, "Figure", roles)
        out.append({
            "width_cm": round(int(ext.get("cx")) / EMU_PER_CM, 2),
            "height_cm": round(int(ext.get("cy")) / EMU_PER_CM, 2),
            "alignment": jc_map.get(align, align),
            "caption_position": pos, "caption_label": label, "caption_separator": sep,
        })
        if len(out) >= 5:
            break
    return out


def _language(sr: StyleResolver, body, page: dict) -> dict:
    text = "".join(t.text or "" for t in body.iter(qn("w:t")))[:5000]
    script = dominant_script(text)
    normal = sr.resolve(sr.default_par_id)
    lang_val = normal.get("lang_val")
    normal_bidi = bool(normal.get("bidi"))
    # python-docx and Word put bidi="ar-SA" in docDefaults of every file: it is not evidence on its own
    rtl = script in RTL_SCRIPTS or normal_bidi or page["rtl_section"]

    code, code_origin = (lang_val or "en"), ("template" if lang_val else "default")
    if script and script != "Latn" and script in SCRIPT_LANG:
        wanted = SCRIPT_LANG[script]
        if (lang_val or "").split("-")[0].lower() != wanted:
            code, code_origin = wanted, "inferred"
    elif rtl and normal.get("lang_bidi"):
        code, code_origin = normal["lang_bidi"], "template"

    def explicit(slot: str) -> Optional[str]:
        return normal.get(f"font_{slot}") if not normal.get(f"font_{slot}_theme") else None

    scripts = sr.theme.get("minor_scripts", {}) or {}
    cs_font = ea_font = None
    if script and script not in ("Latn", "Cyrl", "Grek"):
        if script in ("Hani", "Jpan", "Hang"):
            ea_font = explicit("eastAsia") or normal.get("font_eastAsia") or \
                scripts.get({"Hani": "Hans", "Jpan": "Jpan", "Hang": "Hang"}[script])
        else:
            cs_font = explicit("cs") or normal.get("font_cs") or scripts.get(script)
    elif rtl:
        cs_font = explicit("cs") or normal.get("font_cs") or scripts.get("Arab")
    return {
        "default_lang": lang_val,
        "bidi_lang": normal.get("lang_bidi"),
        "text_script": script_of(text),
        "script": script,
        "rtl": rtl,
        "normal_bidi": normal_bidi,
        "normal_cs_font": normal.get("font_cs"),
        "suggested_code": code,
        "suggested_code_origin": code_origin,
        "suggested_cs_font": cs_font,
        "suggested_ea_font": ea_font,
    }


def _placeholders(doc) -> List[dict]:
    """[{name, where: ['body'|'header'|'footer', ...]}] in order of first appearance."""
    out: Dict[str, List[str]] = {}
    parts = [("body", [doc.element.body])]
    for sec in doc.sections:
        for kind in ("header", "first_page_header", "even_page_header", "footer", "first_page_footer", "even_page_footer"):
            try:
                part = getattr(sec, kind)
                if not part.is_linked_to_previous:
                    parts.append((kind.split("_")[-1], [part._element]))
            except Exception:
                pass
    for where, els in parts:
        for name in names_in(els):
            if where not in out.setdefault(name, []):
                out[name].append(where)
    return [{"name": n, "where": w} for n, w in out.items()]


def _headings_numbered(roles: Dict[str, str], sr: StyleResolver, num_ids: set) -> bool:
    h1 = roles.get("heading_1")
    if not h1:
        return False
    nid = sr.resolve(h1).get("num_id")
    return bool(nid) and nid in num_ids


def _health(doc, sr, styles, roles, usage, direct_runs, total_runs, page,
            language, body, num_ids) -> List[dict]:
    issues: List[dict] = []

    def add(code, severity, message, hint=""):
        issues.append({"code": code, "severity": severity, "message": message, "hint": hint})

    if not any(k.startswith("heading_") for k in roles):
        add("NO_HEADING_STYLES", "warning",
            "No heading styles were found in this template.",
            "Map headings manually, or let SmartDoc create clean heading styles inside the template.")
    else:
        missing = [i for i in range(1, 4) if f"heading_{i}" not in roles]
        if missing:
            add("MISSING_HEADING_LEVELS", "info",
                f"No style found for heading level(s) {missing}. Deeper sections fall back to the lowest level found.")
    if total_runs >= 10 and direct_runs / max(total_runs, 1) > 0.3:
        add("HEAVY_DIRECT_FORMATTING", "warning",
            f"{direct_runs} of {total_runs} text runs carry direct formatting instead of styles.",
            "Style-based mapping may not reflect what you see. Check the role map against your sample.")
    if "caption" not in roles:
        add("NO_CAPTION_STYLE", "info", "No Caption style found. SmartDoc will create one.")
    if not any(s["type"] == "table" and s["id"] not in ("TableNormal",) for s in styles):
        add("NO_TABLE_STYLE", "info", "No table style found. Tables will use direct borders from the table rule.")
    if "list_bullet" not in roles or "list_number" not in roles:
        add("NO_LIST_STYLES", "info", "No list styles found. SmartDoc will generate bullet/number lists.")
    if len(doc.sections) > 1:
        add("MULTIPLE_SECTIONS", "warning",
            f"The template has {len(doc.sections)} sections. Only the last section's page setup, headers and footers are kept.")
    if page["columns"] > 1:
        add("MULTI_COLUMN", "info",
            f"{page['columns']}-column layout is preserved. Table and figure widths are computed per column.")
    if any(True for _ in body.iter(qn("w:sdt"))):
        add("CONTENT_CONTROLS", "info", "Content controls found in the body; they are removed with the sample content.")
    if any(True for _ in body.iter(qn("w:ins"))) or any(True for _ in body.iter(qn("w:del"))):
        add("TRACKED_CHANGES", "warning", "The template contains tracked changes. Accept or reject them before use.")
    if len(body.findall(qn("w:p"))) > 3 and any(usage.values()):
        add("SAMPLE_CONTENT", "info", "The template's own sample text is removed; headers, footers and styles are kept.")
    if language["script"] not in (None, "Latn", "Cyrl", "Grek", "Hani", "Jpan", "Hang") and not language["suggested_cs_font"]:
        add("NO_COMPLEX_SCRIPT_FONT", "warning",
            "The template text uses a complex script but no complex-script font is defined.",
            "Set a complex-script font in the profile (for example a Bangla or Arabic font).")
    if not _headings_numbered(roles, sr, num_ids) and "heading_1" in roles:
        add("HEADINGS_NOT_NUMBERED", "info",
            "Headings are not numbered by the template. Set heading numbering to 'auto' if you want 1, 1.1, 1.1.1.")

    inherited = []
    for role, sid in roles.items():
        if not (role in ("title", "subtitle", "caption") or role.startswith("heading_")):
            continue
        if (sr.resolve(sid).get("first_line_pt") or 0) > 0:
            own = sr.by_id[sid].find(f"{qn('w:pPr')}/{qn('w:ind')}")
            if own is None or own.get(qn("w:firstLine")) is None:
                inherited.append(sid)
    if inherited:
        add("INHERITED_FIRST_LINE_INDENT", "info",
            f"Style(s) {', '.join(sorted(set(inherited)))} inherit a first-line indent from the body style, "
            "so titles/headings/captions start indented.",
            "This is how Word will show them too. Remove the indent from those styles in the template if unwanted.")

    layout = sum(1 for _ in body.iter(qn("w:drawing"))) + sum(1 for _ in body.iter(qn("w:pict"))) \
        + sum(1 for _ in body.iter(qn("w:txbxContent")))
    body_text = " ".join(paragraph_text(p) for p in body.iter(qn("w:p")))
    if layout or PLACEHOLDER.search(body_text):
        add("BODY_LAYOUT", "warning",
            f"The template's body contains a layout ({layout} image(s)/text box(es)"
            f"{', placeholders' if PLACEHOLDER.search(body_text) else ''}), for example a first-page banner, "
            "logo or abstract box. With 'Keep the template's first-page layout' on, everything before the "
            "template's first heading is kept and its placeholders are filled; with it off, the whole body is "
            "replaced by your content.",
            "The setting is on by default when the layout has placeholders. Check the result in the preview.")
    found: List[str] = []
    parts = [("body", body)]
    for sec in doc.sections:
        for kind in ("header", "first_page_header", "even_page_header", "footer", "first_page_footer", "even_page_footer"):
            try:
                part = getattr(sec, kind)
                if not part.is_linked_to_previous:
                    parts.append((kind.split("_")[-1], part._element))
            except Exception:
                pass
    where: Dict[str, set] = {}
    for label, el in parts:
        for m in PLACEHOLDER.findall(" ".join(paragraph_text(p) for p in el.iter(qn("w:p")))):
            where.setdefault(m, set()).add(label)
    if where:
        listed = ", ".join(sorted(where)[:6]) + (" …" if len(where) > 6 else "")
        kept = sorted({w for v in where.values() for w in v} - {"body"})
        add("PLACEHOLDERS", "info",
            f"The template contains placeholders: {listed}. TITLE, SUBTITLE, AUTHORS, ABSTRACT and KEYWORDS are "
            "filled from the document; enter the others under 'Template fields' in each document.",
            "A placeholder without a value stays visible in the document and the formatting check reports it.")
    cycles = sr.cycles()
    if cycles:
        add("STYLE_CYCLE", "warning", f"Style(s) {', '.join(sorted(cycles))} are based on each other in a loop.",
            "Word ignores the loop; fix 'Based on' in the template.")
    broken = sorted({sid for role, sid in roles.items()
                     if (nid := sr.resolve(sid).get("num_id")) and nid not in num_ids})
    if broken:
        add("BROKEN_NUMBERING", "warning",
            f"Style(s) {', '.join(broken)} point to numbering that does not exist in the template.",
            "Their numbers will not appear. Use heading numbering 'auto' or repair the template.")
    return issues


# ---------------------------------------------------------------------------
def build_default_profile(analysis: dict, name: str = "Untitled profile") -> FormattingProfile:
    """Turn an analysis into a first-draft profile. Every rule records its origin."""
    roles = dict(analysis["suggested_roles"])
    evidence = analysis.get("role_evidence", {})
    table, figure, labels = TableRule(), FigureRule(), Labels()
    lang = analysis["language"]
    o: Dict[str, str] = {}

    for role in roles:
        by = evidence.get(role, {}).get("by", "style_id")
        o[f"roles.{role}"] = "template" if by in TEMPLATE_ORIGIN else "inferred"

    numbered = analysis["heading_numbering_in_template"]
    if numbered:
        o["heading_numbering"] = "template"

    for t in analysis["tables"][:1]:
        if t["caption_position"]:
            table.caption_position = t["caption_position"]; o["table.caption_position"] = "inferred"
        if t["alignment"] in ("left", "center", "right"):
            table.alignment = t["alignment"]; o["table.alignment"] = "inferred"
        if t["header_fill"]:
            table.header_shading = t["header_fill"]; o["table.header_shading"] = "inferred"
        if t["header_bold"]:
            table.header_bold = True; o["table.header_bold"] = "inferred"
        if t["style_id"] and t["style_id"] != "TableNormal":
            table.borders = "template"; table.template_style_id = t["style_id"]
            o["table.borders"] = o["table.template_style_id"] = "inferred"
        elif t["has_direct_borders"]:
            table.borders = "all"; o["table.borders"] = "inferred"
        if t.get("caption_label"):
            table.label = t["caption_label"]; o["table.label"] = "template"
            labels.caption_separator = t["caption_separator"]; o["labels.caption_separator"] = "template"
    for f in analysis["figures"][:1]:
        if f["caption_position"]:
            figure.caption_position = f["caption_position"]; o["figure.caption_position"] = "inferred"
        if f["alignment"] in ("left", "center", "right"):
            figure.alignment = f["alignment"]; o["figure.alignment"] = "inferred"
        if f.get("caption_label"):
            figure.label = f["caption_label"]; o["figure.label"] = "template"
            if "labels.caption_separator" not in o:
                labels.caption_separator = f["caption_separator"]; o["labels.caption_separator"] = "template"

    code = lang.get("suggested_code") or "en"
    settings = LanguageSettings(code=code, rtl=bool(lang.get("rtl")),
                                complex_script_font=lang.get("suggested_cs_font"),
                                east_asian_font=lang.get("suggested_ea_font"))
    o["language.code"] = lang.get("suggested_code_origin", "default")
    if settings.rtl:
        o["language.rtl"] = "template" if (lang.get("normal_bidi") or analysis["page"].get("rtl_section")) else "inferred"
    if settings.complex_script_font:
        o["language.complex_script_font"] = "template"
    if settings.east_asian_font:
        o["language.east_asian_font"] = "template"

    base = code.split("-")[0].lower()
    if base in NATIVE_DIGIT_LANGS:
        settings.native_digits = True
        o["language.native_digits"] = "inferred"
    if base != "en" and base in LANGUAGE_LABELS:
        words = LANGUAGE_LABELS[base]
        for key in ("abstract", "keywords", "source", "note"):
            setattr(labels, key, words[key]); o[f"labels.{key}"] = "inferred"
        for rule, key in ((table, "table"), (figure, "figure")):
            if f"{key}.label" not in o:
                rule.label = words[key]; o[f"{key}.label"] = "inferred"

    if any("body" in p["where"] for p in analysis.get("placeholders", [])):
        o["keep_template_layout"] = "inferred"          # a fill-in layout template
    profile = FormattingProfile(
        name=name, roles=roles,
        keep_template_layout=o.get("keep_template_layout") == "inferred",
        heading_numbering="template" if numbered else "none",
        table=table, figure=figure, language=settings, labels=labels,
    )
    for path in rule_paths(profile):
        o.setdefault(path, "default")
    profile.origins = o
    return profile
