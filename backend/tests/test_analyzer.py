"""Phase 2: StyleResolver, role detection, page/header/footer/table/figure/language detection,
health report and build_default_profile with origins. Runs against all six fixtures plus small
synthetic templates for cases the fixtures do not cover."""
import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from pydantic import BaseModel

from app.schemas.profile import ROLES, FormattingProfile
from app.services.profiles import carry_over
from app.template_engine.analyzer import analyze_template, build_default_profile
from app.template_engine.ooxml import StyleResolver, dominant_script

ALL = ["default", "university", "messy", "bangla", "twocol", "rtl"]


@pytest.fixture(scope="module")
def analyses(templates):
    return {n: analyze_template(templates[n]) for n in ALL}


def _style(doc, sid, name, xml_inner, based_on=None, kind="paragraph"):
    based = f'<w:basedOn w:val="{based_on}"/>' if based_on else ""
    el = parse_xml(f'<w:style {nsdecls("w")} w:type="{kind}" w:styleId="{sid}"><w:name w:val="{name}"/>{based}{xml_inner}</w:style>')
    doc.styles.element.append(el)
    return el


def _drop_builtin_headings(doc):
    for s in list(doc.styles.element.findall(qn("w:style"))):
        if (s.get(qn("w:styleId")) or "").startswith("Heading"):
            doc.styles.element.remove(s)


def _save(doc, tmp_path, name="t.docx"):
    p = str(tmp_path / name)
    doc.save(p)
    return p


# ------------------------------------------------------------------ StyleResolver
def test_theme_attribute_beats_explicit_font_in_same_element(templates):
    sr = StyleResolver(Document(templates["university"]))
    # python-docx set ascii="Times New Roman" on Heading 1 but left asciiTheme="majorHAnsi": Word uses the theme
    h1 = sr.resolve("Heading1")
    assert h1["font"] == sr.theme["major"] and h1["font_ascii_theme"] == "majorHAnsi"
    assert sr.resolve("Normal")["font"] == "Times New Roman"      # explicit on Normal beats docDefaults theme


def test_cs_theme_is_read_and_overrides_inherited_cs_font(templates):
    sr = StyleResolver(Document(templates["bangla"]))
    assert sr.resolve("Normal")["font_cs"] == "Kalpurush"
    h1 = sr.resolve("Heading1")                                     # rFonts w:cstheme="majorBidi" on Heading 1
    assert h1["font_cs_theme"] == "majorBidi"
    assert h1["font_cs"] != "Kalpurush"


def test_theme_fonts_include_east_asian_cs_and_script_fonts(templates):
    t = StyleResolver(Document(templates["default"])).theme
    assert t["major"] and t["minor"]
    assert "Beng" in t["minor_scripts"] and "Arab" in t["minor_scripts"]


def test_later_explicit_font_beats_earlier_theme(tmp_path):
    d = Document()
    _style(d, "Base", "Base", '<w:rPr><w:rFonts w:asciiTheme="minorHAnsi" w:hAnsiTheme="minorHAnsi"/></w:rPr>')
    _style(d, "Child", "Child", '<w:rPr><w:rFonts w:ascii="Georgia" w:hAnsi="Georgia"/></w:rPr>', based_on="Base")
    _style(d, "Grand", "Grand", '<w:rPr><w:rFonts w:asciiTheme="majorHAnsi"/></w:rPr>', based_on="Child")
    sr = StyleResolver(Document(_save(d, tmp_path)))
    assert sr.resolve("Child")["font"] == "Georgia" and "font_ascii_theme" not in sr.resolve("Child")
    assert sr.resolve("Grand")["font"] == sr.theme["major"]


def test_basedon_chain_doc_defaults_and_cycles(tmp_path):
    d = Document()
    _style(d, "A", "A", '<w:pPr><w:spacing w:after="120"/></w:pPr><w:rPr><w:b/><w:sz w:val="30"/></w:rPr>')
    _style(d, "B", "B", '<w:rPr><w:b w:val="0"/><w:i/></w:rPr>', based_on="A")
    _style(d, "LoopX", "LoopX", "", based_on="LoopY")
    _style(d, "LoopY", "LoopY", "", based_on="LoopX")
    sr = StyleResolver(Document(_save(d, tmp_path)))
    b = sr.resolve("B")
    assert b["bold"] is False and b["italic"] is True and b["size_pt"] == 15 and b["space_after_pt"] == 6
    assert sr.resolve("NoSuchStyle")["size_pt"] == 11               # unknown id -> docDefaults only
    assert sr.resolve("LoopX") is not None                           # cycle does not hang
    assert {"LoopX", "LoopY"} <= set(sr.cycles())


