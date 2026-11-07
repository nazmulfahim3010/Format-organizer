"""Validation of a generated DOCX against the profile (no AI, no percentage score).

Every check has a status: passed | warning | failed | info | manual.
`kind` says whether it was verified automatically from the file ("auto") or
needs a human look at the rendering ("visual").
"""
from __future__ import annotations

import copy
import re
import zipfile
from typing import Dict, List, Optional

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from ..core.inline import plain
from ..core.placeholders import PLACEHOLDER as PLACEHOLDER_RE
from ..document_engine.generator import (CJK_SCRIPTS, CONTENT_BOOKMARK, LANG_SCRIPT, PPR_ORDER, RPR_ORDER,
                                         RTL_LANGS, SECTPR_ORDER, TBLPR_ORDER, TCPR_ORDER)
from ..schemas.content import DocumentContent, SectionBox
from ..schemas.profile import FormattingProfile
from ..template_engine.ooxml import (StyleResolver, has_field, page_text_height_twips, page_text_width_twips,
                                     paragraph_text, script_of)

WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
STATUSES = ("passed", "warning", "failed", "info", "manual")
EMU_PER_TWIP = 635
PLACEHOLDERS = ("[image missing]", "[image unreadable]")
# a number or marker typed at the start of text that Word already numbers
TYPED_NUMBER = re.compile(r"^\s*(?:\(?\d+(?:[.\-]\d+)*[.)]?|\(?[a-zA-Z][.)]|[•\-–·▪●○◦])\s+\S")
ORDERS = (("pPr", PPR_ORDER), ("rPr", RPR_ORDER), ("tblPr", TBLPR_ORDER), ("tcPr", TCPR_ORDER),
          ("sectPr", SECTPR_ORDER))


def _check(id_: str, title: str, status: str, details: Optional[List[str]] = None, kind: str = "auto") -> dict:
    return {"id": id_, "title": title, "status": status, "kind": kind, "details": details or []}


def _seq_values(p_el, name: str) -> List[int]:
    """Cached result numbers of SEQ <name> fields in a paragraph."""
    out: List[int] = []
    runs = list(p_el.iter(qn("w:r")))
    state = None
    for r in runs:
        fc = r.find(qn("w:fldChar"))
        it = r.find(qn("w:instrText"))
        if fc is not None:
            t = fc.get(qn("w:fldCharType"))
            if t == "begin":
                state = {"instr": "", "phase": "instr", "text": ""}
            elif t == "separate" and state:
                state["phase"] = "result"
            elif t == "end" and state:
                if state["instr"].strip().upper().startswith(f"SEQ {name.upper()}"):
                    digits = "".join(ch for ch in state["text"] if ch.isdigit())
                    if digits:
                        out.append(int(digits))
                state = None
        elif state is not None:
            if it is not None and state["phase"] == "instr":
                state["instr"] += it.text or ""
            elif state["phase"] == "result":
                state["text"] += "".join(t.text or "" for t in r.iter(qn("w:t")))
    return out


def _same_text(template: str, document: str) -> bool:
    """Header/footer text is unchanged, allowing each {{PLACEHOLDER}} to have been filled with anything."""
    pattern = "".join(".*?" if PLACEHOLDER_RE.fullmatch(part) else re.escape(part)
                      for part in re.split(r"(\{\{\s*[A-Za-z0-9_]{1,40}\s*\}\})", template))
    return re.fullmatch(pattern, document, re.S) is not None


def _digits(text: str) -> str:
    """Native digits (১, ٢, ३ ...) to ASCII so typed numbers in any script are recognised."""
    return "".join(str(int(c)) if c.isdigit() else c for c in text)


def _num_levels(doc) -> Dict[str, set]:
    """numId -> set of ilvl defined by its abstractNum."""
    try:
        root = doc.part.numbering_part.element
    except Exception:
        return {}
    abstract = {a.get(qn("w:abstractNumId")): {int(l.get(qn("w:ilvl"))) for l in a.findall(qn("w:lvl"))}
                for a in root.findall(qn("w:abstractNum"))}
    out = {}
    for n in root.findall(qn("w:num")):
        a = n.find(qn("w:abstractNumId"))
        out[n.get(qn("w:numId"))] = abstract.get(a.get(qn("w:val")) if a is not None else None, set())
    return out


