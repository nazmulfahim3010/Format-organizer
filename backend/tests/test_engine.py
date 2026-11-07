import os
import zipfile

import pytest
from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from app.document_engine.pdf import docx_to_pdf
from app.document_engine.generator import (PPR_ORDER, RPR_ORDER, TBLPR_ORDER, TCPR_ORDER, generate_docx)
from app.schemas.content import DocumentContent
from app.template_engine.analyzer import analyze_template, build_default_profile
from app.validation.validator import validate_docx
from tests.conftest import needs_soffice
from tests.sample import sample_content

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def build(templates, image, name, lang="en", tweak=None, content=None, tmp=None):
    a = analyze_template(templates[name])
    prof = build_default_profile(a, name)
    if tweak:
        tweak(prof)
    c = content or sample_content(lang)
    out = os.path.join(tmp, f"{name}.docx")
    res = generate_docx(templates[name], prof, c, lambda aid: image if aid == "img1" else None, out)
    return a, prof, c, res, out


# ------------------------------------------------------------------ analyzer
def test_analyzer_roles_and_health(templates):
    a = analyze_template(templates["university"])
    assert a["suggested_roles"]["heading_1"] == "Heading1"
    assert a["heading_numbering_in_template"] is True
    assert a["header_footer"]["footer_has_page_number"] is True
    assert a["page"]["margins_cm"]["left"] == 3.8
    assert a["tables"][0]["style_id"] == "TableGrid" and a["tables"][0]["caption_position"] == "below"

    m = analyze_template(templates["messy"])
    codes = {h["code"] for h in m["health"]}
    assert {"NO_HEADING_STYLES", "HEAVY_DIRECT_FORMATTING", "NO_CAPTION_STYLE"} <= codes
    assert not any(k.startswith("heading_") for k in m["suggested_roles"])

    t = analyze_template(templates["twocol"])
    assert t["page"]["columns"] == 2 and "MULTI_COLUMN" in {h["code"] for h in t["health"]}

    b = analyze_template(templates["bangla"])
    assert b["language"]["text_script"] == "complex" and b["language"]["normal_cs_font"] == "Kalpurush"
    # localized style display names are still found through ids / outline levels
    assert b["suggested_roles"]["heading_1"] == "Heading1" and b["suggested_roles"]["caption"] == "Caption"
    assert analyze_template(templates["rtl"])["language"]["text_script"] == "rtl"


def test_default_profile_records_origins(templates):
    p = build_default_profile(analyze_template(templates["university"]))
    assert p.table.caption_position == "below" and p.origins["table.caption_position"] == "inferred"
    assert p.table.borders == "template" and p.table.template_style_id == "TableGrid"
    assert p.heading_numbering == "template"


# ------------------------------------------------------------------ generator on every template
@pytest.mark.parametrize("name", ["default", "university", "messy", "bangla", "twocol", "rtl"])
def test_generates_valid_document_for_every_template(templates, image, tmp_path, name):
    lang = {"bangla": "bn", "rtl": "ar"}.get(name, "en")
    a, prof, c, res, out = build(templates, image, name, lang, tmp=str(tmp_path),
                                 tweak=(lambda p: setattr(p, "heading_numbering", "auto")) if name == "messy" else None)
    assert res.stats["tables"] == 3 and res.stats["figures"] == 1 and res.stats["sections"] == 4
    d = Document(out)
    assert len(d.tables) == 3
    rep = validate_docx(out, prof, c, a["page"])
    failed = [(c_["id"], c_["details"]) for c_ in rep["checks"] if c_["status"] == "failed"]
    assert not failed, failed