def test_complex_script_toggles_and_rtl(tmp_path):
    d = Document()
    _style(d, "CS", "CS", '<w:pPr><w:bidi/></w:pPr><w:rPr><w:bCs/><w:iCs/><w:rtl/><w:szCs w:val="28"/></w:rPr>')
    r = StyleResolver(Document(_save(d, tmp_path))).resolve("CS")
    assert r["bold_cs"] and r["italic_cs"] and r["rtl"] and r["bidi"] and r["size_cs_pt"] == 14


def test_indent_firstline_and_hanging_are_exclusive(tmp_path):
    d = Document()
    _style(d, "P", "P", '<w:pPr><w:ind w:start="720" w:end="360" w:firstLine="567"/></w:pPr>')
    _style(d, "Q", "Q", '<w:pPr><w:ind w:hanging="360"/></w:pPr>', based_on="P")
    sr = StyleResolver(Document(_save(d, tmp_path)))
    p, q = sr.resolve("P"), sr.resolve("Q")
    assert p["left_indent_pt"] == 36 and p["right_indent_pt"] == 18 and p["first_line_pt"] == 28.35
    assert q["hanging_pt"] == 18 and "first_line_pt" not in q


def test_numid_zero_removes_inherited_numbering(templates, tmp_path):
    d = Document(templates["university"])
    _style(d, "H1Plain", "Heading 1 unnumbered", '<w:pPr><w:numPr><w:numId w:val="0"/></w:numPr></w:pPr>', based_on="Heading1")
    sr = StyleResolver(Document(_save(d, tmp_path)))
    assert sr.resolve("Heading1")["num_id"] == "90"
    assert "num_id" not in sr.resolve("H1Plain")


def test_dominant_script():
    assert dominant_script("এটি একটি নমুনা") == "Beng"
    assert dominant_script("هذا نص") == "Arab"
    assert dominant_script("यह हिंदी है") == "Deva"
    assert dominant_script("Plain English with one ক") == "Latn"
    assert dominant_script("") is None


# ------------------------------------------------------------------ role detection
def test_roles_on_every_fixture(analyses):
    r = {n: a["suggested_roles"] for n, a in analyses.items()}
    for n in ("default", "university", "bangla", "twocol", "rtl"):
        assert r[n]["heading_1"] == "Heading1" and r[n]["heading_2"] == "Heading2", n
        assert r[n]["title"] == "Title" and r[n]["caption"] == "Caption", n
    assert r["default"]["list_bullet"] == "ListBullet" and r["default"]["list_number"] == "ListNumber"
    assert not any(k.startswith("heading_") for k in r["messy"]) and "caption" not in r["messy"]
    assert all(a["suggested_roles"]["body"] == "Normal" for a in analyses.values())
    assert all(set(a["suggested_roles"]) <= set(ROLES) for a in analyses.values())


def test_odd_style_names_are_not_mistaken_for_roles(analyses):
    assert not {"bdyttxtFINAL", "Normal1", "Paracopy2", "zzoldSTYLE"} & set(analyses["messy"]["suggested_roles"].values())


@pytest.mark.parametrize("name, level", [
    ("Überschrift 1", 1), ("Titre 2", 2), ("Título 3", 3), ("Заголовок 1", 1), ("标题 2", 2),
    ("見出し 1", 1), ("عنوان 2", 2), ("שִׁכְבָה", None), ("শিরোনাম ১", 1), ("शीर्षक २", 2), ("Kop 3", 3),
])
def test_localized_heading_names_with_native_digits(tmp_path, name, level):
    d = Document()
    _drop_builtin_headings(d)                        # a localized template has no English "Heading N"
    _style(d, "Custom9", name, "<w:qFormat/>")
    p = d.add_paragraph("x"); p.style = d.styles[name]
    a = analyze_template(_save(d, tmp_path))
    found = {k for k, v in a["suggested_roles"].items() if v == "Custom9" and k.startswith("heading_")}
    assert found == ({f"heading_{level}"} if level else set())


