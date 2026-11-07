"""Build a varied set of template .docx files for tests (no external downloads).

default      - python-docx default template (all Word built-in styles)
university   - custom styles, numbered headings, header/footer with page field, table style
messy        - everything is Normal with direct formatting (no real styles)
bangla       - localized style names, complex-script fonts, Bangla sample text
twocol       - IEEE-like two-column page with its own styles
rtl          - Arabic sample text, RTL defaults
"""
import os
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from app.document_engine.generator import PPR_ORDER, RPR_ORDER, sort_children


def _field(par, instr):
    for kind, val in (("begin", None), ("instr", instr), ("separate", None), ("text", "1"), ("end", None)):
        r = OxmlElement("w:r")
        if kind == "instr":
            it = OxmlElement("w:instrText"); it.text = f" {val} "; r.append(it)
        elif kind == "text":
            t = OxmlElement("w:t"); t.text = val; r.append(t)
        else:
            fc = OxmlElement("w:fldChar"); fc.set(qn("w:fldCharType"), kind); r.append(fc)
        par._p.append(r)


def default(path):
    d = Document()
    d.add_heading("Sample template", 0)
    d.add_paragraph("Sample text that should be removed.")
    d.save(path)


def university(path):
    d = Document()
    for s in d.sections:
        s.page_width, s.page_height = Cm(21), Cm(29.7)
        s.left_margin = s.right_margin = Cm(3.8)
        s.top_margin = s.bottom_margin = Cm(2.5)
        s.header.paragraphs[0].text = "Metropolitan University - Thesis"
        _field(s.footer.paragraphs[0], "PAGE")
    st = d.styles
    st["Normal"].font.name = "Times New Roman"; st["Normal"].font.size = Pt(12)
    st["Normal"].paragraph_format.line_spacing = 1.5
    st["Normal"].paragraph_format.first_line_indent = Cm(1.0)
    for i, size in ((1, 14), (2, 13), (3, 12)):
        h = st[f"Heading {i}"]
        h.font.name = "Times New Roman"; h.font.size = Pt(size); h.font.bold = True
        h.font.color.rgb = RGBColor(0, 0, 0)
        h.paragraph_format.first_line_indent = Cm(0)
    cap = st["Caption"]; cap.font.size = Pt(10); cap.font.bold = False; cap.font.italic = False
    # numbered headings from template (real multilevel list linked to styles)
    numbering = d.part.numbering_part.element
    a = OxmlElement("w:abstractNum"); a.set(qn("w:abstractNumId"), "90")
    ml = OxmlElement("w:multiLevelType"); ml.set(qn("w:val"), "multilevel"); a.append(ml)
    for lvl in range(3):
        lv = OxmlElement("w:lvl"); lv.set(qn("w:ilvl"), str(lvl))
        for tag, val in (("start", "1"), ("numFmt", "decimal"), ("pStyle", f"Heading{lvl+1}"),
                         ("lvlText", ".".join(f"%{i+1}" for i in range(lvl + 1))), ("lvlJc", "left")):
            e = OxmlElement(f"w:{tag}"); e.set(qn("w:val"), val); lv.append(e)
        a.append(lv)
    first = numbering.find(qn("w:num"))
    (first.addprevious(a) if first is not None else numbering.append(a))
    n = OxmlElement("w:num"); n.set(qn("w:numId"), "90")
    ab = OxmlElement("w:abstractNumId"); ab.set(qn("w:val"), "90"); n.append(ab); numbering.append(n)
    for lvl in range(3):
        ppr = st[f"Heading {lvl+1}"].element.get_or_add_pPr()
        np_ = OxmlElement("w:numPr")
        il = OxmlElement("w:ilvl"); il.set(qn("w:val"), str(lvl))
        ni = OxmlElement("w:numId"); ni.set(qn("w:val"), "90")
        np_.append(il); np_.append(ni); ppr.append(np_)
        sort_children(ppr, PPR_ORDER)            # numPr belongs before spacing/ind/outlineLvl
    d.add_heading("Introduction", 1)
    d.add_paragraph("Sample body text.")
    t = d.add_table(rows=2, cols=2); t.style = "Table Grid"
    d.add_paragraph("Table 1: Sample table", style="Caption")
    d.save(path)


