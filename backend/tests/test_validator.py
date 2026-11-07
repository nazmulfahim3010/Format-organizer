"""Phase 5: validator checks. Each test starts from a good generated document and breaks one thing."""
import pytest
from docx import Document
from docx.oxml.ns import qn

from app.document_engine.generator import generate_docx
from app.schemas.content import DocumentContent
from app.template_engine.analyzer import analyze_template, build_default_profile
from app.validation.validator import STATUSES, validate_docx
from tests.sample import sample_content

ALL = ["default", "university", "messy", "bangla", "twocol", "rtl", "journal"]
LANG = {"bangla": "bn", "rtl": "ar"}


def make(templates, image, name, tmp_path, content=None, tweak=None):
    a = analyze_template(templates[name])
    prof = build_default_profile(a, name)
    if tweak:
        tweak(prof)
    c = content or sample_content(LANG.get(name, "en"))
    out = str(tmp_path / f"{name}.docx")
    generate_docx(templates[name], prof, c, lambda x: image if x == "img1" else None, out)
    return a, prof, c, out


def report(a, prof, c, path):
    return validate_docx(path, prof, c, a["page"], analysis=a)


def by_id(rep):
    return {x["id"]: x for x in rep["checks"]}


def broken(out, tmp_path, fn, name="bad.docx"):
    d = Document(out)
    fn(d)
    p = str(tmp_path / name)
    d.save(p)
    return p


# ------------------------------------------------------------------ report shape
@pytest.mark.parametrize("name", ALL)
def test_good_documents_have_no_failed_checks(templates, image, tmp_path, name):
    a, prof, c, out = make(templates, image, name, tmp_path)
    rep = report(a, prof, c, out)
    failed = [(x["id"], x["details"]) for x in rep["checks"] if x["status"] == "failed"]
    assert failed == []
    st = by_id(rep)
    for cid in ("header_footer", "list_numbering", "xml_order", "table_fit", "figure_fit", "caption_labels"):
        assert st[cid]["status"] in ("passed", "info"), (cid, st[cid])


def test_report_shape_has_no_score(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "university", tmp_path)
    rep = report(a, prof, c, out)
    assert set(rep) == {"checks", "summary"}
    assert set(rep["summary"]) == set(STATUSES)
    assert sum(rep["summary"].values()) == len(rep["checks"])
    for x in rep["checks"]:
        assert x["status"] in STATUSES and x["kind"] in ("auto", "visual")
        assert set(x) == {"id", "title", "status", "kind", "details"}
        assert all(isinstance(d, str) for d in x["details"])
    assert len({x["id"] for x in rep["checks"]}) == len(rep["checks"])
    assert all(x["status"] == "manual" for x in rep["checks"] if x["kind"] == "visual")
    flat = str(rep).lower()
    assert "score" not in flat and "percent" not in flat and "%" not in flat


# ------------------------------------------------------------------ headers / footers
def test_header_removed_is_detected(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "university", tmp_path)

    def drop_header(d):
        sp = d.element.body.find(qn("w:sectPr"))
        for ref in sp.findall(qn("w:headerReference")):
            sp.remove(ref)
    st = by_id(report(a, prof, c, broken(out, tmp_path, drop_header)))
    assert st["header_footer"]["status"] == "failed"
    assert any("header" in d.lower() for d in st["header_footer"]["details"])


def test_page_number_field_removed_is_detected(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "university", tmp_path)

    def drop_field(d):
        ftr = d.sections[-1].footer._element
        for it in list(ftr.iter(qn("w:instrText"))):
            it.getparent().getparent().remove(it.getparent())
    st = by_id(report(a, prof, c, broken(out, tmp_path, drop_field)))
    assert st["header_footer"]["status"] == "failed"
    assert any("page number" in d.lower() for d in st["header_footer"]["details"])


def test_columns_change_is_a_page_setup_failure(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "twocol", tmp_path)
    p = broken(out, tmp_path, lambda d: d.element.body.find(qn("w:sectPr")).find(qn("w:cols")).set(qn("w:num"), "1"))
    st = by_id(report(a, prof, c, p))
    assert st["page_setup"]["status"] == "failed" and any("columns" in d for d in st["page_setup"]["details"])