def test_outline_level_detects_custom_heading_style(tmp_path):
    d = Document()
    _style(d, "ChapterHead", "Chapter Head", '<w:qFormat/><w:pPr><w:outlineLvl w:val="0"/></w:pPr>')
    p = d.add_paragraph("x"); p.style = d.styles["Chapter Head"]
    _drop_builtin_headings(d)                        # so outline level is the only evidence
    a = analyze_template(_save(d, tmp_path))
    assert a["suggested_roles"]["heading_1"] == "ChapterHead"
    assert a["role_evidence"]["heading_1"]["by"] == "outline_level"


def test_role_evidence_explains_every_role(analyses):
    for n, a in analyses.items():
        assert set(a["role_evidence"]) == set(a["suggested_roles"]), n
        for role, ev in a["role_evidence"].items():
            assert ev["style_id"] == a["suggested_roles"][role]
            assert ev["by"] in {"outline_level", "style_id", "style_name", "usage", "default_style"}


def test_character_styles_never_take_paragraph_roles(tmp_path):
    d = Document()
    d.styles.add_style("Quote Char Thing", WD_STYLE_TYPE.CHARACTER)
    _style(d, "Quote", "Quote", "", kind="character")
    a = analyze_template(_save(d, tmp_path))
    ids = {s["id"]: s["type"] for s in a["styles"]}
    assert all(ids.get(v) == "paragraph" for v in a["suggested_roles"].values())


# ------------------------------------------------------------------ page / header / footer
def test_page_detection(analyses):
    u, t = analyses["university"]["page"], analyses["twocol"]["page"]
    assert (u["width_cm"], u["height_cm"]) == (21.0, 29.7) and u["margins_cm"]["left"] == 3.8
    assert u["orientation"] == "portrait" and u["columns"] == 1 and t["columns"] == 2
    assert t["column_space_cm"] == round(360 / 566.929, 2)
    for a in analyses.values():
        assert {"gutter_cm", "header_distance_cm", "footer_distance_cm", "rtl_section", "page_number_format"} <= set(a["page"])


def test_section_level_rtl_and_page_number_format(tmp_path):
    d = Document()
    sp = d.sections[0]._sectPr
    pg = OxmlElement("w:pgNumType"); pg.set(qn("w:fmt"), "bengali"); pg.set(qn("w:start"), "1")
    sp.append(pg); sp.append(OxmlElement("w:bidi"))
    from app.document_engine.generator import SECTPR_ORDER, sort_children
    sort_children(sp, SECTPR_ORDER)
    a = analyze_template(_save(d, tmp_path))
    assert a["page"]["rtl_section"] is True and a["page"]["page_number_format"] == "bengali"
    assert a["language"]["rtl"] is True


def test_header_footer_detection(analyses):
    hf = analyses["university"]["header_footer"]
    assert hf["header_text"] == "Metropolitan University - Thesis" and hf["footer_has_page_number"]
    assert set(hf["kinds"]) == {"default"}
    assert not analyses["default"]["header_footer"]["footer_has_page_number"]


def test_first_and_even_page_headers(tmp_path):
    d = Document()
    s = d.sections[0]
    s.different_first_page_header_footer = True
    s.first_page_header.paragraphs[0].text = "Cover header"
    d.settings.odd_and_even_pages_header_footer = True
    s.even_page_header.paragraphs[0].text = "Even header"
    s.header.paragraphs[0].text = "Odd header"
    hf = analyze_template(_save(d, tmp_path))["header_footer"]
    assert hf["kinds"] == {"default": "Odd header", "first": "Cover header", "even": "Even header"}
    assert hf["even_and_odd"] is True


# ------------------------------------------------------------------ tables / figures
def test_table_detection(analyses):
    t = analyses["university"]["tables"][0]
    assert t["style_id"] == "TableGrid" and t["caption_position"] == "below"
    assert t["caption_label"] == "Table" and t["caption_separator"] == ": "
    assert analyses["default"]["tables"] == []