@pytest.mark.parametrize("name", ["default", "university", "messy", "bangla", "twocol", "rtl"])
def test_xml_child_order_is_schema_valid(templates, image, tmp_path, name):
    """Word rejects/repairs files whose property children are out of schema order."""
    lang = {"bangla": "bn", "rtl": "ar"}.get(name, "en")
    *_, out = build(templates, image, name, lang, tmp=str(tmp_path))
    root = etree.fromstring(zipfile.ZipFile(out).read("word/document.xml"))
    for tag, order in (("rPr", RPR_ORDER), ("pPr", PPR_ORDER), ("tblPr", TBLPR_ORDER), ("tcPr", TCPR_ORDER)):
        rank = {f"{{{W}}}{n}": i for i, n in enumerate(order)}
        for el in root.iter(f"{{{W}}}{tag}"):
            seq = [rank[c.tag] for c in el if c.tag in rank]
            assert seq == sorted(seq), (tag, [etree.QName(c).localname for c in el])


def test_template_parts_are_preserved(templates, image, tmp_path):
    *_, out = build(templates, image, "university", tmp=str(tmp_path))
    d = Document(out)
    s = d.sections[-1]
    assert s.header.paragraphs[0].text == "Metropolitan University - Thesis"
    assert "PAGE" in etree.tostring(s.footer._element).decode()
    assert round(s.left_margin / 360000, 1) == 3.8
    assert "Sample body text" not in "\n".join(p.text for p in d.paragraphs)      # sample content removed


def test_template_numbered_headings_are_real_numbering_not_typed(templates, image, tmp_path):
    *_, out = build(templates, image, "university", tmp=str(tmp_path))
    d = Document(out)
    heads = [p for p in d.paragraphs if p.style.style_id.startswith("Heading")]
    assert [p.text for p in heads][:2] == ["Introduction", "Motivation"]            # no "1." typed into the text


def test_auto_heading_numbering_links_styles(templates, image, tmp_path):
    a, prof, c, res, out = build(templates, image, "messy", tmp=str(tmp_path),
                                 tweak=lambda p: setattr(p, "heading_numbering", "auto"))
    d = Document(out)
    num = d.part.numbering_part.element
    linked = [e.get(qn("w:val")) for e in num.iter(qn("w:pStyle"))]
    assert "Heading1" in linked and "Heading3" in linked
    assert "HEADING_STYLE_CREATED" in {w["code"] for w in res.warnings}            # messy template had none
    st = {s.style_id: s for s in d.styles}["Heading1"]
    assert st.element.find(f"{qn('w:pPr')}/{qn('w:numPr')}") is not None


def test_heading_numbering_none_suppresses_template_numbers(templates, image, tmp_path):
    *_, out = build(templates, image, "university", tmp=str(tmp_path),
                    tweak=lambda p: setattr(p, "heading_numbering", "none"))
    d = Document(out)
    h = [p for p in d.paragraphs if p.style.style_id == "Heading1"][0]
    assert h._p.find(f"{qn('w:pPr')}/{qn('w:numPr')}/{qn('w:numId')}").get(qn("w:val")) == "0"


def test_captions_use_seq_fields_with_cached_numbers(templates, image, tmp_path):
    a, prof, c, res, out = build(templates, image, "default", tmp=str(tmp_path))
    xml = zipfile.ZipFile(out).read("word/document.xml").decode()
    assert xml.count("SEQ Table") == 3 and xml.count("SEQ Figure") == 1
    d = Document(out)
    caps = [p.text for p in d.paragraphs if p.style.style_id == "Caption"]
    assert caps[0] == "Table 1: Experimental results" and caps[-1] == "Table 3: Wide"
    assert any(t.startswith("Figure 1: System architecture") for t in caps)


def test_caption_position_follows_the_locked_rule(templates, image, tmp_path):
    def below(p):
        p.table.caption_position = "below"
    a, prof, c, res, out = build(templates, image, "default", tmp=str(tmp_path), tweak=below)
    body = list(Document(out).element.body)
    i = next(k for k, el in enumerate(body) if el.tag == qn("w:tbl"))
    assert "SEQ Table" in etree.tostring(body[i + 1]).decode() and "SEQ" not in etree.tostring(body[i - 1]).decode()


