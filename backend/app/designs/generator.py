"""Fixed template generator for predefined designs (component 3 of 3).

`DesignGenerator` combines an `ArticleContent` (what the article says) with a `Design` (how it looks). It is a
subclass of the shared `Generator`, so the article body — any structure of sections, paragraphs, lists, tables
and figures — is written by exactly the same code as in the custom-template workflow. This class only adds:
the first page (rebuilt as flowing tables so it grows with the content), extra heading levels, declarations,
references and the running-header values. Nothing here knows any section name.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from ..core.inline import parse_inline, plain
from ..document_engine.generator import (CONTENT_BOOKMARK, PPR_ORDER, RPR_ORDER, TBLPR_ORDER, TCPR_ORDER,
                                         GenerationResult, Generator, sort_children)
from ..schemas.article import ArticleAuthor, ArticleContent
from ..schemas.content import Author, DocumentContent
from . import Design

TWIPS_PER_CM = 567
JUSTIFY = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
           "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}


def _w(tag: str, **attrs):
    el = OxmlElement(f"w:{tag}")
    for k, v in attrs.items():
        el.set(qn(f"w:{k}"), str(v))
    return el


def cite_authors(authors: List[ArticleAuthor]) -> str:
    """'Akter, R., Rahman, M.K. and Das, S.' (surname, initials; the style of the design's reference examples)."""
    def one(name: str) -> str:
        parts = name.replace(",", " ").split()
        if len(parts) == 1:
            return parts[0]
        initials = "".join(f"{p[0]}." for p in parts[:-1] if p[0].isalpha())
        return f"{parts[-1]}, {initials}"
    names = [one(a.name) for a in authors if a.name.strip()]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def to_content(article: ArticleContent, design: Design) -> DocumentContent:
    """What the shared generator needs: body, title/authors for document properties, header field values."""
    m = article.metadata
    fields = {name: getattr(m, attr) or "" for name, attr in design.data.get("header_fields", {}).items()}
    return DocumentContent(
        language=article.language, title=m.title, abstract=article.abstract, keywords=article.keywords,
        authors=[Author(name=a.name) for a in m.authors], body=article.body, fields=fields)


class DesignGenerator(Generator):
    def __init__(self, design: Design, article: ArticleContent, media_path: Callable[[str], Optional[str]]):
        self.design = design
        self.article = article
        self.page_one = design.data["page_one"]
        super().__init__(design.base_path, design.profile, to_content(article, design), media_path)
        self._add_extra_styles()

    # ------------------------------------------------------------------ styles the design adds
    def _add_extra_styles(self) -> None:
        for spec in self.design.data.get("extra_styles", []):
            if spec["id"] in self.styles:
                continue
            st = self.doc.styles.add_style(spec["name"], WD_STYLE_TYPE.PARAGRAPH)
            st.element.set(qn("w:styleId"), spec["id"])
            st.base_style = self.styles[spec["based_on"]]
            ppr = st.element.get_or_add_pPr()
            ppr.append(_w("outlineLvl", val=spec["outline_level"]))
            sort_children(ppr, PPR_ORDER)
            self.styles[spec["id"]] = st
            self.sr.by_id[spec["id"]] = st.element

    # ------------------------------------------------------------------ small formatting helpers
    @staticmethod
    def _font(run, font: Optional[str] = None, size: Optional[float] = None, bold: Optional[bool] = None,
              italic: Optional[bool] = None, color: Optional[str] = None) -> None:
        if font:
            run.font.name = font
            rpr = run._r.get_or_add_rPr()
            f = rpr.find(qn("w:rFonts"))
            for k in ("eastAsia", "cs"):
                if not f.get(qn(f"w:{k}")):
                    f.set(qn(f"w:{k}"), font)
        if size:
            run.font.size = Pt(size)
            run._r.get_or_add_rPr().append(_w("szCs", val=int(size * 2)))
        if bold is not None:
            run.bold = bold
        if italic is not None:
            run.italic = italic
        if color:
            run.font.color.rgb = RGBColor.from_string(color)
        sort_children(run._r.get_or_add_rPr(), RPR_ORDER)

    def _para(self, container=None, align: Optional[str] = None, before: float = 0, after: float = 0,
              line: Optional[float] = None):
        p = (container or self.doc).add_paragraph()
        pf = p.paragraph_format
        pf.space_before, pf.space_after = Pt(before), Pt(after)
        pf.first_line_indent = Cm(0)
        if line:
            pf.line_spacing = Pt(line)
        if align:
            pf.alignment = JUSTIFY[align]
        return p

    def _markup(self, p, text: str, font: str, size: float, italic: Optional[bool] = None,
                color: Optional[str] = None) -> None:
        """Inline markup (**bold** …) written with the design's font: bold/italic/sup/sub come from the text."""
        for r in parse_inline(text):
            for i, line in enumerate(r.text.split("\n")):
                if i:
                    p.add_run().add_break()
                if not line:
                    continue
                run = p.add_run(line)
                self._font(run, font, size, bold=r.bold or None, italic=(r.italic or italic) or None, color=color)
                if r.sup:
                    run.font.superscript = True
                if r.sub:
                    run.font.subscript = True
                self._script_props(run, line, r.bold, r.italic, {}, size)

    def _table(self, widths_cm: List[float], rows: int = 1):
        t = self.doc.add_table(rows=rows, cols=len(widths_cm))
        tbl = t._tbl
        pr = tbl.tblPr
        for tag in ("tblStyle", "tblW", "tblBorders", "tblLayout", "tblCellMar", "jc"):
            for old in pr.findall(qn(f"w:{tag}")):
                pr.remove(old)
        total = int(sum(widths_cm) * TWIPS_PER_CM)
        pr.append(_w("tblW", w=total, type="dxa"))
        pr.append(_w("jc", val="center"))
        borders = _w("tblBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            borders.append(_w(side, val="nil"))
        pr.append(borders)
        pr.append(_w("tblLayout", type="fixed"))
        mar = _w("tblCellMar")
        for side, v in (("top", 57), ("left", 85), ("bottom", 57), ("right", 85)):
            mar.append(_w(side, w=v, type="dxa"))
        pr.append(mar)
        sort_children(pr, TBLPR_ORDER)
        for gc, w in zip(tbl.find(qn("w:tblGrid")).findall(qn("w:gridCol")), widths_cm):
            gc.set(qn("w:w"), str(int(w * TWIPS_PER_CM)))
        for row in t.rows:
            for cell, w in zip(row.cells, widths_cm):
                tcpr = cell._tc.get_or_add_tcPr()
                for old in tcpr.findall(qn("w:tcW")):
                    tcpr.remove(old)
                tcpr.append(_w("tcW", w=int(w * TWIPS_PER_CM), type="dxa"))
                sort_children(tcpr, TCPR_ORDER)
        return t

    @staticmethod
    def _cell_look(cell, fill: Optional[str] = None, border: Optional[str] = None, border_pt: float = 1.0,
                   margins_twips: Optional[int] = None, valign: Optional[str] = None) -> None:
        tcpr = cell._tc.get_or_add_tcPr()
        if border:
            b = _w("tcBorders")
            for side in ("top", "left", "bottom", "right"):
                b.append(_w(side, val="single", sz=int(border_pt * 8), space=0, color=border))
            tcpr.append(b)
        if fill:
            tcpr.append(_w("shd", val="clear", color="auto", fill=fill))
        if margins_twips is not None:
            m = _w("tcMar")
            for side in ("top", "left", "bottom", "right"):
                m.append(_w(side, w=margins_twips, type="dxa"))
            tcpr.append(m)
        if valign:
            tcpr.append(_w("vAlign", val=valign))
        sort_children(tcpr, TCPR_ORDER)

    def _hyperlink(self, p, url: str):
        rid = self.doc.part.relate_to(url, RT.HYPERLINK, is_external=True)
        h = OxmlElement("w:hyperlink")
        h.set(qn("r:id"), rid)
        p._p.append(h)
        return h

    def _spacer(self, before_pt: float = 0):
        """Keeps two tables apart (Word would merge them) and gives vertical space."""
        p = self._para(before=0, after=0, line=max(before_pt, 1))
        return p

    # ------------------------------------------------------------------ page one
    def add_title_block(self) -> None:
        lay, m = self.page_one, self.article.metadata
        width = round(self.text_width / TWIPS_PER_CM, 2)
        # banner
        b = lay["banner"]
        t = self._table([width / 2, width / 2])
        for cell, text, align in zip(t.rows[0].cells, (b["left"], b["right"]), ("left", "right")):
            self._cell_look(cell, fill=b["fill"], valign="center")
            p = cell.paragraphs[0]
            p.paragraph_format.alignment = JUSTIFY[align]
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.space_after = Pt(0)
            self._font(p.add_run(text), b["font"], b["size_pt"], bold=b["bold"], color=b["color"])
        # title
        ti = lay["title"]
        if m.title.strip():
            p = self._para(align="center", before=ti["space_before_pt"])
            self._markup(p, m.title, ti["font"], ti["size_pt"])
            for r in p.runs:
                r.bold = ti["bold"] or r.bold
        # authors with affiliation markers, * for the corresponding author, ORCID icon
        au = lay["authors"]
        if m.authors:
            p = self._para(align="center", before=au["space_before_pt"])
            for i, a in enumerate(m.authors):
                if i:
                    self._font(p.add_run(", "), au["font"], au["size_pt"], bold=au["bold"])
                self._font(p.add_run(a.name), au["font"], au["size_pt"], bold=au["bold"])
                marks = ",".join(a.affiliations) + ("*" if a.corresponding else "")
                if marks:
                    r = p.add_run(marks)
                    self._font(r, au["font"], au["size_pt"], bold=False)
                    r.font.superscript = True
                if a.orcid:
                    h = self._hyperlink(p, f"https://orcid.org/{a.orcid}")
                    r = p.add_run()
                    r.add_picture(self.design.asset(au["orcid_icon"]), height=Cm(au["orcid_icon_cm"]))
                    h.append(r._r)
        self._spacer()
        # side panel | abstract box
        pn, ab = lay["panel"], lay["abstract_box"]
        t = self._table([pn["width_cm"], ab["width_cm"]])
        row = t.rows[0]
        trpr = row._tr.get_or_add_trPr()
        trpr.append(_w("trHeight", val=int(ab["min_height_cm"] * TWIPS_PER_CM), hRule="atLeast"))
        left, right = row.cells
        self._side_panel(left, pn)
        self._cell_look(right, border=ab["border"], border_pt=ab["border_pt"], margins_twips=113)
        self._abstract(right, ab)
        # citation box
        cb = lay["citation_box"]
        self._spacer(cb["space_before_pt"])
        t = self._table([width])
        cell = t.rows[0].cells[0]
        self._cell_look(cell, fill=cb["fill"], border=cb["border"], border_pt=cb["border_pt"], margins_twips=113)
        self._citation(cell.paragraphs[0], cb)
        # logo | licence
        li = lay["licence"]
        self._spacer(li["space_before_pt"])
        t = self._table([li["logo_cell_cm"], width - li["logo_cell_cm"]])
        logo_cell, text_cell = t.rows[0].cells
        self._cell_look(logo_cell, valign="center")
        lp = logo_cell.paragraphs[0]
        lp.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        lp.add_run().add_picture(self.design.asset(li["logo"]), width=Cm(li["logo_cm"]))
        self._licence(text_cell.paragraphs[0], li)
        # the article body starts on the next page; the bookmark tells the validator where content begins
        end = self._spacer()
        if lay.get("body_starts_on_new_page", True):
            end.add_run().add_break(WD_BREAK.PAGE)
        body = self.doc.element.body
        ids = [int(x.get(qn("w:id"))) for x in body.iter(qn("w:bookmarkStart")) if (x.get(qn("w:id")) or "").isdigit()]
        bid = max(ids, default=0) + 1
        end._p.addnext(_w("bookmarkEnd", id=bid))
        end._p.addnext(_w("bookmarkStart", id=bid, name=CONTENT_BOOKMARK))
        self._after_heading = False

    def _side_panel(self, cell, pn: dict) -> None:
        m, lab = self.article.metadata, pn["labels"]
        tc = cell._tc.get_or_add_tcPr()
        mar = _w("tcMar")
        mar.append(_w("left", w=0, type="dxa"))
        mar.append(_w("right", w=int((pn["width_cm"] - pn["rule_width_cm"]) * TWIPS_PER_CM), type="dxa"))
        tc.append(mar)
        sort_children(tc, TCPR_ORDER)
        lines: List[tuple] = []
        if m.corresponding_author:
            lines.append((lab["corresponding"], 0))
        dates = [f"{lab['received']} {m.received}" if m.received else "", f"{lab['accepted']} {m.accepted}" if m.accepted else ""]
        if any(dates):
            lines.append(("\n".join(d for d in dates if d), 6))
        if m.published:
            lines.append((f"{lab['published']} {m.published}", 6))
        lines.append((f"{lab['copyright']} {m.year}".rstrip() + "\n" + pn["licence_short"], 6))
        lines.append((f"{lab['issn']} {pn['issn']}", 6))
        if m.corresponding_email:
            lines.append((f"{lab['email']} {m.corresponding_email}", 6))
        for i, aff in enumerate(m.affiliations):
            parts = ", ".join(x for x in (aff.department, aff.institution, aff.city, aff.country) if x)
            lines.append((f"{aff.id} {parts}", 6 if i == 0 else 2))
        first = cell.paragraphs[0]
        for i, (text, before) in enumerate(lines):
            p = first if i == 0 else cell.add_paragraph()
            pf = p.paragraph_format
            pf.space_before, pf.space_after = Pt(before), Pt(0)
            pf.line_spacing = Pt(pn["line_pt"])
            pf.first_line_indent = Cm(0)
            pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
            if i == 0:               # the thin rule above the panel
                ppr = p._p.get_or_add_pPr()
                bdr = _w("pBdr")
                bdr.append(_w("top", val="single", sz=6, space=4, color="000000"))
                ppr.append(bdr)
                sort_children(ppr, PPR_ORDER)
            for k, line in enumerate(text.split("\n")):
                if k:
                    p.add_run().add_break()
                self._font(p.add_run(line), pn["font"], pn["size_pt"])

    def _abstract(self, cell, ab: dict) -> None:
        h = cell.paragraphs[0]
        h.paragraph_format.space_after = Pt(3)
        h.paragraph_format.first_line_indent = Cm(0)
        self._font(h.add_run(ab["heading"]), ab["heading_font"], ab["heading_size_pt"], bold=True, color="000000")
        for chunk in [c for c in self.article.abstract.split("\n\n") if c.strip()] or [""]:
            p = cell.add_paragraph()
            pf = p.paragraph_format
            pf.alignment, pf.space_before, pf.space_after = WD_ALIGN_PARAGRAPH.JUSTIFY, Pt(3), Pt(0)
            pf.line_spacing, pf.first_line_indent = Pt(ab["line_pt"]), Cm(0)
            self._markup(p, chunk, ab["text_font"], ab["text_size_pt"], color="000000")
        if any(k.strip() for k in self.article.keywords):
            p = cell.add_paragraph()
            pf = p.paragraph_format
            pf.alignment, pf.space_before, pf.first_line_indent = WD_ALIGN_PARAGRAPH.JUSTIFY, Pt(8), Cm(0)
            self._font(p.add_run(ab["keywords_label"] + " "), ab["text_font"], ab["text_size_pt"], bold=True, italic=True)
            self._markup(p, ", ".join(k.strip() for k in self.article.keywords if k.strip()), ab["text_font"],
                         ab["text_size_pt"], italic=True)

    def _citation(self, p, cb: dict) -> None:
        m = self.article.metadata
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.space_after = Pt(0)
        font, size, color = cb["font"], cb["size_pt"], cb["color"]
        self._font(p.add_run(cb["label"] + " "), font, size, bold=True, color=color)
        who = cite_authors(m.authors)
        lead = " ".join(x for x in (who, f"({m.year})." if m.year else "") if x)
        if lead:
            self._font(p.add_run(lead + " "), font, size, color=color)
        if m.title.strip():
            self._markup(p, plain(m.title).rstrip(".") + ". ", font, size, color=color)
        self._font(p.add_run(cb["journal"]), font, size, italic=True, color=color)
        vol = m.volume + (f"({m.issue})" if m.issue else "")
        tail = ", ".join(x for x in (vol, m.pages) if x)
        self._font(p.add_run((", " + tail if tail else "") + "." + (f" {m.doi}" if m.doi else "")), font, size, color=color)

    def _licence(self, p, li: dict) -> None:
        m = self.article.metadata
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.space_after = Pt(0)
        self._font(p.add_run(f"{li['copyright']} {m.year}".rstrip() + ". "), li["font"], li["size_pt"])
        self._font(p.add_run(li["lead"] + " "), li["font"], li["lead_size_pt"], bold=True)
        self._font(p.add_run(li["text"]), li["font"], li["size_pt"])
        h = self._hyperlink(p, li["url"])
        r = p.add_run(li["url"])
        self._font(r, li["font"], li["size_pt"], color="0563C1")
        r.underline = True
        h.append(r._r)
        self._font(p.add_run(li["after_url"]), li["font"], li["size_pt"])

    # ------------------------------------------------------------------ after the body
    def add_back_matter(self) -> None:
        bm, a = self.design.data["back_matter"], self.article
        for key, title in bm["items"]:
            text = getattr(a.back_matter, key, "")
            if not text.strip():
                continue
            h = self.new_par(bm["heading_style"], keep_next=True, text=title)
            self.add_text(h, title, bm["heading_style"])
            p = self.new_par(bm["text_style"], text=text)
            self.add_text(p, text, bm["text_style"])
        refs = [r for r in a.references if r.strip()]
        if refs:
            h = self.new_par(bm["references_heading_style"], keep_next=True, text=bm["references_heading"])
            self.add_text(h, bm["references_heading"], bm["references_heading_style"])
            for ref in refs:
                p = self.new_par(bm["reference_style"], text=ref)
                self.add_text(p, ref, bm["reference_style"])
        self._last_was_table = False


def generate_article(design: Design, article: ArticleContent, media_path: Callable[[str], Optional[str]],
                     out_path: str) -> GenerationResult:
    g = DesignGenerator(design, article, media_path)
    g.build()
    g.doc.save(out_path)
    return GenerationResult(path=out_path, warnings=g.warnings, stats=g.stats)