def test_table_header_bold_from_table_style_first_row(tmp_path):
    d = Document()
    _style(d, "Fancy", "Fancy Table",
           '<w:tblStylePr w:type="firstRow"><w:rPr><w:b/></w:rPr></w:tblStylePr>', kind="table")
    t = d.add_table(rows=2, cols=2); t.style = d.styles["Fancy Table"]
    a = analyze_template(_save(d, tmp_path))
    assert a["tables"][0]["header_bold"] is True


def test_figure_detection_with_localized_caption(tmp_path, image):
    d = Document()
    d.add_picture(image)
    d.paragraphs[-1].alignment = 1
    d.add_paragraph("চিত্র ১: কাঠামো", style="Caption")
    a = analyze_template(_save(d, tmp_path))
    f = a["figures"][0]
    assert f["alignment"] == "center" and f["caption_position"] == "below" and f["caption_label"] == "চিত্র"
    p = build_default_profile(a)
    assert p.figure.label == "চিত্র" and p.origins["figure.label"] == "template"


# ------------------------------------------------------------------ language
def test_language_detection(analyses):
    b, r, u = analyses["bangla"]["language"], analyses["rtl"]["language"], analyses["university"]["language"]
    assert b["script"] == "Beng" and b["suggested_code"] == "bn" and b["rtl"] is False
    assert r["script"] == "Arab" and r["suggested_code"] == "ar" and r["rtl"] is True and r["normal_bidi"] is True
    assert u["script"] == "Latn" and u["suggested_code"] == "en-US" and u["rtl"] is False
    # python-docx puts bidi="ar-SA" in every docDefaults; that alone must not make a template Arabic
    assert analyses["default"]["language"]["rtl"] is False


def test_cs_font_falls_back_to_theme_script_font(tmp_path):
    d = Document()
    d.add_paragraph("এটি একটি নমুনা অনুচ্ছেদ।")
    a = analyze_template(_save(d, tmp_path))
    theme_beng = StyleResolver(Document(_save(d, tmp_path, "u.docx"))).theme["minor_scripts"]["Beng"]
    assert a["language"]["suggested_cs_font"] == theme_beng
    p = build_default_profile(a)
    assert p.language.complex_script_font == theme_beng and p.origins["language.complex_script_font"] == "template"


# ------------------------------------------------------------------ health
def test_health_codes(analyses):
    codes = {n: {h["code"] for h in a["health"]} for n, a in analyses.items()}
    assert {"NO_HEADING_STYLES", "HEAVY_DIRECT_FORMATTING", "NO_CAPTION_STYLE"} <= codes["messy"]
    assert "MULTI_COLUMN" in codes["twocol"]
    assert "HEADINGS_NOT_NUMBERED" in codes["default"] and "HEADINGS_NOT_NUMBERED" not in codes["university"]
    # defect 3 from Phase 0 renders: Title inherits Normal's first-line indent. That is the template, not a bug; say so.
    assert "INHERITED_FIRST_LINE_INDENT" in codes["university"]
    assert "INHERITED_FIRST_LINE_INDENT" not in codes["default"]
    for a in analyses.values():
        assert all(h["severity"] in {"error", "warning", "info"} for h in a["health"])


def test_health_reports_cycles_and_broken_numbering(templates, tmp_path):
    d = Document(templates["university"])
    _style(d, "LoopX", "LoopX", "", based_on="LoopY")
    _style(d, "LoopY", "LoopY", "", based_on="LoopX")
    h2 = next(s for s in d.styles.element.findall(qn("w:style")) if s.get(qn("w:styleId")) == "Heading2")
    h2.find(f"{qn('w:pPr')}/{qn('w:numPr')}/{qn('w:numId')}").set(qn("w:val"), "777")
    codes = {h["code"] for h in analyze_template(_save(d, tmp_path))["health"]}
    assert {"STYLE_CYCLE", "BROKEN_NUMBERING"} <= codes


# ------------------------------------------------------------------ build_default_profile
def _leaf_paths(model: BaseModel, prefix=""):
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            yield from _leaf_paths(value, f"{prefix}{name}.")
        else:
            yield f"{prefix}{name}"


NOT_RULES = {"schema_version", "name", "roles", "origins", "required_sections"}


