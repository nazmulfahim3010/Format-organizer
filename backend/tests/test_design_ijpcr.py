"""Predefined design: IJPCR research paper. The 16 scenarios of the feature request, plus design versioning."""
import os

import pymupdf
import pytest
from docx import Document
from docx.oxml.ns import qn

from app import designs
from app.core.uploads import check_docx
from app.designs.generator import cite_authors, generate_article, to_content
from app.document_engine.pdf import docx_to_pdf
from app.schemas.article import ArticleContent
from app.template_engine.analyzer import analyze_template
from app.validation.validator import validate_docx
from tests import design_articles as A
from tests.conftest import needs_soffice

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture(scope="module")
def design():
    return designs.load("ijpcr")


@pytest.fixture(scope="module")
def fig(tmp_path_factory):
    return A.make_figure(str(tmp_path_factory.mktemp("fig") / "f.png"))


def make(design, fig, tmp_path, scenario):
    art = ArticleContent.model_validate(scenario() if callable(scenario) else scenario)
    out = str(tmp_path / "article.docx")
    res = generate_article(design, art, lambda a: fig, out)
    return Document(out), res, out, art


def headings(d):
    return [(p.style.style_id, p.text) for p in d.paragraphs if p.style.style_id.startswith("IJPCRHeading")]


def first_page_tables(d):
    return d.tables[:4]          # banner, panel + abstract, citation, logo + licence


def fills(tbl):
    return {s.get(qn("w:fill")) for s in tbl._tbl.iter(qn("w:shd"))}


def border_colours(tbl):
    return {b.get(qn("w:color")) for b in tbl._tbl.iter(qn("w:top"), qn("w:left")) if b.get(qn("w:color"))}


def pdf_pages(out, tmp_path):
    pdf = docx_to_pdf(out, str(tmp_path / "a.pdf"), timeout=180)
    return pymupdf.open(pdf)


# ------------------------------------------------------------------ design package and versions
def test_design_is_registered_and_versioned(design):
    assert design.id == "ijpcr" and design.version == "v1" and "v1" in designs.versions("ijpcr")
    assert designs.load("ijpcr", "v1").data == design.data
    with pytest.raises(designs.DesignNotFound):
        designs.load("ijpcr", "v99")
    with pytest.raises(designs.DesignNotFound):
        designs.load("../etc")


def test_bundled_template_passes_the_upload_checks(design):
    check_docx(open(design.base_path, "rb").read(), "base.docx")


def test_design_profile_contains_no_section_names(design):
    flat = str(design.data["profile"]).lower()
    for name in ("introduction", "conclusion", "methodology", "literature", "results"):
        assert name not in flat


def test_assets_cannot_escape_the_design_folder(design):
    with pytest.raises(designs.DesignNotFound):
        design.asset("../../config.py")


# ------------------------------------------------------------------ 1-4: structure comes from the user
def test_1_short_introduction(design, fig, tmp_path):
    d, res, _, _ = make(design, fig, tmp_path, A.short_intro)
    assert headings(d) == [("IJPCRHeading1", "Introduction")]
    p = next(p for p in d.paragraphs if p.text == "A short introduction.")
    assert p.style.style_id == "IJPCRBodyFirst"


def test_2_multiple_main_sections(design, fig, tmp_path):
    d, _, _, _ = make(design, fig, tmp_path, A.multi_sections)
    h = headings(d)
    assert [t for s, t in h if s == "IJPCRHeading1"] == ["Introduction", "Literature Review", "Research Methodology",
                                                         "Results and Discussion", "Conclusion"]
    assert ("IJPCRHeading2", "Data Collection") in h
    styles = [p.style.style_id for p in d.paragraphs if p.text.startswith("Water scarcity")]
    assert styles[:2] == ["IJPCRBodyFirst", "IJPCRBody"]           # first paragraph, then indented ones


def test_3_deeply_nested_subsections_get_real_numbering(design, fig, tmp_path):
    d, _, out, art = make(design, fig, tmp_path, A.deep_nesting)
    h = headings(d)
    assert [s for s, _ in h[:5]] == ["IJPCRHeading1", "IJPCRHeading2", "IJPCRHeading3", "IJPCRHeading4", "IJPCRHeading5"]
    # each level is a level of one generated multilevel list (1 / 1.1 / 1.1.1 / 1.1.1.1 / 1.1.1.1.1)
    num = d.part.numbering_part.element
    linked = {l.find(qn("w:pStyle")).get(qn("w:val")): (l.get(qn("w:ilvl")), l.find(qn("w:lvlText")).get(qn("w:val")))
              for a in num.findall(qn("w:abstractNum")) for l in a.findall(qn("w:lvl"))
              if l.find(qn("w:pStyle")) is not None and l.find(qn("w:pStyle")).get(qn("w:val")).startswith("IJPCRHeading")}
    assert linked["IJPCRHeading1"] == ("0", "%1.") and linked["IJPCRHeading5"] == ("4", "%1.%2.%3.%4.%5")
    rep = validate(design, art, out)
    assert rep["list_numbering"]["status"] == "passed" and rep["heading_hierarchy"]["status"] == "passed"