def _xml_order_problems(docx_path: str) -> List[str]:
    bad: List[str] = []
    with zipfile.ZipFile(docx_path) as z:
        names = [n for n in z.namelist() if n in ("word/document.xml", "word/styles.xml", "word/numbering.xml")]
        for part in names:
            root = etree.fromstring(z.read(part))
            for tag, order in ORDERS:
                rank = {f"{{{W_NS}}}{n}": i for i, n in enumerate(order)}
                for el in root.iter(f"{{{W_NS}}}{tag}"):
                    ranks = [rank[c.tag] for c in el if c.tag in rank]
                    if ranks != sorted(ranks):
                        kids = [etree.QName(c).localname for c in el]
                        bad.append(f"{part}: {tag} children out of order: {', '.join(kids)}")
                        break
    return bad


def _paragraph_numbered(p, sr: StyleResolver, sid: Optional[str]) -> Optional[tuple]:
    """(numId, ilvl) a paragraph is numbered with, from its own numPr or its style; None if not numbered."""
    np_ = p.find(f"{qn('w:pPr')}/{qn('w:numPr')}")
    res = sr.resolve(sid) if sid else {}
    nid = res.get("num_id")
    lvl = res.get("num_ilvl", 0)
    if np_ is not None:
        n = np_.find(qn("w:numId"))
        l = np_.find(qn("w:ilvl"))
        if n is not None:
            nid = n.get(qn("w:val"))
        if l is not None:
            lvl = int(l.get(qn("w:val")))
    if nid in (None, "0"):
        return None
    return nid, lvl