# ------------------------------------------------------------------ numbering
def test_list_pointing_to_missing_numbering_fails(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "default", tmp_path)

    def bad_num(d):
        p = next(p for p in d.paragraphs if p.text == "Alpha")
        p._p.pPr.find(qn("w:numPr")).find(qn("w:numId")).set(qn("w:val"), "999")
    st = by_id(report(a, prof, c, broken(out, tmp_path, bad_num)))
    assert st["list_numbering"]["status"] == "failed" and "Alpha" in " ".join(st["list_numbering"]["details"])


def test_list_level_not_defined_fails(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "default", tmp_path)

    def drop_level(d):
        p = next(p for p in d.paragraphs if p.text == "Alpha-1")
        nid = p._p.pPr.find(qn("w:numPr")).find(qn("w:numId")).get(qn("w:val"))
        num = d.part.numbering_part.element
        aid = next(n for n in num.findall(qn("w:num")) if n.get(qn("w:numId")) == nid).find(qn("w:abstractNumId")).get(qn("w:val"))
        ab = next(x for x in num.findall(qn("w:abstractNum")) if x.get(qn("w:abstractNumId")) == aid)
        for lv in ab.findall(qn("w:lvl")):
            if lv.get(qn("w:ilvl")) == "1":
                ab.remove(lv)
    st = by_id(report(a, prof, c, broken(out, tmp_path, drop_level)))
    assert st["list_numbering"]["status"] == "failed"


def test_typed_numbers_on_top_of_real_numbering_warn(templates, image, tmp_path):
    c = DocumentContent.model_validate({"body": [
        {"type": "section", "title": "1. Introduction", "content": [{"type": "paragraph", "text": "x"}]},
        {"type": "section", "title": "Methods", "content": [
            {"type": "list", "ordered": True, "items": [{"text": "1) first"}, {"text": "second"}]}]}]})
    a, prof, c, out = make(templates, image, "university", tmp_path, content=c)
    st = by_id(report(a, prof, c, out))
    assert st["typed_numbering"]["status"] == "warning"
    assert any("1. Introduction" in d for d in st["typed_numbering"]["details"])
    assert any("1) first" in d for d in st["typed_numbering"]["details"])


def test_no_typed_numbers_passes(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "university", tmp_path)
    assert by_id(report(a, prof, c, out))["typed_numbering"]["status"] == "passed"


# ------------------------------------------------------------------ XML order
def test_out_of_order_xml_fails(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "university", tmp_path)

    def misorder(d):
        p = next(p for p in d.paragraphs if p.text == "Alpha")._p    # pPr has pStyle + numPr
        ppr = p.pPr
        ps = ppr.find(qn("w:pStyle"))
        ppr.remove(ps); ppr.append(ps)               # pStyle must be first
    st = by_id(report(a, prof, c, broken(out, tmp_path, misorder)))
    assert st["xml_order"]["status"] == "failed" and "pPr" in st["xml_order"]["details"][0]


# ------------------------------------------------------------------ fit
def test_figure_wider_than_column_fails(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "twocol", tmp_path)

    def widen(d):
        ext = next(d.element.body.iter("{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent"))
        ext.set("cx", str(int(ext.get("cx")) * 3))
    st = by_id(report(a, prof, c, broken(out, tmp_path, widen)))
    assert st["figure_fit"]["status"] == "failed"


def test_table_wider_than_column_fails(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "twocol", tmp_path)

    def widen(d):
        d.tables[0]._tbl.tblPr.find(qn("w:tblW")).set(qn("w:w"), "12000")
    st = by_id(report(a, prof, c, broken(out, tmp_path, widen)))
    assert st["table_fit"]["status"] == "failed"


def test_missing_image_placeholder_warns(templates, image, tmp_path):
    c = DocumentContent.model_validate({"body": [{"type": "figure", "asset_id": "nope", "caption": "Missing"}]})
    a, prof, c, out = make(templates, image, "university", tmp_path, content=c)
    st = by_id(report(a, prof, c, out))
    assert st["figure_images"]["status"] == "warning"


