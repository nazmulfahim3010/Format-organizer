"""Phase 3: generator behaviours not covered by test_engine.py."""
import os
import zipfile

import pytest
from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from app.document_engine.generator import SECTPR_ORDER, generate_docx
from app.schemas.content import DocumentContent
from app.template_engine.analyzer import analyze_template, build_default_profile
from tests.sample import sample_content

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ALL = ["default", "university", "messy", "bangla", "twocol", "rtl"]
LANG = {"bangla": "bn", "rtl": "ar"}


def gen(templates, image, name, tmp_path, content=None, tweak=None, lang=None):
    prof = build_default_profile(analyze_template(templates[name]), name)
    if tweak:
        tweak(prof)
    c = content or sample_content(lang or LANG.get(name, "en"))
    out = str(tmp_path / f"{name}.docx")
    res = generate_docx(templates[name], prof, c, lambda a: image if a == "img1" else None, out)
    return Document(out), res, out


def body(**kw):
    return DocumentContent.model_validate({"body": [], **kw})


def in_order(el, order):
    rank = {qn(f"w:{n}"): i for i, n in enumerate(order)}
    ranks = [rank[c.tag] for c in el if c.tag in rank]
    return ranks == sorted(ranks)


# ------------------------------------------------------------------ body, sectPr, settings
@pytest.mark.parametrize("name", ALL)
def test_body_cleared_and_final_sectpr_in_schema_order(templates, image, tmp_path, name):
    d, _, _ = gen(templates, image, name, tmp_path)
    sp = d.element.body.find(qn("w:sectPr"))
    assert d.element.body[-1] is sp and in_order(sp, SECTPR_ORDER)
    texts = [p.text for p in d.paragraphs]
    assert "Sample body text." not in texts and "Sample" not in texts and "এটি একটি নমুনা অনুচ্ছেদ।" not in texts


def test_missing_page_setup_is_added_in_order(templates, image, tmp_path):
    src = Document(templates["twocol"])
    sp = src.element.body.find(qn("w:sectPr"))
    for tag in ("pgSz", "pgMar"):
        sp.remove(sp.find(qn(f"w:{tag}")))
    path = str(tmp_path / "nopg.docx"); src.save(path)
    templates = {**templates, "nopg": path}
    d, _, _ = gen(templates, image, "nopg", tmp_path)
    sp = d.element.body.find(qn("w:sectPr"))
    assert sp.find(qn("w:pgSz")) is not None and sp.find(qn("w:cols")).get(qn("w:num")) == "2"
    assert in_order(sp, SECTPR_ORDER)


def test_rtl_document_gets_rtl_section(templates, image, tmp_path):
    d, _, _ = gen(templates, image, "rtl", tmp_path)
    assert d.element.body.find(qn("w:sectPr")).find(qn("w:bidi")) is not None
    d2, _, _ = gen(templates, image, "university", tmp_path)
    assert d2.element.body.find(qn("w:sectPr")).find(qn("w:bidi")) is None


def test_soft_breaks_are_not_stretched_in_justified_text(templates, image, tmp_path):
    d, _, _ = gen(templates, image, "twocol", tmp_path)
    compat = d.settings.element.find(qn("w:compat"))
    assert compat is not None and compat.find(qn("w:doNotExpandShiftReturn")) is not None
    tags = [c.tag for c in compat]
    if qn("w:compatSetting") in tags:          # compatSetting elements come last in CT_Compat
        assert tags.index(qn("w:doNotExpandShiftReturn")) < tags.index(qn("w:compatSetting"))


# ------------------------------------------------------------------ fallback styles
def test_fallback_heading_styles_carry_complex_script_properties(templates, image, tmp_path):
    d, res, _ = gen(templates, image, "messy", tmp_path, lang="bn",
                    tweak=lambda p: setattr(p.language, "complex_script_font", "Kalpurush"))
    assert "HEADING_STYLE_CREATED" in {w["code"] for w in res.warnings}
    h1 = next(s for s in d.styles if s.name == "Heading 1")
    rpr = h1.element.rPr
    assert rpr.find(qn("w:b")) is not None and rpr.find(qn("w:bCs")) is not None
    assert rpr.find(qn("w:sz")).get(qn("w:val")) == rpr.find(qn("w:szCs")).get(qn("w:val"))