def test_table_rules_applied(templates, image, tmp_path):
    a, prof, c, res, out = build(templates, image, "default", tmp=str(tmp_path))
    d = Document(out)
    t = d.tables[0]
    pr = t._tbl.tblPr
    assert pr.find(qn("w:jc")).get(qn("w:val")) == "center"
    assert pr.find(qn("w:tblBorders")) is not None
    hdr = t.rows[0]._tr
    assert hdr.find(f"{qn('w:trPr')}/{qn('w:tblHeader')}") is not None
    assert hdr.find(f".//{qn('w:shd')}").get(qn("w:fill")) == "D9D9D9"
    assert all(r.bold for r in t.rows[0].cells[0].paragraphs[0].runs)
    assert "TABLE_WIDE" in {w["code"] for w in res.warnings}                         # 8 columns -> smaller font
    # widths add up to the text width
    grid = [int(g.get(qn("w:w"))) for g in t._tbl.find(qn("w:tblGrid")).findall(qn("w:gridCol"))]
    assert abs(sum(grid) - int(pr.find(qn("w:tblW")).get(qn("w:w")))) <= 1


def test_two_tables_in_a_row_do_not_merge(templates, image, tmp_path):
    c = DocumentContent.model_validate({"body": [{"type": "section", "title": "S", "content": [
        {"type": "table", "caption": "a", "data": [["1"]]}, {"type": "table", "caption": "b", "data": [["2"]]}]}]})
    a, prof, c, res, out = build(templates, image, "default", content=c, tmp=str(tmp_path),
                                 tweak=lambda p: setattr(p.table, "caption_position", "below"))
    assert len(Document(out).tables) == 2


def test_ordered_lists_restart_and_nest(templates, image, tmp_path):
    a, prof, c, res, out = build(templates, image, "default", tmp=str(tmp_path))
    d = Document(out)
    ids = []
    for p in d.paragraphs:
        n = p._p.find(f"{qn('w:pPr')}/{qn('w:numPr')}")
        if n is not None and p.text in ("One", "Restart-one"):
            ids.append(n.find(qn("w:numId")).get(qn("w:val")))
    assert len(ids) == 2 and ids[0] != ids[1]                                         # second list restarts at 1
    nested = [p for p in d.paragraphs if p.text == "Two-a"][0]
    assert nested._p.find(f"{qn('w:pPr')}/{qn('w:numPr')}/{qn('w:ilvl')}").get(qn("w:val")) == "1"
    num = d.part.numbering_part.element
    assert any(o.find(qn("w:startOverride")) is not None for o in num.iter(qn("w:lvlOverride")))


def _level_def(d, num_id, ilvl):
    root = d.part.numbering_part.element
    num = [n for n in root.findall(qn("w:num")) if n.get(qn("w:numId")) == num_id][0]
    aid = num.find(qn("w:abstractNumId")).get(qn("w:val"))
    ab = [a for a in root.findall(qn("w:abstractNum")) if a.get(qn("w:abstractNumId")) == aid][0]
    lv = [l for l in ab.findall(qn("w:lvl")) if l.get(qn("w:ilvl")) == ilvl]
    return lv[0] if lv else None


@pytest.mark.parametrize("name", ["default", "university", "bangla", "twocol", "rtl", "messy"])
def test_nested_list_levels_are_defined_and_keep_list_kind(templates, image, tmp_path, name):
    # template List Bullet/List Number numbering is often singleLevel; nested items must not hit undefined levels
    a, prof, c, res, out = build(templates, image, name, tmp=str(tmp_path))
    d = Document(out)
    for text, bullet in (("Alpha-1", True), ("Two-a", False)):
        p = [p for p in d.paragraphs if p.text == text][0]
        np_ = p._p.find(f"{qn('w:pPr')}/{qn('w:numPr')}")
        lv = _level_def(d, np_.find(qn("w:numId")).get(qn("w:val")), np_.find(qn("w:ilvl")).get(qn("w:val")))
        assert lv is not None, f"{name}: level for {text} undefined"
        assert (lv.find(qn("w:numFmt")).get(qn("w:val")) == "bullet") == bullet
    for p in d.paragraphs:                                                            # no list item hits an undefined level
        np_ = p._p.find(f"{qn('w:pPr')}/{qn('w:numPr')}")
        if np_ is not None and np_.find(qn("w:numId")).get(qn("w:val")) != "0":
            assert _level_def(d, np_.find(qn("w:numId")).get(qn("w:val")), np_.find(qn("w:ilvl")).get(qn("w:val"))) is not None