# ------------------------------------------------------------------ captions
def test_caption_label_mismatch_warns(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "university", tmp_path)
    prof2 = prof.model_copy(deep=True)
    prof2.table.label = "Tabelle"
    st = by_id(report(a, prof2, c, out))
    assert st["caption_labels"]["status"] == "warning"
    assert any("Tabelle" in d for d in st["caption_labels"]["details"])


# ------------------------------------------------------------------ complex scripts / RTL
def test_rtl_document_checks_pass_and_detect_missing_bidi(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "rtl", tmp_path)
    assert by_id(report(a, prof, c, out))["complex_script"]["status"] == "passed"

    def strip(d):
        for t in d.tables:
            bv = t._tbl.tblPr.find(qn("w:bidiVisual"))
            if bv is not None:
                t._tbl.tblPr.remove(bv)
        for r in d.element.body.iter(qn("w:rtl")):
            r.getparent().remove(r)
            break
    st = by_id(report(a, prof, c, broken(out, tmp_path, strip)))
    assert st["complex_script"]["status"] == "failed"
    det = " ".join(st["complex_script"]["details"])
    assert "bidiVisual" in det and "rtl" in det


def test_bangla_runs_without_cs_font_fail(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "bangla", tmp_path)
    assert by_id(report(a, prof, c, out))["complex_script"]["status"] == "passed"

    def strip_cs(d):
        for f in d.element.body.iter(qn("w:rFonts")):
            if f.get(qn("w:cs")):
                del f.attrib[qn("w:cs")]
    st = by_id(report(a, prof, c, broken(out, tmp_path, strip_cs)))
    assert st["complex_script"]["status"] == "failed" and "Kalpurush" in " ".join(st["complex_script"]["details"])


def test_latin_document_complex_script_check_is_info(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "university", tmp_path)
    assert by_id(report(a, prof, c, out))["complex_script"]["status"] == "info"


def test_document_language_check(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "bangla", tmp_path)
    st = by_id(report(a, prof, c, out))
    assert st["document_language"]["status"] == "passed"


# ------------------------------------------------------------------ manual checks
def test_manual_visual_checks_cover_language_specific_rendering(templates, image, tmp_path):
    a, prof, c, out = make(templates, image, "bangla", tmp_path)
    ids = {x["id"] for x in report(a, prof, c, out)["checks"] if x["status"] == "manual"}
    assert {"visual_pagination", "visual_figures", "visual_fit", "visual_headers", "visual_script"} <= ids
    a2, prof2, c2, out2 = make(templates, image, "university", tmp_path)
    ids2 = {x["id"] for x in report(a2, prof2, c2, out2)["checks"] if x["status"] == "manual"}
    assert "visual_script" not in ids2


def test_unfilled_placeholders_check(templates, image, tmp_path):
    c = DocumentContent.model_validate({"title": "T", "fields": {"DOI": "10.1/x"}, "body": []})
    a, prof, c, out = make(templates, image, "journal", tmp_path, content=c)
    st = by_id(report(a, prof, c, out))
    assert st["placeholders"]["status"] == "warning" and any("VOLUME" in d for d in st["placeholders"]["details"])
    c2 = DocumentContent.model_validate({"title": "T", "fields": {"DOI": "1", "VOLUME": "1", "ISSUE": "1"},
                                         "authors": [{"name": "A"}], "body": []})
    a2, prof2, c2, out2 = make(templates, image, "journal", tmp_path, content=c2)
    assert by_id(report(a2, prof2, c2, out2))["placeholders"]["status"] == "passed"
    a3, prof3, c3, out3 = make(templates, image, "university", tmp_path)
    assert by_id(report(a3, prof3, c3, out3))["placeholders"]["status"] == "info"


def test_filled_header_placeholders_are_not_a_changed_header(templates, image, tmp_path):
    c = DocumentContent.model_validate({"title": "T", "fields": {"DOI": "10.1/x", "VOLUME": "2", "ISSUE": "3"}, "body": []})
    a, prof, c, out = make(templates, image, "journal", tmp_path, content=c)
    assert by_id(report(a, prof, c, out))["header_footer"]["status"] == "passed"

    def change(d):
        d.sections[0].header.paragraphs[0].runs[0].text = "Something else entirely"
    st = by_id(report(a, prof, c, broken(out, tmp_path, change)))
    assert st["header_footer"]["status"] == "failed"