def test_fallback_styles_do_not_inherit_body_first_line_indent(templates, image, tmp_path):
    def drop_roles(p):
        for r in ("heading_1", "heading_2", "heading_3", "caption", "title"):
            p.roles.pop(r, None)
    d, _, _ = gen(templates, image, "university", tmp_path, tweak=drop_roles)
    # university Normal has a 1 cm first-line indent; the styles SmartDoc creates must reset it
    created = [st for st in d.styles if st.type == 1 and st.name.startswith("SmartDoc")]
    assert created
    for st in created:
        ind = st.element.pPr.find(qn("w:ind")) if st.element.pPr is not None else None
        assert ind is not None and ind.get(qn("w:firstLine")) == "0", st.name


# ------------------------------------------------------------------ heading numbering
def test_auto_numbering_with_reused_styles_keeps_each_style_at_its_own_level(templates, image, tmp_path):
    """heading_4 falls back to heading_3's style; auto numbering must not move Heading 3 to level 4."""
    def tweak(p):
        p.heading_numbering = "auto"
        for k in range(4, 10):
            p.roles.pop(f"heading_{k}", None)
    deep = {"type": "section", "title": "L1", "content": [{"type": "section", "title": "L2", "content": [
        {"type": "section", "title": "L3", "content": [{"type": "section", "title": "L4", "content": []}]}]}]}
    d, _, _ = gen(templates, image, "university", tmp_path, content=body(body=[deep]), tweak=tweak)
    h3 = d.styles["Heading 3"].element.pPr.find(qn("w:numPr"))
    assert h3.find(qn("w:ilvl")).get(qn("w:val")) == "2"
    num = d.part.numbering_part.element
    pstyles = [l.find(qn("w:pStyle")).get(qn("w:val")) for a in num.findall(qn("w:abstractNum"))
               for l in a.findall(qn("w:lvl")) if l.find(qn("w:pStyle")) is not None
               and a.find(qn("w:multiLevelType")).get(qn("w:val")) == "multilevel"
               and l.find(qn("w:pStyle")).get(qn("w:val")).startswith("Heading")]
    assert len(pstyles) == len(set(pstyles)), pstyles        # each style linked to exactly one level


@pytest.mark.parametrize("name", ["messy", "university"])
def test_auto_numbered_heading_styles_hang_like_their_level(templates, image, tmp_path, name):
    """Found by rendering: a style's own w:ind (e.g. firstLine=0) overrode the level's hanging indent,
    so numbers started 1 cm in from the margin."""
    d, _, _ = gen(templates, image, name, tmp_path, tweak=lambda p: setattr(p, "heading_numbering", "auto"))
    for lvl in (1, 2, 3):
        st = next(s for s in d.styles if s.style_id == f"Heading{lvl}")
        ind = st.element.pPr.find(qn("w:ind"))
        width = str(567 + 170 * (lvl - 1))
        assert (ind.get(qn("w:left")), ind.get(qn("w:hanging")), ind.get(qn("w:firstLine"))) == (width, width, None)


# ------------------------------------------------------------------ captions
def _seq_results(d):
    out = []
    for p in d.paragraphs:
        runs = list(p._p.iter(qn("w:r")))
        for i, r in enumerate(runs):
            it = r.find(qn("w:instrText"))
            if it is not None and "SEQ" in it.text:
                kind = it.text.split()[1]
                result = runs[i + 2].find(qn("w:t")).text
                out.append((kind, result))
    return out


def test_seq_cached_numbers_use_native_digits_when_asked(templates, image, tmp_path):
    d, _, _ = gen(templates, image, "bangla", tmp_path)
    assert _seq_results(d) == [("Table", "১"), ("Table", "২"), ("Figure", "১"), ("Table", "৩")]
    d2, _, _ = gen(templates, image, "bangla", tmp_path, tweak=lambda p: setattr(p.language, "native_digits", False))
    assert _seq_results(d2)[0] == ("Table", "1")
    d3, _, _ = gen(templates, image, "university", tmp_path)
    assert [r for _, r in _seq_results(d3)] == ["1", "2", "1", "3"]