def validate_docx(docx_path: str, profile: FormattingProfile, content: DocumentContent,
                  template_page: Optional[dict] = None, analysis: Optional[dict] = None) -> dict:
    """`template_page` is the template analysis' page dict; `analysis` the whole analysis (enables the
    header/footer and column checks)."""
    doc = Document(docx_path)
    sr = StyleResolver(doc)
    body = doc.element.body
    checks: List[dict] = []
    template_page = template_page or (analysis or {}).get("page")
    sect_pr = body.find(qn("w:sectPr"))
    col_width = page_text_width_twips(sect_pr)
    text_height = page_text_height_twips(sect_pr)

    # ---- page setup (must match the template exactly) -------------------------------
    sect = doc.sections[-1]
    cm = lambda v: round(v / 360000, 2)
    got = {"width_cm": cm(sect.page_width), "height_cm": cm(sect.page_height),
           "left": cm(sect.left_margin), "right": cm(sect.right_margin),
           "top": cm(sect.top_margin), "bottom": cm(sect.bottom_margin)}
    if template_page:
        want = {"width_cm": template_page["width_cm"], "height_cm": template_page["height_cm"],
                **template_page["margins_cm"]}
        bad = [f"{k}: template {want[k]} cm, document {got[k]} cm" for k in got if abs(got[k] - want[k]) > 0.02]
        cols = sect_pr.find(qn("w:cols"))
        ncols = int(cols.get(qn("w:num"))) if cols is not None and cols.get(qn("w:num")) else 1
        if template_page.get("columns", 1) != ncols:
            bad.append(f"columns: template {template_page.get('columns', 1)}, document {ncols}")
        checks.append(_check("page_setup", "Page size and margins match the template",
                             "failed" if bad else "passed", bad))
    else:
        checks.append(_check("page_setup", "Page size and margins", "info",
                             [f"{got['width_cm']} x {got['height_cm']} cm; margins L{got['left']} R{got['right']} T{got['top']} B{got['bottom']} cm"]))

    # ---- required sections ---------------------------------------------------------------
    if profile.required_sections:
        titles = {plain(b.title).strip().lower() for b in content.body if isinstance(b, SectionBox)}
        missing = [r for r in profile.required_sections if r.strip().lower() not in titles]
        checks.append(_check("required_sections", "Required sections are present",
                             "failed" if missing else "passed", [f"Missing: {m}" for m in missing]))

    # ---- heading hierarchy & numbering ------------------------------------------------
    role_of = {}
    for lvl in range(1, 10):
        sid = profile.roles.get(f"heading_{lvl}")
        if sid:
            role_of.setdefault(sid, lvl)
    # generator may have created "Heading N" styles; recognise them by outline level too
    paragraphs = list(body.iter(qn("w:p")))
    # a kept template layout (banner, boxes, logo) is the template's, not content: judge only what follows
    # the generator's content bookmark
    scope = body
    marker = next((b for b in body if b.tag == qn("w:bookmarkStart") and b.get(qn("w:name")) == CONTENT_BOOKMARK), None)
    if marker is not None:
        scope = etree.Element(body.tag)
        for el in list(body)[list(body).index(marker) + 1:]:
            if el.tag != qn("w:sectPr"):
                scope.append(copy.deepcopy(el))
    heads: List[tuple] = []
    unnumbered: List[str] = []
    for p in paragraphs:
        ps = p.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
        sid = ps.get(qn("w:val")) if ps is not None else None
        lvl = role_of.get(sid)
        if lvl is None and sid:
            ol = sr.resolve(sid).get("outline_level")
            lvl = ol + 1 if ol is not None else None
        if lvl is None:
            continue
        heads.append((lvl, paragraph_text(p)))
        res = sr.resolve(sid)
        num = p.find(f"{qn('w:pPr')}/{qn('w:numPr')}/{qn('w:numId')}")
        numbered = (num.get(qn("w:val")) != "0") if num is not None else res.get("num_id") not in (None, "0")
        if not numbered:
            unnumbered.append(paragraph_text(p)[:50])
    hier_bad = []
    prev = 0
    for lvl, text in heads:
        if lvl > prev + 1:
            hier_bad.append(f"'{text[:40]}' is level {lvl} after level {prev}")
        prev = lvl
    # the generator maps depth>available levels to the nearest defined style, so skipped *styles* can appear;
    # judge hierarchy from the content tree too
    checks.append(_check("heading_hierarchy", "Heading hierarchy has no skipped levels",
                         "failed" if hier_bad else "passed", hier_bad))
    if profile.heading_numbering != "none" and heads:
        checks.append(_check("heading_numbering", "Headings are numbered",
                             "warning" if unnumbered else "passed",
                             [f"Not numbered: {t}" for t in unnumbered[:8]]))
    elif heads:
        checks.append(_check("heading_numbering", "Headings are numbered", "info", ["Numbering is switched off in the profile."]))

    # ---- headers and footers kept from the template ---------------------------------
    hf = (analysis or {}).get("header_footer")
    if hf is None:
        checks.append(_check("header_footer", "Headers and footers kept from the template", "info",
                             ["Template analysis not available; compare by eye."]))
    else:
        sect = doc.sections[-1]
        present = {(r.get(qn("w:type")), t) for t in ("headerReference", "footerReference")
                   for r in sect_pr.findall(qn(f"w:{t}"))}
        parts = {("headerReference", "default"): sect.header, ("headerReference", "first"): sect.first_page_header,
                 ("headerReference", "even"): sect.even_page_header, ("footerReference", "default"): sect.footer,
                 ("footerReference", "first"): sect.first_page_footer, ("footerReference", "even"): sect.even_page_footer}

        def text_of(part) -> str:
            return " | ".join(p.text for p in part.paragraphs if p.text.strip())
        hbad: List[str] = []
        want = {("headerReference", k): v for k, v in (hf.get("kinds") or
                ({"default": hf["header_text"]} if hf.get("header_text") else {})).items()}
        want.update({("footerReference", k): v for k, v in (hf.get("footer_kinds") or
                     ({"default": hf["footer_text"]} if hf.get("footer_text") else {})).items()})
        for (tag, kind), text in want.items():
            label = f"{kind} {'header' if tag == 'headerReference' else 'footer'}"
            if (kind, tag) not in present:
                hbad.append(f"The template's {label} is missing.")
            elif not _same_text(text, text_of(parts[(tag, kind)])):
                hbad.append(f"The {label} text changed: template '{text[:40]}', document '{text_of(parts[(tag, kind)])[:40]}'.")
        for where, flag, tag in (("footer", "footer_has_page_number", "footerReference"),
                                 ("header", "header_has_page_number", "headerReference")):
            if hf.get(flag):
                has = any(has_field(parts[(tag, k)]._element, "PAGE") for k in ("default", "first", "even")
                          if (k, tag) in present)
                if not has:
                    hbad.append(f"The template's page number in the {where} is missing.")
        checks.append(_check("header_footer", "Headers and footers kept from the template",
                             "failed" if hbad else "passed", hbad))

    # ---- real Word numbering ----------------------------------------------------------
    levels = _num_levels(doc)
    nbad: List[str] = []
    typed: List[str] = []
    for p in paragraphs:
        ps = p.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
        sid = ps.get(qn("w:val")) if ps is not None else None
        num = _paragraph_numbered(p, sr, sid)
        text = paragraph_text(p)
        if num is None:
            continue
        nid, lvl = num
        if nid not in levels:
            nbad.append(f"'{text[:40]}' uses numbering {nid}, which does not exist.")
        elif lvl not in levels[nid]:
            nbad.append(f"'{text[:40]}' uses level {lvl + 1} of numbering {nid}, which is not defined.")
        if TYPED_NUMBER.match(_digits(text)):
            typed.append(f"'{text[:50]}' has a typed number on top of Word's numbering.")
    checks.append(_check("list_numbering", "Lists and numbered headings use real Word numbering",
                         "failed" if nbad else "passed", nbad[:10]))
    checks.append(_check("typed_numbering", "No typed numbers on top of automatic numbering",
                         "warning" if typed else "passed", typed[:10]))

    # ---- XML in schema order (Word refuses some files otherwise) ----------------------
    order_bad = _xml_order_problems(docx_path)
    checks.append(_check("xml_order", "XML elements are in the order Word requires",
                         "failed" if order_bad else "passed", order_bad[:10]))

    # ---- direct formatting in body text -----------------------------------------------
    direct = 0
    for p in scope.findall(qn("w:p")):   # body paragraphs only, not table cells
        for r in p.findall(qn("w:r")):
            rpr = r.find(qn("w:rPr"))
            if rpr is None:
                continue
            f = rpr.find(qn("w:rFonts"))
            has_latin = f is not None and (f.get(qn("w:ascii")) or f.get(qn("w:hAnsi")))
            if has_latin or rpr.find(qn("w:sz")) is not None or rpr.find(qn("w:color")) is not None:
                direct += 1
    checks.append(_check("direct_formatting", "Body text uses template styles (no direct font/size/colour)",
                         "warning" if direct else "passed",
                         [f"{direct} run(s) carry direct font, size or colour formatting."] if direct else []))

    # ---- captions + numbering -------------------------------------------------------------
    body_children = [c for c in scope if c.tag in (qn("w:p"), qn("w:tbl"))]
    tbl_rule, fig_rule = profile.table, profile.figure

    def caption_near(idx: int, pos: str, kind: str) -> Optional[object]:
        j = idx - 1 if pos == "above" else idx + 1
        if 0 <= j < len(body_children):
            el = body_children[j]
            if el.tag == qn("w:p") and has_field(el, f"SEQ {kind}"):
                return el
        return None

    missing_t, missing_f, weak = [], [], []
    seq: Dict[str, List[int]] = {"Table": [], "Figure": []}
    n_tbl = n_fig = 0
    for idx, el in enumerate(body_children):
        kind = None
        if el.tag == qn("w:tbl"):
            kind, rule = "Table", tbl_rule
            n_tbl += 1
        elif el.tag == qn("w:p") and next(el.iter(f"{WP}extent"), None) is not None:
            kind, rule = "Figure", fig_rule
            n_fig += 1
        if kind:
            cap = caption_near(idx, rule.caption_position, kind)
            if cap is None:
                (missing_t if kind == "Table" else missing_f).append(
                    f"{kind} {n_tbl if kind == 'Table' else n_fig}: no caption {rule.caption_position} it")
            else:
                text = paragraph_text(cap).strip()
                if len(text) <= len(rule.label) + 3:
                    weak.append(f"{kind} {n_tbl if kind == 'Table' else n_fig}: caption has no text")
    for el in body_children:
        if el.tag == qn("w:p"):
            for k in ("Table", "Figure"):
                seq[k].extend(_seq_values(el, k))
    checks.append(_check("table_captions", f"Every table has a caption {tbl_rule.caption_position} it",
                         "failed" if missing_t else ("warning" if any("Table" in w for w in weak) else "passed"),
                         missing_t + [w for w in weak if w.startswith("Table")]) if n_tbl else
                  _check("table_captions", "Table captions", "info", ["No tables in the document."]))
    checks.append(_check("figure_captions", f"Every figure has a caption {fig_rule.caption_position} it",
                         "failed" if missing_f else ("warning" if any("Figure" in w for w in weak) else "passed"),
                         missing_f + [w for w in weak if w.startswith("Figure")]) if n_fig else
                  _check("figure_captions", "Figure captions", "info", ["No figures in the document."]))
    bad_seq = []
    for k, vals in seq.items():
        if vals and vals != list(range(1, len(vals) + 1)):
            bad_seq.append(f"{k} numbers are {vals}, expected 1..{len(vals)}")
    checks.append(_check("numbering_continuity", "Table and figure numbers are sequential (SEQ fields)",
                         "failed" if bad_seq else "passed", bad_seq))

    # ---- table structure ---------------------------------------------------------------------
    tbad = []
    for ti, tbl in enumerate(scope.findall(qn("w:tbl")), 1):
        ncols = len(tbl.findall(f"{qn('w:tblGrid')}/{qn('w:gridCol')}"))
        rows = tbl.findall(qn("w:tr"))
        for ri, tr in enumerate(rows):
            if len(tr.findall(qn("w:tc"))) != ncols:
                tbad.append(f"Table {ti}, row {ri + 1}: {len(tr.findall(qn('w:tc')))} cells, grid has {ncols}")
        if tbl_rule.repeat_header and rows and rows[0].find(f"{qn('w:trPr')}/{qn('w:tblHeader')}") is None:
            tbad.append(f"Table {ti}: header row is not set to repeat on new pages")
    if n_tbl:
        checks.append(_check("table_structure", "Tables are well-formed with a repeating header row",
                             "failed" if tbad else "passed", tbad))

    # ---- tables and figures fit the text column ------------------------------------------------
    fit_t: List[str] = []
    for ti, tbl in enumerate(scope.iter(qn("w:tbl")), 1):
        w = tbl.find(f"{qn('w:tblPr')}/{qn('w:tblW')}")
        grid = sum(int(g.get(qn("w:w")) or 0) for g in tbl.findall(f"{qn('w:tblGrid')}/{qn('w:gridCol')}"))
        width = int(w.get(qn("w:w"))) if w is not None and w.get(qn("w:type")) == "dxa" else grid
        if max(width, grid) > col_width * 1.01:
            fit_t.append(f"Table {ti} is {max(width, grid) / 567:.1f} cm wide; the text column is {col_width / 567:.1f} cm.")
    if n_tbl:
        checks.append(_check("table_fit", "Tables fit the text column", "failed" if fit_t else "passed", fit_t))
    else:
        checks.append(_check("table_fit", "Tables fit the text column", "info", ["No tables in the document."]))
    fit_f: List[str] = []
    for fi, ext in enumerate(scope.iter(f"{WP}extent"), 1):
        cx, cy = int(ext.get("cx")), int(ext.get("cy"))
        if cx > col_width * EMU_PER_TWIP * 1.01:
            fit_f.append(f"Figure {fi} is {cx / 360000:.1f} cm wide; the text column is {col_width / 567:.1f} cm.")
        if cy > text_height * EMU_PER_TWIP:
            fit_f.append(f"Figure {fi} is {cy / 360000:.1f} cm tall; the page has {text_height / 567:.1f} cm.")
    if n_fig:
        checks.append(_check("figure_fit", "Figures fit the column and the page", "failed" if fit_f else "passed", fit_f))
    else:
        checks.append(_check("figure_fit", "Figures fit the column and the page", "info", ["No figures in the document."]))
    holes = [paragraph_text(p).strip() for p in scope.iter(qn("w:p")) if paragraph_text(p).strip() in PLACEHOLDERS]

    # ---- template placeholders all filled ------------------------------------------------------
    left: Dict[str, set] = {}
    parts = [("body", body)] + [(r.reltype.rsplit("/", 1)[-1], r.target_part.element) for r in doc.part.rels.values()
                                if r.reltype.endswith(("/header", "/footer"))]
    for where, el in parts:
        for p in el.iter(qn("w:p")):
            for m in PLACEHOLDER_RE.finditer(paragraph_text(p)):
                left.setdefault(m.group(1), set()).add(where)
    had = (analysis or {}).get("placeholders")
    if left:
        checks.append(_check("placeholders", "Template placeholders are filled", "warning",
                             [f"{{{{{n}}}}} is still in the {' and '.join(sorted(w))}." for n, w in sorted(left.items())][:12]))
    elif had is not None and not had:
        checks.append(_check("placeholders", "Template placeholders are filled", "info", ["The template has no placeholders."]))
    else:
        checks.append(_check("placeholders", "Template placeholders are filled", "passed"))
    checks.append(_check("figure_images", "Every figure has its image",
                         "warning" if holes else "passed",
                         [f"{len(holes)} figure(s) have no image yet; upload them in the editor."] if holes else []))

    # ---- caption labels follow the profile ---------------------------------------------------
    label_bad: List[str] = []
    for el in body_children:
        if el.tag != qn("w:p"):
            continue
        for kind, rule in (("Table", tbl_rule), ("Figure", fig_rule)):
            if has_field(el, f"SEQ {kind}") and not paragraph_text(el).strip().startswith(rule.label):
                label_bad.append(f"'{paragraph_text(el)[:40]}' does not start with the label '{rule.label}'.")
    if n_tbl or n_fig:
        checks.append(_check("caption_labels", "Caption labels match the profile",
                             "warning" if label_bad else "passed", label_bad[:10]))
    else:
        checks.append(_check("caption_labels", "Caption labels match the profile", "info", ["No captions."]))

    # ---- complex scripts and right-to-left ---------------------------------------------------
    lang_code = (content.language or profile.language.code or "en")
    rtl_doc = profile.language.rtl or lang_code.split("-")[0].lower() in RTL_LANGS
    all_text = "".join(t.text or "" for t in body.iter(qn("w:t")))
    has_complex = script_of(all_text) in ("complex", "rtl")
    if not has_complex and not rtl_doc:
        checks.append(_check("complex_script", "Complex-script and right-to-left properties", "info",
                             ["No complex-script or right-to-left text."]))
    else:
        cbad: List[str] = []
        cs_font = profile.language.complex_script_font
        no_font = no_rtl = no_bcs = 0
        for p in body.iter(qn("w:p")):
            ps = p.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
            res = sr.resolve(ps.get(qn("w:val")) if ps is not None else sr.default_par_id)
            for r in p.iter(qn("w:r")):
                text = "".join(t.text or "" for t in r.iter(qn("w:t")))
                kind = script_of(text)
                if kind not in ("complex", "rtl"):
                    continue
                # direction comes from letters; Arabic-Indic digits are neutral and need no w:rtl
                letters_rtl = script_of("".join(ch for ch in text if ch.isalpha())) == "rtl"
                rpr = r.find(qn("w:rPr"))
                fonts = rpr.find(qn("w:rFonts")) if rpr is not None else None
                if cs_font and (fonts is None or fonts.get(qn("w:cs")) != cs_font) and res.get("font_cs") != cs_font:
                    no_font += 1
                if letters_rtl and (rpr is None or rpr.find(qn("w:rtl")) is None):
                    no_rtl += 1
                bold = (rpr is not None and rpr.find(qn("w:b")) is not None) or res.get("bold")
                if bold and not (rpr is not None and rpr.find(qn("w:bCs")) is not None) and not res.get("bold_cs"):
                    no_bcs += 1
        if no_font:
            cbad.append(f"{no_font} complex-script run(s) do not use the profile font '{cs_font}'.")
        if no_rtl:
            cbad.append(f"{no_rtl} right-to-left run(s) lack w:rtl.")
        if no_bcs:
            cbad.append(f"{no_bcs} bold complex-script run(s) lack w:bCs, so they will not look bold.")
        if rtl_doc:
            flat = [t for t in body.iter(qn("w:tbl")) if t.find(f"{qn('w:tblPr')}/{qn('w:bidiVisual')}") is None]
            if flat:
                cbad.append(f"{len(flat)} table(s) lack w:bidiVisual (columns will not run right to left).")
            if sect_pr.find(qn("w:bidi")) is None:
                cbad.append("The section is not marked right-to-left (sectPr/bidi).")
        checks.append(_check("complex_script", "Complex-script and right-to-left properties",
                             "failed" if cbad else "passed", cbad))

    # ---- document language default -------------------------------------------------------------
    dd_lang = doc.styles.element.find(f"{qn('w:docDefaults')}/{qn('w:rPrDefault')}/{qn('w:rPr')}/{qn('w:lang')}")
    script = LANG_SCRIPT.get(lang_code.split("-")[0].lower())
    slot = "val" if script is None else ("eastAsia" if script in CJK_SCRIPTS else "bidi")
    if not profile.language.set_default_language:
        checks.append(_check("document_language", "Document language is set", "info",
                             ["Setting the document language is switched off in the profile."]))
    else:
        found = dd_lang.get(qn(f"w:{slot}")) if dd_lang is not None else None
        checks.append(_check("document_language", "Document language is set",
                             "passed" if found == lang_code else "warning",
                             [] if found == lang_code else [f"Expected {slot}='{lang_code}', found '{found}'."]))

    # ---- empty sections ----------------------------------------------------------------------
    empty: List[str] = []

    def walk(boxes):
        for b in boxes:
            if isinstance(b, SectionBox):
                if not b.content:
                    empty.append(plain(b.title) or "(untitled)")
                walk(b.content)
    walk(content.body)
    checks.append(_check("empty_sections", "No empty sections", "warning" if empty else "passed",
                         [f"Empty: {t}" for t in empty]))

    # ---- fonts overview (info, for the human) -------------------------------------------
    used = {}
    for p in body.findall(qn("w:p")):
        ps = p.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
        sid = ps.get(qn("w:val")) if ps is not None else sr.default_par_id
        used[sid] = used.get(sid, 0) + 1
    lines = []
    for sid, n in sorted(used.items(), key=lambda kv: -kv[1])[:6]:
        r = sr.resolve(sid)
        cs = ""
        if has_complex:     # the font that complex-script text actually uses
            cs_name = profile.language.complex_script_font or r.get("font_cs")
            cs = f" / {cs_name or '?'} (complex script)"
        lines.append(f"{sid}: {r.get('font') or '?'}{cs} {r.get('size_pt') or '?'} pt x{n}")
    checks.append(_check("fonts_used", "Fonts and sizes in use (from template styles)", "info", lines))

    # ---- things only a human can judge ----------------------------------------------------
    for id_, title in (("visual_pagination", "Page breaks, widows/orphans and where tables split across pages"),
                       ("visual_figures", "Image placement and sizing on the page"),
                       ("visual_fit", "Wide tables fit the page and remain readable"),
                       ("visual_headers", "Header/footer content looks right (logos, page numbers)")):
        checks.append(_check(id_, title, "manual", ["Check in the preview or in Word."], kind="visual"))
    if has_complex or rtl_doc:
        checks.append(_check("visual_script", "Script shaping (conjuncts, joined letters) and right-to-left order "
                             "look right", "manual",
                             ["Fonts substitute silently when the named font is missing; check in Word on the "
                              "target machine."], kind="visual"))

    summary = {s: sum(1 for c in checks if c["status"] == s) for s in STATUSES}
    return {"checks": checks, "summary": summary}