def messy(path):
    d = Document()
    for _ in range(12):
        p = d.add_paragraph()
        r = p.add_run("Heading-looking line"); r.bold = True; r.font.size = Pt(15); r.font.name = "Arial"
        p2 = d.add_paragraph(); r2 = p2.add_run("Body text with manual formatting."); r2.font.size = Pt(11); r2.font.color.rgb = RGBColor(10, 10, 10)
    # wipe heading/caption styles to simulate an all-Normal template
    styles_el = d.styles.element
    for s in list(styles_el.findall(qn("w:style"))):
        sid = s.get(qn("w:styleId"))
        if sid.startswith("Heading") or sid in ("Title", "Caption", "ListBullet", "ListNumber", "Subtitle"):
            styles_el.remove(s)
    # odd, copy-pasted style names of the kind real messy templates accumulate
    for name in ("bdy txt FINAL", "Normal1", "Para (copy) 2", "zz_old_STYLE"):
        st = d.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = d.styles["Normal"]
        d.add_paragraph(f"Text in {name}", style=st)
    d.styles.add_style("Default Paragraph Font1", WD_STYLE_TYPE.CHARACTER)
    d.save(path)


def bangla(path):
    d = Document()
    for s in d.sections:
        s.left_margin = s.right_margin = Cm(2.54)
    st = d.styles
    st["Normal"].font.name = "Times New Roman"
    rpr = st["Normal"].element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    rf.set(qn("w:cs"), "Kalpurush")
    # localize built-in style display names (ids stay English, as in real localized Word files)
    names = {"Heading 1": "শিরোনাম ১", "Heading 2": "শিরোনাম ২", "Caption": "ক্যাপশন", "Title": "শিরোনাম"}
    for s in st.element.findall(qn("w:style")):
        n = s.find(qn("w:name"))
        if n is not None and n.get(qn("w:val")).lower() in {k.lower() for k in names}:
            for k, v in names.items():
                if n.get(qn("w:val")).lower() == k.lower():
                    n.set(qn("w:val"), v)
    d.add_paragraph("এটি একটি নমুনা অনুচ্ছেদ।")
    d.save(path)