def test_4_any_section_order(design, fig, tmp_path):
    d, _, _, _ = make(design, fig, tmp_path, A.different_order)
    assert [t for _, t in headings(d)] == ["Conclusion First", "Background", "Methods"]


# ------------------------------------------------------------------ 5-7: first-page metadata
def test_5_one_author(design, fig, tmp_path):
    d, _, _, _ = make(design, fig, tmp_path, A.short_intro)
    authors = next(p for p in d.paragraphs if p.text.startswith("Rahima Akter"))
    sup = [r.text for r in authors.runs if r.font.superscript]
    assert sup == ["1*"]
    assert any(h.get(qn("r:id")) for h in authors._p.iter(qn("w:hyperlink")))      # ORCID link
    cite = first_page_tables(d)[2].cell(0, 0).text
    assert cite.startswith("Cite this article: Akter, R. (2026). Water Scarcity")
    assert "01(04), 12-27. 10.5281/ijpcr.2026.0142" in cite


def test_6_multiple_authors_and_affiliations(design, fig, tmp_path):
    d, _, _, art = make(design, fig, tmp_path, A.many_authors)
    authors = next(p for p in d.paragraphs if p.text.startswith("Rahima Akter"))
    assert authors.text.count(",") >= 5 and "Arif Chowdhury" in authors.text
    panel = first_page_tables(d)[1].cell(0, 0).text
    for i in (1, 2, 3):
        assert f"{i} Department {i}, University {i}, Bangladesh" in panel
    assert cite_authors(art.metadata.authors).endswith("Jahan, N. and Chowdhury, A.")


def test_7_long_abstract_is_complete_and_the_box_grows(design, fig, tmp_path):
    d, _, out, art = make(design, fig, tmp_path, A.long_abstract)
    box = first_page_tables(d)[1].cell(0, 1).text
    assert box.startswith("Abstract") and art.abstract[-60:] in box
    h = first_page_tables(d)[1].rows[0]._tr.find(f"{W}trPr/{W}trHeight")
    assert h.get(qn("w:hRule")) == "atLeast"                                     # a minimum, never a fixed height


# ------------------------------------------------------------------ 8-9: tables and figures
def test_8_9_many_tables_and_figures_are_numbered_and_captioned(design, fig, tmp_path):
    d, res, out, art = make(design, fig, tmp_path, A.many_tables_figures)
    caps = [(p.style.style_id, p.text) for p in d.paragraphs if p.text.startswith(("Table ", "Figure "))]
    assert [t for _, t in caps if t.startswith("Table")] == [f"Table {i}: Result set {i}" for i in range(1, 5)]
    assert [t for _, t in caps if t.startswith("Figure")] == [f"Figure {i}: Chart {i}" for i in range(1, 5)]
    assert {s for s, t in caps if t.startswith("Table")} == {"IJPCRTableCaption"}
    assert {s for s, t in caps if t.startswith("Figure")} == {"IJPCRFigureCaption"}
    rep = validate(design, art, out)
    for cid in ("table_captions", "figure_captions", "numbering_continuity", "table_fit", "figure_fit"):
        assert rep[cid]["status"] == "passed", (cid, rep[cid])


def test_10_references_and_declarations(design, fig, tmp_path):
    d, _, _, art = make(design, fig, tmp_path, A.long_references)
    texts = [(p.style.style_id, p.text) for p in d.paragraphs]
    decl = [t for s, t in texts if s == "IJPCRDeclHeading"]
    assert decl == ["Acknowledgements", "Declaration of Competing Interest",
                    "Declaration of Generative AI and AI-assisted technologies in the writing process", "Funding"]
    assert ("IJPCRRefHeading", "References") in texts
    assert len([1 for s, _ in texts if s == "IJPCRReference"]) == 90


def test_optional_back_matter_is_left_out(design, fig, tmp_path):
    art = A.short_intro()
    art["back_matter"] = {"funding": "Funded by X."}
    d, _, _, _ = make(design, fig, tmp_path, art)
    assert [p.text for p in d.paragraphs if p.style.style_id == "IJPCRDeclHeading"] == ["Funding"]
    assert not [p for p in d.paragraphs if p.style.style_id == "IJPCRRefHeading"]


def test_11_short_document_without_metadata(design, fig, tmp_path):
    d, res, out, art = make(design, fig, tmp_path, A.short_document)
    panel = first_page_tables(d)[1].cell(0, 0).text
    assert "Received" not in panel and "Corresponding" not in panel                # no empty labels
    assert "{{" not in d.sections[0].header.paragraphs[0].text                    # header placeholders emptied
    assert "Only one paragraph." in [p.text for p in d.paragraphs]


# ------------------------------------------------------------------ 14-16: design elements and consistency
def test_14_header_and_footer_are_the_templates(design, fig, tmp_path):
    d, _, _, _ = make(design, fig, tmp_path, A.short_intro)
    hdr = " ".join(p.text for p in d.sections[0].header.paragraphs)
    assert "DOI: 10.5281/ijpcr.2026.0142" in hdr and "Vol. 01, Issue 04, pp. 12-27, 2026" in hdr
    assert "International Journal of Peace and Conflict Research (IJPCR)" in hdr
    assert "PAGE" in "".join(t.text for t in d.sections[0].footer._element.iter(qn("w:instrText")))
    pg = d.sections[0]
    assert (round(pg.page_width / 360000, 2), round(pg.page_height / 360000, 2)) == (21.01, 28.01)