@pytest.mark.parametrize("name", ALL)
def test_every_rule_has_an_origin_and_every_origin_is_real(analyses, name):
    p = build_default_profile(analyses[name], name)
    leaves = {x for x in _leaf_paths(p) if x not in NOT_RULES}
    role_keys = {f"roles.{r}" for r in p.roles}
    assert leaves | role_keys == set(p.origins), set(p.origins) ^ (leaves | role_keys)
    FormattingProfile.model_validate(p.model_dump())               # passes strict validation


def test_origins_reflect_evidence(analyses):
    u = build_default_profile(analyses["university"])
    assert u.origins["roles.heading_1"] == "template" and u.origins["heading_numbering"] == "template"
    assert u.origins["table.caption_position"] == "inferred" and u.origins["table.label"] == "template"
    assert u.origins["labels.caption_separator"] == "template"
    m = build_default_profile(analyses["messy"])
    assert m.heading_numbering == "none" and m.origins["heading_numbering"] == "default"
    assert m.origins["table.caption_position"] == "default"


def test_language_specific_default_labels(analyses):
    b = build_default_profile(analyses["bangla"])
    assert b.language.code == "bn" and b.origins["language.code"] == "inferred"
    assert (b.labels.abstract, b.labels.keywords, b.table.label, b.figure.label) == ("সারসংক্ষেপ", "মূলশব্দ", "সারণি", "চিত্র")
    assert (b.labels.source, b.labels.note) == ("উৎস", "টীকা") and b.origins["labels.abstract"] == "inferred"
    r = build_default_profile(analyses["rtl"])
    assert r.language.code == "ar" and r.language.rtl and r.table.label == "جدول" and r.figure.label == "شكل"
    e = build_default_profile(analyses["default"])
    assert e.labels.abstract == "Abstract" and e.origins["labels.abstract"] == "default"


def test_carry_over_records_origins_for_new_roles(analyses):
    old = build_default_profile(analyses["messy"])
    moved = carry_over(old, analyses["university"])
    assert moved.roles["heading_1"] == "Heading1" and moved.origins["roles.heading_1"] == "template"


# ------------------------------------------------------------------ Phase 9: real-template findings (journal fixture)
def test_used_custom_styles_beat_unused_builtins(templates):
    """The user's IJPCR template: sample content uses 'IJPCR Heading 1..3', 'IJPCR Body Text' ...
    while Word's Heading 1..6 / Caption are unused. The unused built-ins were picked."""
    r = analyze_template(templates["journal"])["suggested_roles"]
    assert (r["heading_1"], r["heading_2"], r["heading_3"]) == ("JRNLHeading1", "JRNLHeading2", "JRNLHeading3")
    assert r["body"] == "JRNLBodyText" and r["body_first"] == "JRNLBodyFirst"
    assert r["list_bullet"] == "JRNLListBullet" and r["table_text"] == "JRNLTableText"
    assert r["caption"] in ("JRNLTableCaption", "JRNLFigureCaption") and r["quote"] == "JRNLBlockQuote"


def test_builtin_word_templates_keep_their_roles(analyses):
    r = analyses["default"]["suggested_roles"]
    assert r["heading_1"] == "Heading1" and r["body"] == "Normal" and "body_first" not in r
    assert analyses["university"]["suggested_roles"]["heading_1"] == "Heading1"


def test_body_layout_and_placeholders_are_reported(templates):
    codes = {h["code"]: h for h in analyze_template(templates["journal"])["health"]}
    assert "BODY_LAYOUT" in codes and "PLACEHOLDERS" in codes
    assert "{{DOI}}" in codes["PLACEHOLDERS"]["message"]
    assert "BODY_LAYOUT" not in {h["code"] for h in analyze_template(templates["university"])["health"]}


def test_placeholders_listed_and_layout_mode_suggested(templates):
    a = analyze_template(templates["journal"])
    names = {p["name"]: p["where"] for p in a["placeholders"]}
    assert names["TITLE"] == ["body"] and names["DOI"] == ["header"]
    p = build_default_profile(a)
    assert p.keep_template_layout is True and p.origins["keep_template_layout"] == "inferred"
    u = build_default_profile(analyze_template(templates["university"]))
    assert u.keep_template_layout is False and u.origins["keep_template_layout"] == "default"
    assert analyze_template(templates["university"])["placeholders"] == []