def twocol(path):
    d = Document()
    s = d.sections[0]
    s.left_margin = s.right_margin = Cm(1.9); s.top_margin = Cm(1.9); s.bottom_margin = Cm(2.3)
    cols = s._sectPr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols"); s._sectPr.append(cols)
    cols.set(qn("w:num"), "2"); cols.set(qn("w:space"), "360")
    d.styles["Normal"].font.name = "Times New Roman"; d.styles["Normal"].font.size = Pt(10)
    d.styles["Normal"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    d.styles["Heading 1"].font.size = Pt(10); d.styles["Heading 1"].font.bold = True
    d.styles["Caption"].font.size = Pt(8)
    d.add_paragraph("Sample")
    d.save(path)


def rtl(path):
    d = Document()
    d.styles["Normal"].font.name = "Arial"
    rpr = d.styles["Normal"].element.get_or_add_rPr()
    rpr.find(qn("w:rFonts")).set(qn("w:cs"), "Arial")
    # RTL defaults on Normal: rtl run + Arabic bidi language, bidi paragraph (starts at the right edge)
    rtl_el = OxmlElement("w:rtl"); rpr.append(rtl_el)
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang"); rpr.append(lang)
    lang.set(qn("w:bidi"), "ar-SA")
    ppr = d.styles["Normal"].element.get_or_add_pPr()
    ppr.append(OxmlElement("w:bidi"))
    sort_children(rpr, RPR_ORDER); sort_children(ppr, PPR_ORDER)
    d.add_paragraph("هذا نص تجريبي.")
    d.save(path)


def journal(path):
    """Modelled on a real journal template (IJPCR, Phase 9): a full set of custom, prefixed styles
    used by the sample content while Word's built-in Heading N / Caption stay unused, a first-page
    layout in the BODY (banner table, logo image, {{PLACEHOLDERS}}), placeholders in the header and
    nameless table styles."""
    d = Document()
    st = d.styles
    st["Normal"].font.name = "Times New Roman"
    st["Heading 1"].font.name = "Tahoma"; st["Heading 1"].font.size = Pt(10)   # unused built-in, looks wrong

    def para_style(name, size, bold=False, outline=None, first_line=None, align=None):
        s = st.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        s.base_style = st["Normal"]
        s.font.size = Pt(size); s.font.bold = bold or None
        if bold:
            s.font.name = "Trebuchet MS"
        if first_line is not None:
            s.paragraph_format.first_line_indent = Cm(first_line)
        if align is not None:
            s.paragraph_format.alignment = align
        if outline is not None:
            ppr = s.element.get_or_add_pPr()
            ol = OxmlElement("w:outlineLvl"); ol.set(qn("w:val"), str(outline)); ppr.append(ol)
            sort_children(ppr, PPR_ORDER)
        s.quick_style = True
        return s

    for i in (1, 2, 3):
        para_style(f"JRNL Heading {i}", 12, bold=True, outline=i - 1)
    para_style("JRNL Body First", 12, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    para_style("JRNL Body Text", 12, first_line=0.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    para_style("JRNL List Bullet", 12)
    para_style("JRNL Table Caption", 11, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    para_style("JRNL Figure Caption", 11, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    para_style("JRNL Table Text", 10)
    para_style("JRNL Block Quote", 11)
    # nameless table styles, as Word sometimes leaves behind
    for sid in ("a", "a0"):
        el = OxmlElement("w:style"); el.set(qn("w:type"), "table"); el.set(qn("w:styleId"), sid)
        st.element.append(el)
    s = d.sections[0]
    s.header.paragraphs[0].text = "DOI: {{DOI}} | Vol. {{VOLUME}}, Issue {{ISSUE}}"
    _field(s.footer.paragraphs[0], "PAGE")
    # first-page layout in the body: banner table, placeholders, a logo image
    banner = d.add_table(rows=1, cols=2)
    banner.cell(0, 0).text = "RESEARCH ARTICLE"; banner.cell(0, 1).text = "Open Access"
    d.add_paragraph("{{TITLE}}", style="Title")
    d.add_paragraph("{{AUTHORS}}")
    import io
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (400, 200), (20, 40, 120)).save(buf, "PNG")
    d.add_picture(io.BytesIO(buf.getvalue()))
    d.add_paragraph("", style="Heading 1")        # an empty heading-styled spacer inside the layout (as in IJPCR)
    d.add_paragraph("Cite this article: {{TITLE}}, Vol. {{VOLUME}}")
    # sample article using the custom styles
    d.add_paragraph("1. Introduction", style="JRNL Heading 1")
    d.add_paragraph("First paragraph after a heading.", style="JRNL Body First")
    d.add_paragraph("A following paragraph.", style="JRNL Body Text")
    d.add_paragraph("1.1 Background", style="JRNL Heading 2")
    d.add_paragraph("Text.", style="JRNL Body First")
    d.add_paragraph("A point", style="JRNL List Bullet")
    d.add_paragraph("Table 1: Results", style="JRNL Table Caption")
    t = d.add_table(rows=2, cols=2)
    for c in t._cells:
        c.paragraphs[0].style = st["JRNL Table Text"]; c.paragraphs[0].text = "x"
    d.add_paragraph("1.1.1 Detail", style="JRNL Heading 3")
    d.add_paragraph("A long quotation.", style="JRNL Block Quote")
    d.add_paragraph("Figure 1: Map", style="JRNL Figure Caption")
    d.save(path)


BUILDERS = dict(default=default, university=university, messy=messy, bangla=bangla, twocol=twocol, rtl=rtl,
                journal=journal)


def build_all(outdir):
    os.makedirs(outdir, exist_ok=True)
    out = {}
    for name, fn in BUILDERS.items():
        p = os.path.join(outdir, f"{name}.docx")
        fn(p)
        out[name] = p
    return out


if __name__ == "__main__":
    print(build_all(os.path.join(os.path.dirname(__file__), "fixtures")))