def test_native_digit_caption_numbers_get_the_complex_script_font(templates, image, tmp_path):
    """Found by the Phase 5 validator: SEQ result runs had no rPr, so native digits had no cs font."""
    d, _, _ = gen(templates, image, "bangla", tmp_path)
    for p in d.paragraphs:
        runs = list(p._p.iter(qn("w:r")))
        for i, r in enumerate(runs):
            it = r.find(qn("w:instrText"))
            if it is not None and "SEQ" in it.text:
                rpr = runs[i + 2].find(qn("w:rPr"))
                assert rpr is not None and rpr.find(qn("w:rFonts")).get(qn("w:cs")) == "Kalpurush"


def test_native_digits_default_by_language(templates):
    assert build_default_profile(analyze_template(templates["bangla"])).language.native_digits is True
    assert build_default_profile(analyze_template(templates["rtl"])).language.native_digits is True
    assert build_default_profile(analyze_template(templates["university"])).language.native_digits is False


def test_caption_below_table_is_kept_with_the_table(templates, image, tmp_path):
    d, _, _ = gen(templates, image, "university", tmp_path)       # university captions go below
    t = d.tables[0]._tbl
    last_row_pars = t.findall(qn("w:tr"))[-1].iter(qn("w:p"))
    assert all(p.find(f"{qn('w:pPr')}/{qn('w:keepNext')}") is not None for p in last_row_pars)


# ------------------------------------------------------------------ tables, columns, images
def test_unequal_columns_use_the_narrowest_column(templates, image, tmp_path):
    src = Document(templates["twocol"])
    cols = src.element.body.find(qn("w:sectPr")).find(qn("w:cols"))
    cols.set(qn("w:equalWidth"), "0")
    for w in ("6000", "3000"):
        c = etree.SubElement(cols, qn("w:col")); c.set(qn("w:w"), w); c.set(qn("w:space"), "360")
    path = str(tmp_path / "uneq.docx"); src.save(path)
    d, _, _ = gen({**templates, "uneq": path}, image, "uneq", tmp_path)
    tw = int(d.tables[0]._tbl.tblPr.find(qn("w:tblW")).get(qn("w:w")))
    assert tw <= 3000


def test_figure_height_limited_by_page_text_height(templates, tmp_path):
    from PIL import Image
    tall = str(tmp_path / "tall.png")
    Image.new("RGB", (200, 4000), (200, 200, 200)).save(tall, dpi=(96, 96))
    src = Document(templates["university"])
    sec = src.sections[0]
    sec.page_width, sec.page_height = sec.page_height, sec.page_width     # landscape: ~10.6 cm text height
    path = str(tmp_path / "land.docx"); src.save(path)
    prof = build_default_profile(analyze_template(path))
    c = body(body=[{"type": "figure", "asset_id": "t", "caption": "Tall"}])
    out = str(tmp_path / "o.docx")
    generate_docx(path, prof, c, lambda a: tall, out)
    ext = next(Document(out).element.body.iter(
        "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent"))
    d = Document(path).sections[0]
    text_h = d.page_height - d.top_margin - d.bottom_margin
    assert int(ext.get("cy")) <= text_h * 0.9


# ------------------------------------------------------------------ complex scripts and RTL
def test_rtl_sample_is_arabic(templates, image, tmp_path):
    d, _, _ = gen(templates, image, "rtl", tmp_path)
    assert any("؀" <= ch <= "ۿ" for ch in d.paragraphs[0].text)


def test_complex_runs_get_bcs_when_style_is_bold(templates, image, tmp_path, monkeypatch):
    # a template heading style with <w:b/> but no <w:bCs/>: Bangla text in it must still be bold
    src = Document(templates["bangla"])
    h1 = next(s for s in src.styles if s.style_id == "Heading1").element.rPr
    h1.remove(h1.find(qn("w:bCs")))
    path = str(tmp_path / "nobcs.docx"); src.save(path)
    d, _, _ = gen({**templates, "nobcs": path}, image, "nobcs", tmp_path, lang="bn")
    heading = next(p for p in d.paragraphs if p.text == "ভূমিকা")
    assert all(r._r.rPr is not None and r._r.rPr.find(qn("w:bCs")) is not None for r in heading.runs)