def test_15_first_page_design_elements(design, fig, tmp_path):
    d, _, _, _ = make(design, fig, tmp_path, A.multi_sections)
    banner, panel, cite, logo = first_page_tables(d)
    assert fills(banner) == {"003366"} and [c.text for c in banner.rows[0].cells] == ["RESEARCH ARTICLE", "Open Access"]
    assert "003366" in border_colours(panel) and panel.cell(0, 1).text.startswith("Abstract")
    assert fills(cite) == {"DAE5F1"} and "1F3863" in border_colours(cite)
    assert logo.cell(0, 0)._tc.find(f".//{W}drawing") is not None
    assert "Creative Commons Attribution 4.0" in logo.cell(0, 1).text
    title = next(p for p in d.paragraphs if p.text.startswith("Water Scarcity"))
    assert title.runs[0].font.name == "Trebuchet MS" and title.runs[0].font.size.pt == 18 and title.runs[0].bold


def test_16_body_uses_only_design_styles_and_passes_the_checks(design, fig, tmp_path):
    d, res, out, art = make(design, fig, tmp_path, A.multi_sections)
    paras = d.paragraphs
    start = next(i for i, p in enumerate(paras) if p.text == "Introduction")
    body_styles = {p.style.style_id for p in paras[start:] if p.text.strip()}
    assert body_styles <= {"IJPCRHeading1", "IJPCRHeading2", "IJPCRBody", "IJPCRBodyFirst", "IJPCRListBullet",
                           "IJPCRTableCaption", "IJPCRFigureCaption", "IJPCRDeclHeading", "IJPCRDeclText",
                           "IJPCRRefHeading", "IJPCRReference", "SmartDocNote"}, body_styles
    rep = validate(design, art, out)
    assert [c for c, v in rep.items() if v["status"] == "failed"] == []


def validate(design, art, out):
    a = analyze_template(design.base_path)
    report = validate_docx(out, design.profile, to_content(art, design), a["page"], analysis=a)
    return {c["id"]: c for c in report["checks"]}


# ------------------------------------------------------------------ rendered: 7, 10, 12, 13, 15 by page images
@needs_soffice
def test_7_rendered_long_abstract_never_overlaps(design, fig, tmp_path):
    d, _, out, _ = make(design, fig, tmp_path, A.long_abstract)
    pages = pdf_pages(out, tmp_path)
    p1 = pages[0]
    abstract_end = p1.search_for("decide whether a dry season ends")[-1]
    cite = p1.search_for("Cite this article") or pages[1].search_for("Cite this article")
    on_same_page = bool(p1.search_for("Cite this article"))
    assert not on_same_page or cite[0].y0 > abstract_end.y1                      # citation box below the abstract


@needs_soffice
def test_12_13_long_document_paginates_with_header_and_numbers(design, fig, tmp_path):
    d, _, out, _ = make(design, fig, tmp_path, A.long_document)
    pages = pdf_pages(out, tmp_path)
    assert pages.page_count >= 8
    for i, page in enumerate(pages, 1):
        text = page.get_text()
        assert "International Journal of Peace and Conflict Research (IJPCR)" in text, i
        assert str(i) in text.split()[-3:] or str(i) in text.split(), i              # footer page number
    assert pages[1].search_for("CHAPTER 1")                                          # body starts on page 2


@needs_soffice
def test_10_rendered_references_span_pages_with_hanging_indent(design, fig, tmp_path):
    d, _, out, _ = make(design, fig, tmp_path, A.long_references)
    pages = pdf_pages(out, tmp_path)
    ref_pages = [i for i, p in enumerate(pages) if p.search_for("about water governance")]
    assert len(ref_pages) >= 2
    page = pages[ref_pages[0]]
    first_lines = [b for b in page.get_text("blocks") if "about water governance" in b[4]]
    # wrapped lines of an entry start further right than its first line (1.27 cm hanging indent)
    lines = [l for b in page.get_text("dict")["blocks"] for l in b.get("lines", [])]
    xs = sorted({round(l["bbox"][0]) for l in lines if l["spans"] and "Available" not in l["spans"][0]["text"]})
    assert first_lines and len(xs) >= 2 and xs[1] - xs[0] > 25


@needs_soffice
def test_15_rendered_first_page_holds_the_whole_masthead(design, fig, tmp_path):
    d, _, out, _ = make(design, fig, tmp_path, A.multi_sections)
    p1 = pdf_pages(out, tmp_path)[0]
    for text in ("RESEARCH ARTICLE", "Open Access", "Abstract", "Keywords", "Cite this article", "ISSN: 3108-6136",
                 "Creative Commons Attribution 4.0"):
        assert p1.search_for(text), text
    assert not p1.search_for("INTRODUCTION")                                          # body on the next page
