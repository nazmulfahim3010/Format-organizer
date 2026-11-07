"""Every fixture template opens and has the features it exists to exercise."""
import os

import pytest
from docx import Document
from docx.oxml.ns import qn

from tests.make_templates import BUILDERS

COMMITTED = os.path.join(os.path.dirname(__file__), "fixtures")
NAMES = ["default", "university", "messy", "bangla", "twocol", "rtl", "journal"]


def _style_ids(doc):
    return {s.get(qn("w:styleId")) for s in doc.styles.element.findall(qn("w:style"))}


def test_builders_cover_every_fixture():
    assert sorted(BUILDERS) == sorted(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_built_and_committed_fixture_opens(templates, name):
    for path in (templates[name], os.path.join(COMMITTED, f"{name}.docx")):
        doc = Document(path)
        assert doc.sections and doc.element.body.find(qn("w:sectPr")) is not None, path


def test_university_has_header_footer_page_field_and_numbered_headings(templates):
    doc = Document(templates["university"])
    sec = doc.sections[0]
    assert sec.header.paragraphs[0].text == "Metropolitan University - Thesis"
    instr = "".join(t.text for t in sec.footer._element.iter(qn("w:instrText")))
    assert "PAGE" in instr
    for i in (1, 2, 3):
        assert doc.styles[f"Heading {i}"].element.pPr.find(qn("w:numPr")) is not None


def test_messy_has_odd_names_and_no_heading_numbering(templates):
    doc = Document(templates["messy"])
    ids = _style_ids(doc)
    assert not any(i.startswith("Heading") for i in ids)
    names = {s.name for s in doc.styles}
    assert {"bdy txt FINAL", "Normal1", "Para (copy) 2", "zz_old_STYLE"} <= names
    for s in doc.styles.element.findall(qn("w:style")):     # list styles may keep numPr; headings may not
        ppr = s.find(qn("w:pPr"))
        if ppr is not None and ppr.find(qn("w:outlineLvl")) is not None:
            assert ppr.find(qn("w:numPr")) is None, s.get(qn("w:styleId"))


def test_bangla_has_cs_font_localized_names_and_text(templates):
    doc = Document(templates["bangla"])
    assert doc.styles["Normal"].element.rPr.find(qn("w:rFonts")).get(qn("w:cs")) == "Kalpurush"
    assert "শিরোনাম ১" in {s.name for s in doc.styles}
    assert any("ঀ" <= ch <= "৿" for p in doc.paragraphs for ch in p.text)


def test_twocol_has_two_columns(templates):
    cols = Document(templates["twocol"]).sections[0]._sectPr.find(qn("w:cols"))
    assert cols.get(qn("w:num")) == "2"


def test_rtl_has_rtl_defaults_and_arabic_text(templates):
    doc = Document(templates["rtl"])
    normal = doc.styles["Normal"].element
    assert normal.pPr.find(qn("w:bidi")) is not None
    assert normal.rPr.find(qn("w:rtl")) is not None
    assert normal.rPr.find(qn("w:lang")).get(qn("w:bidi")) == "ar-SA"
    assert any("؀" <= ch <= "ۿ" for p in doc.paragraphs for ch in p.text)