def test_run_language_follows_the_runs_script(templates, image, tmp_path):
    c = body(language="bn", body=[{"type": "paragraph", "text": "বাংলা লেখা এবং مرحبا"}])
    d, _, _ = gen(templates, image, "bangla", tmp_path, content=c)
    runs = [(r.text, r._r.rPr) for r in d.paragraphs[0].runs]
    # mixed text is split into one run per script, each with its own language and direction
    assert [t for t, _ in runs] == ["বাংলা লেখা এবং ", "مرحبا"]
    assert [rpr.find(qn("w:lang")).get(qn("w:bidi")) for _, rpr in runs] == ["bn", "ar"]
    assert [rpr.find(qn("w:rtl")) is not None for _, rpr in runs] == [False, True]
    c2 = body(language="en", body=[{"type": "paragraph", "text": "مرحبا"}])
    d2, _, _ = gen(templates, image, "university", tmp_path, content=c2)
    r = d2.paragraphs[0].runs[0]._r.rPr
    assert r.find(qn("w:lang")).get(qn("w:bidi")) == "ar" and r.find(qn("w:rtl")) is not None


def test_doc_default_language_does_not_mark_latin_text_as_bangla(templates, image, tmp_path):
    d, _, _ = gen(templates, image, "bangla", tmp_path)
    lang = d.styles.element.find(qn("w:docDefaults")).find(f"{qn('w:rPrDefault')}/{qn('w:rPr')}/{qn('w:lang')}")
    assert lang.get(qn("w:bidi")) == "bn" and lang.get(qn("w:val")) == "en-US"
    d2, _, _ = gen(templates, image, "university", tmp_path, lang="en")
    lang2 = d2.styles.element.find(qn("w:docDefaults")).find(f"{qn('w:rPrDefault')}/{qn('w:rPr')}/{qn('w:lang')}")
    assert lang2.get(qn("w:val")) == "en"


def test_paragraph_direction_follows_first_strong_character(templates, image, tmp_path):
    c = body(language="ar", body=[{"type": "paragraph", "text": "Deep text."},
                                  {"type": "paragraph", "text": "نص عربي"},
                                  {"type": "paragraph", "text": "123"}])
    d, _, _ = gen(templates, image, "rtl", tmp_path, content=c)
    def bidi(p):
        el = p._p.pPr.find(qn("w:bidi"))
        return None if el is None else el.get(qn("w:val"), "1")
    by_text = {p.text: bidi(p) for p in d.paragraphs}
    assert by_text["Deep text."] == "0"             # explicit LTR: the template's Normal is bidi
    assert by_text["نص عربي"] == "1" and by_text["123"] == "1"
    c2 = body(language="en", body=[{"type": "paragraph", "text": "نص عربي"}])
    d2, _, _ = gen(templates, image, "university", tmp_path, content=c2)
    assert bidi(d2.paragraphs[0]) == "1"           # an Arabic paragraph in an English document


@pytest.mark.parametrize("name", ALL)
def test_every_generated_part_is_in_schema_order(templates, image, tmp_path, name):
    from app.document_engine.generator import PPR_ORDER, RPR_ORDER, TBLPR_ORDER, TCPR_ORDER
    _, _, out = gen(templates, image, name, tmp_path)
    z = zipfile.ZipFile(out)
    for part in ("word/document.xml", "word/styles.xml", "word/numbering.xml"):
        root = etree.fromstring(z.read(part))
        for tag, order in (("pPr", PPR_ORDER), ("rPr", RPR_ORDER), ("tblPr", TBLPR_ORDER),
                           ("tcPr", TCPR_ORDER), ("sectPr", SECTPR_ORDER)):
            for el in root.iter(f"{{{W}}}{tag}"):
                assert in_order(el, order), (part, tag, [c.tag.split('}')[1] for c in el])


def test_styles_without_a_name_do_not_break_generation(templates, image, tmp_path):
    """Found with the user's real IJPCR template (Phase 9): table styles 'a'/'a0' have no w:name,
    and creating a fallback style crashed with AttributeError."""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    src = Document(templates["messy"])           # messy has no author/abstract styles, so fallbacks are created
    src.styles.element.append(parse_xml(f'<w:style {nsdecls("w")} w:type="table" w:styleId="a"/>'))
    src.styles.element.append(parse_xml(f'<w:style {nsdecls("w")} w:type="paragraph" w:styleId="a1"/>'))
    path = str(tmp_path / "nameless.docx"); src.save(path)
    d, res, _ = gen({**templates, "nameless": path}, image, "nameless", tmp_path)
    assert any(p.text == "Author One\nMetropolitan University\na@example.org" for p in d.paragraphs)