def test_generated_lists_when_template_has_no_list_styles(templates, image, tmp_path):
    a, prof, c, res, out = build(templates, image, "messy", tmp=str(tmp_path))
    d = Document(out)
    item = [p for p in d.paragraphs if p.text == "Alpha"][0]
    assert item._p.find(f"{qn('w:pPr')}/{qn('w:numPr')}") is not None


def test_inline_markup_becomes_runs(templates, image, tmp_path):
    *_, out = build(templates, image, "default", tmp=str(tmp_path))
    d = Document(out)
    ab = [p for p in d.paragraphs if "tests" in p.text and "Abstract" in p.text][0]
    assert any(r.bold and r.text == "bold" for r in ab.runs)
    assert any(r.font.subscript and r.text == "2" for r in ab.runs)
    assert any(r.font.superscript and r.text == "2" for r in ab.runs)


def test_figure_scaled_into_column_width(templates, image, tmp_path):
    *_, out = build(templates, image, "twocol", tmp=str(tmp_path))
    d = Document(out)
    shape = d.inline_shapes[0]
    col_cm = (21.59 - 2 * 1.9 - 0.635) / 2        # text width minus gap, over two columns
    assert shape.width / 360000 <= col_cm + 0.05
    assert abs(shape.width / shape.height - 1200 / 700) < 0.01                        # aspect ratio kept


def test_two_column_layout_preserved_and_tables_fit_the_column(templates, image, tmp_path):
    *_, out = build(templates, image, "twocol", tmp=str(tmp_path))
    d = Document(out)
    cols = d.sections[-1]._sectPr.find(qn("w:cols"))
    assert cols.get(qn("w:num")) == "2"
    w = int(d.tables[0]._tbl.tblPr.find(qn("w:tblW")).get(qn("w:w")))
    assert w < 5000                                                                    # ~one column, not the full page


def test_complex_script_properties_for_bangla(templates, image, tmp_path):
    a, prof, c, res, out = build(templates, image, "bangla", "bn", tmp=str(tmp_path))
    xml = zipfile.ZipFile(out).read("word/document.xml").decode()
    assert 'w:cs="Kalpurush"' in xml and "<w:bCs/>" in xml and 'w:bidi="bn"' in xml
    styles = zipfile.ZipFile(out).read("word/styles.xml").decode()
    assert 'w:bidi="bn"' in styles        # document language default set in the complex-script slot (Phase 3)


def test_rtl_document_gets_bidi_everywhere(templates, image, tmp_path):
    *_, out = build(templates, image, "rtl", "ar", tmp=str(tmp_path))
    d = Document(out)
    assert d.tables[0]._tbl.tblPr.find(qn("w:bidiVisual")) is not None
    assert all(p._p.find(f"{qn('w:pPr')}/{qn('w:bidi')}") is not None for p in d.paragraphs if p.text.strip())


def test_east_asian_font_applied(templates, image, tmp_path):
    c = DocumentContent.model_validate({"language": "zh", "title": "你好世界", "body": []})
    def tw(p): p.language.east_asian_font = "SimSun"
    *_, out = build(templates, image, "default", content=c, tmp=str(tmp_path), tweak=tw)
    assert 'w:eastAsia="SimSun"' in zipfile.ZipFile(out).read("word/document.xml").decode()