def test_first_paragraph_after_a_heading_uses_body_first(templates, image, tmp_path):
    c = body(body=[{"type": "section", "title": "Intro", "content": [
        {"type": "paragraph", "text": "one"}, {"type": "paragraph", "text": "two"},
        {"type": "list", "items": [{"text": "x"}]}, {"type": "paragraph", "text": "three"},
        {"type": "section", "title": "Sub", "content": [{"type": "paragraph", "text": "four"}]}]}])
    d, _, _ = gen(templates, image, "journal", tmp_path, content=c)
    by = {p.text: p.style.style_id for p in d.paragraphs}
    assert (by["one"], by["two"], by["three"], by["four"]) == ("JRNLBodyFirst", "JRNLBodyText", "JRNLBodyText", "JRNLBodyFirst")
    d2, _, _ = gen(templates, image, "university", tmp_path, content=c)          # no body_first role: body everywhere
    assert {p.style.style_id for p in d2.paragraphs if p.text in ("one", "two", "four")} == {"Normal"}


def test_images_of_the_cleared_template_body_are_not_carried_into_the_output(templates, image, tmp_path):
    """The user's 4 MB IJPCR template produced 4 MB documents: the removed body's images stayed in the file."""
    off = lambda p: setattr(p, "keep_template_layout", False)                       # body cleared
    _, _, out = gen(templates, image, "journal", tmp_path, content=body(body=[{"type": "paragraph", "text": "x"}]), tweak=off)
    names = zipfile.ZipFile(out).namelist()
    assert not [n for n in names if n.startswith("word/media/")]
    _, _, out2 = gen(templates, image, "journal", tmp_path, tweak=off)               # sample content has one figure
    assert len([n for n in zipfile.ZipFile(out2).namelist() if n.startswith("word/media/")]) == 1


# ------------------------------------------------------------------ keep the template's first-page layout + fill placeholders
def _journal_content(**extra):
    return DocumentContent.model_validate({
        "title": "Water and Peace", "authors": [{"name": "Rahima Akter", "affiliation": "Dhaka University", "email": "r@example.org"}],
        "abstract": "We study **water** conflicts.", "keywords": ["water", "peace"],
        "fields": {"DOI": "10.1234/ijpcr.42", "VOLUME": "01", "ISSUE": "04"},
        "body": [{"type": "section", "title": "Introduction", "content": [{"type": "paragraph", "text": "Opening text."}]}],
        **extra})


def test_layout_mode_keeps_the_front_matter_and_replaces_the_sample_article(templates, image, tmp_path):
    d, res, _ = gen(templates, image, "journal", tmp_path, content=_journal_content(),
                    tweak=lambda p: setattr(p, "keep_template_layout", True))
    texts = [p.text for p in d.paragraphs]
    assert d.tables[0].cell(0, 0).text == "RESEARCH ARTICLE"                       # banner kept
    assert "Water and Peace" in texts and "{{TITLE}}" not in texts                  # placeholder filled
    assert texts.count("Water and Peace") == 1                                       # no second title block
    assert "Rahima Akter" in texts and "{{AUTHORS}}" not in texts
    assert "First paragraph after a heading." not in texts and "Introduction" in texts   # sample article replaced
    assert texts.index("Water and Peace") < texts.index("Introduction")
    assert any(r.reltype.endswith("/image") for r in d.part.rels.values())         # the logo image is still there


def test_header_placeholders_are_filled_from_template_fields(templates, image, tmp_path):
    for keep in (True, False):
        d, res, _ = gen(templates, image, "journal", tmp_path, content=_journal_content(),
                        tweak=lambda p: setattr(p, "keep_template_layout", keep))
        assert d.sections[0].header.paragraphs[0].text == "DOI: 10.1234/ijpcr.42 | Vol. 01, Issue 04"


def test_unfilled_placeholders_stay_visible_and_are_reported(templates, image, tmp_path):
    c = _journal_content(fields={"DOI": "10.1/x"})
    d, res, _ = gen(templates, image, "journal", tmp_path, content=c, tweak=lambda p: setattr(p, "keep_template_layout", True))
    assert "{{VOLUME}}" in d.sections[0].header.paragraphs[0].text
    w = [x for x in res.warnings if x["code"] == "PLACEHOLDER_UNFILLED"]
    assert w and "VOLUME" in w[0]["message"] and "ISSUE" in w[0]["message"]


def test_placeholders_split_across_runs_are_filled(templates, image, tmp_path):
    src = Document(templates["journal"])
    p = next(p for p in src.paragraphs if p.text == "{{AUTHORS}}")
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    for piece in ("{{AUT", "HO", "RS}} et al."):
        p.add_run(piece).bold = True
    path = str(tmp_path / "split.docx"); src.save(path)
    d, _, _ = gen({**templates, "split": path}, image, "split", tmp_path, content=_journal_content(),
                  tweak=lambda p: setattr(p, "keep_template_layout", True))
    para = next(p for p in d.paragraphs if p.text.startswith("Rahima"))
    assert para.text == "Rahima Akter et al." and all(r.bold for r in para.runs if r.text.strip())


def test_layout_mode_off_clears_the_body_as_before(templates, image, tmp_path):
    d, _, _ = gen(templates, image, "journal", tmp_path, content=_journal_content(),
                  tweak=lambda p: setattr(p, "keep_template_layout", False))
    assert not [t for t in d.tables if t.cell(0, 0).text == "RESEARCH ARTICLE"]
    assert "Water and Peace" in [p.text for p in d.paragraphs]                      # normal title block


def test_layout_mode_without_a_heading_in_the_template_clears_and_warns(templates, image, tmp_path):
    """The kept part ends at the template's first heading. Without one nothing tells sample content
    from layout, so the body is cleared as usual and the user is told."""
    d, res, _ = gen(templates, image, "default", tmp_path, tweak=lambda p: setattr(p, "keep_template_layout", True))
    assert "Sample text that should be removed." not in [p.text for p in d.paragraphs]
    assert "LAYOUT_NOT_KEPT" in {w["code"] for w in res.warnings}


def test_an_empty_heading_styled_spacer_does_not_end_the_layout(templates, image, tmp_path):
    """IJPCR: an empty 'Heading 1' paragraph sits inside the first-page layout; the kept part ended there and
    the 'Cite this article' box and licence block were lost."""
    d, _, _ = gen(templates, image, "journal", tmp_path, content=_journal_content(),
                  tweak=lambda p: setattr(p, "keep_template_layout", True))
    texts = [p.text for p in d.paragraphs]
    assert "Cite this article: Water and Peace, Vol. 01" in texts
    assert texts.index("Cite this article: Water and Peace, Vol. 01") < texts.index("Introduction")


# ------------------------------------------------------------------ optional profile settings used by predefined designs
def test_heading_number_suffix_space_puts_the_number_inline(templates, image, tmp_path):
    d, _, _ = gen(templates, image, "journal", tmp_path,
                  tweak=lambda p: (setattr(p, "heading_numbering", "auto"), setattr(p, "heading_number_suffix", "space")))
    num = d.part.numbering_part.element
    lvls = [l for a in num.findall(qn("w:abstractNum")) for l in a.findall(qn("w:lvl"))
            if l.find(qn("w:pStyle")) is not None and l.find(qn("w:pStyle")).get(qn("w:val")) == "JRNLHeading1"]
    assert lvls and lvls[0].find(qn("w:suff")).get(qn("w:val")) == "space"
    assert next(s for s in d.styles if s.style_id == "JRNLHeading1").element.pPr.find(qn("w:ind")).get(qn("w:left")) == "0"


def test_defaults_keep_tab_numbering_and_one_caption_style(templates, image, tmp_path):
    d, _, _ = gen(templates, image, "university", tmp_path, tweak=lambda p: setattr(p, "heading_numbering", "auto"))
    assert not list(d.part.numbering_part.element.iter(qn("w:suff")))
    caps = {p.style.style_id for p in d.paragraphs if p.text.startswith(("Table ", "Figure "))}
    assert caps == {"Caption"}


def test_figure_caption_role_styles_figure_captions_only(templates, image, tmp_path):
    d, _, _ = gen(templates, image, "journal", tmp_path,
                  tweak=lambda p: (p.roles.update(caption="JRNLTableCaption", figure_caption="JRNLFigureCaption"),
                                   setattr(p, "keep_template_layout", False)))
    by = {p.text.split(":")[0]: p.style.style_id for p in d.paragraphs if p.text.startswith(("Table ", "Figure "))}
    assert by["Figure 1"] == "JRNLFigureCaption" and by["Table 1"] == "JRNLTableCaption"