# ------------------------------------------------------------------ robustness / fallbacks
def test_missing_image_and_bad_style_mapping_warn_but_do_not_fail(templates, image, tmp_path):
    def tw(p): p.roles["heading_1"] = "NoSuchStyle"
    a, prof, c, res, out = build(templates, image, "default", tmp=str(tmp_path), tweak=tw,
                                 content=DocumentContent.model_validate({"body": [{"type": "section", "title": "A", "content": [
                                     {"type": "figure", "asset_id": "nope", "caption": "x"}]}]}))
    codes = {w["code"] for w in res.warnings}
    assert {"STYLE_NOT_FOUND", "FIGURE_MISSING"} <= codes
    assert Document(out).paragraphs


def test_corrupt_image_does_not_abort_generation(templates, tmp_path):
    bad = tmp_path / "bad.png"; bad.write_bytes(b"not an image")
    a = analyze_template(templates["default"]); prof = build_default_profile(a)
    c = DocumentContent.model_validate({"body": [{"type": "figure", "asset_id": "x", "caption": "c"}]})
    res = generate_docx(templates["default"], prof, c, lambda _: str(bad), str(tmp_path / "o.docx"))
    assert "FIGURE_UNREADABLE" in {w["code"] for w in res.warnings}


def test_depth_beyond_nine_levels_warns(templates, image, tmp_path):
    node = {"type": "section", "title": "leaf", "content": []}
    for i in range(10):
        node = {"type": "section", "title": f"L{i}", "content": [node]}
    c = DocumentContent.model_validate({"body": [node]})
    *_, res, out = build(templates, image, "default", content=c, tmp=str(tmp_path))
    assert "DEPTH_LIMIT" in {w["code"] for w in res.warnings}


def test_empty_content_still_produces_a_valid_file(templates, image, tmp_path):
    *_, out = build(templates, image, "university", content=DocumentContent(), tmp=str(tmp_path))
    Document(out)


# ------------------------------------------------------------------ validator catches real defects
def test_validator_detects_missing_caption_and_bad_numbers(templates, image, tmp_path):
    a, prof, c, res, out = build(templates, image, "default", tmp=str(tmp_path))
    d = Document(out)
    cap = [p for p in d.paragraphs if p.style.style_id == "Caption"][0]
    cap._p.getparent().remove(cap._p)
    bad = str(tmp_path / "bad.docx"); d.save(bad)
    rep = validate_docx(bad, prof, c, a["page"])
    st = {x["id"]: x for x in rep["checks"]}
    assert st["table_captions"]["status"] == "failed"
    assert st["numbering_continuity"]["status"] == "failed"      # SEQ now starts at 2


def test_validator_detects_page_change_and_required_sections(templates, image, tmp_path):
    a, prof, c, res, out = build(templates, image, "default", tmp=str(tmp_path),
                                 tweak=lambda p: setattr(p, "required_sections", ["Introduction", "Conclusion"]))
    d = Document(out)
    d.sections[-1].left_margin = d.sections[-1].left_margin + 360000
    p2 = str(tmp_path / "m.docx"); d.save(p2)
    rep = validate_docx(p2, prof, c, a["page"])
    st = {x["id"]: x for x in rep["checks"]}
    assert st["page_setup"]["status"] == "failed"
    assert st["required_sections"]["status"] == "failed" and "Conclusion" in st["required_sections"]["details"][0]
    assert any(x["status"] == "manual" and x["kind"] == "visual" for x in rep["checks"])


@needs_soffice
@pytest.mark.parametrize("name", ["university", "twocol", "messy", "bangla"])
def test_libreoffice_opens_and_renders(templates, image, tmp_path, name):
    lang = "bn" if name == "bangla" else "en"
    *_, out = build(templates, image, name, lang, tmp=str(tmp_path))
    pdf = docx_to_pdf(out, str(tmp_path / f"{name}.pdf"), timeout=150)
    assert os.path.getsize(pdf) > 5000
