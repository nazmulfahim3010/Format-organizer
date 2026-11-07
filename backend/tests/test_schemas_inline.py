"""Phase 1: content/profile schemas and the inline markup parser/serializer."""
import json
import random

import pytest
from pydantic import ValidationError

from app.core.inline import Run, escape, parse_inline, plain, runs_to_markup
from app.schemas.content import SCHEMA_VERSION, DocumentContent, TableBox
from app.schemas.profile import FormattingProfile


def styles(text):
    return [(r.text, r.bold, r.italic, r.sup, r.sub) for r in parse_inline(text)]


def canon(runs):
    """Merge adjacent same-style runs and drop empty ones, for comparing run lists."""
    out = []
    for r in runs:
        key = (r.bold, r.italic, r.sup, r.sub)
        if not r.text:
            continue
        if out and out[-1][1:] == key:
            out[-1] = (out[-1][0] + r.text, *key)
        else:
            out.append((r.text, *key))
    return out


# ------------------------------------------------------------------ parser
@pytest.mark.parametrize("src, expected", [
    ("**b**", [("b", True, False, False, False)]),
    ("*i*", [("i", False, True, False, False)]),
    ("***bi***", [("bi", True, True, False, False)]),
    ("H~2~O", [("H", False, False, False, False), ("2", False, False, False, True), ("O", False, False, False, False)]),
    ("x^2^", [("x", False, False, False, False), ("2", False, False, True, False)]),
    ("**a *b* c**", [("a ", True, False, False, False), ("b", True, True, False, False), (" c", True, False, False, False)]),
])
def test_parse_basic(src, expected):
    assert styles(src) == expected


@pytest.mark.parametrize("src", [
    "2 * 3 * 4 = 24",          # spaced asterisks are arithmetic, not italics
    "approx ~5 to ~10 km",     # sub/sup content may not contain spaces
    "a ^ b ^ c",
    "**unclosed bold",
    "unclosed *italic",
    "trailing *",
    "* bullet-looking",
    "x ** y",
    "~",
    "**",
    "",
])
def test_unpaired_or_spaced_markers_stay_literal(src):
    runs = parse_inline(src)
    assert all(not (r.bold or r.italic or r.sup or r.sub) for r in runs), runs
    assert plain(src) == src


def test_escapes():
    assert plain(r"\*lit\* \*\* \^ \~ \\") == "*lit* ** ^ ~ \\"
    assert plain(r"a\b") == r"a\b"                 # backslash before a non-special char is literal
    assert styles(r"^a\ b^") == [("a b", False, False, True, False)]   # escaped space allowed in sup
    assert plain("\\") == "\\"


def test_unicode_and_complex_scripts():
    assert styles("**বাংলা** লেখা") == [("বাংলা", True, False, False, False), (" লেখা", False, False, False, False)]
    assert styles("*مرحبا*") == [("مرحبا", False, True, False, False)]
    assert styles("সংখ্যা^২^") == [("সংখ্যা", False, False, False, False), ("২", False, False, True, False)]


def test_newlines_are_kept_as_text():
    assert plain("line one\nline two") == "line one\nline two"
    assert styles("**a\nb**") == [("a\nb", True, False, False, False)]


# ------------------------------------------------------------------ serializer
@pytest.mark.parametrize("runs", [
    [Run("a", italic=True), Run("b", bold=True, italic=True)],
    [Run("a", bold=True, italic=True), Run("b", italic=True)],
    [Run("a", bold=True), Run("b", bold=True, italic=True)],
    [Run("a", italic=True), Run("b", bold=True)],
    [Run("a", bold=True), Run("b", bold=True)],                    # merged
    [Run(" lead", bold=True), Run("trail ", italic=True)],         # whitespace moved outside markers
    [Run("1st place", sup=True)],                                  # space inside sup is escaped
    [Run("*", italic=True), Run("\\", bold=True)],
    [Run("2*3=6"), Run("^~", sub=True)],
])
def test_serializer_round_trip_cases(runs):
    assert canon(parse_inline(runs_to_markup(runs))) == canon(_expected_after_trim(runs))


def _expected_after_trim(runs):
    """Styling is moved off leading/trailing whitespace, which is invisible anyway."""
    out = []
    for r in runs:
        core = r.text.strip()
        if not core or not (r.bold or r.italic or r.sup or r.sub):
            out.append(Run(r.text))
            continue
        lead, trail = r.text[: len(r.text) - len(r.text.lstrip())], r.text[len(r.text.rstrip()):]
        out += [Run(lead), Run(core, r.bold, r.italic, r.sup, r.sub), Run(trail)]
    return out


def test_serializer_fuzz_round_trip():
    rng = random.Random(1234)
    alphabet = list("ab *^~\\\n") + ["বা", "ع"]
    for _ in range(3000):
        runs = [Run("".join(rng.choice(alphabet) for _ in range(rng.randint(0, 4))),
                    bold=rng.random() < .4, italic=rng.random() < .4, sup=rng.random() < .2, sub=rng.random() < .2)
                for _ in range(rng.randint(1, 5))]
        markup = runs_to_markup(runs)
        assert canon(parse_inline(markup)) == canon(_expected_after_trim(runs)), (runs, markup)


def test_serializer_closes_before_it_opens():
    """Found in the Phase 8 browser run: NO3- showed as 'NO~3^~−^' in the editor."""
    assert runs_to_markup([Run("NO"), Run("3", sub=True), Run("−", sup=True)]) == "NO~3~^−^"
    assert runs_to_markup([Run("a", italic=True), Run("b", bold=True)]) == "*a***b**"


def test_escape_makes_any_text_literal():
    rng = random.Random(7)
    for _ in range(2000):
        s = "".join(rng.choice("ab *^~\\ \n") for _ in range(rng.randint(0, 12)))
        assert styles(escape(s)) == ([(s, False, False, False, False)] if s else [("", False, False, False, False)])


def test_markup_is_idempotent_through_parse():
    src = "Mix **bold**, *it*, ***both***, H~2~O, x^2^, \\*literal\\*."
    once = runs_to_markup(parse_inline(src))
    assert runs_to_markup(parse_inline(once)) == once
    assert canon(parse_inline(once)) == canon(parse_inline(src))


# ------------------------------------------------------------------ content schema
def doc(**kw):
    return DocumentContent.model_validate({"body": [], **kw})


def test_content_tree_with_nested_boxes_round_trips():
    data = {
        "schema_version": SCHEMA_VERSION, "language": "bn-BD", "title": "শিরোনাম",
        "body": [{"type": "section", "title": "A", "content": [
            {"type": "paragraph", "text": "p"},
            {"type": "section", "title": "B", "content": [
                {"type": "table", "caption": "t", "data": [["h1", "h2"], ["1"]]},
                {"type": "figure", "asset_id": "x", "caption": "f"},
                {"type": "list", "ordered": True, "items": [{"text": "a", "children": [{"text": "b"}]}]},
            ]},
        ]}],
    }
    c = DocumentContent.model_validate(data)
    again = DocumentContent.model_validate_json(c.model_dump_json())
    assert again == c
    table = c.body[0].content[1].content[0]
    assert table.data == [["h1", "h2"], ["1", ""]]              # ragged rows padded


def test_missing_schema_version_defaults_and_future_version_is_rejected():
    assert doc().schema_version == SCHEMA_VERSION
    with pytest.raises(ValidationError, match="schema_version"):
        doc(schema_version=SCHEMA_VERSION + 1)
    with pytest.raises(ValidationError):
        doc(schema_version=0)


@pytest.mark.parametrize("box", [
    {"type": "paragraph", "text": "x", "font": "Comic Sans"},
    {"type": "paragraph", "text": "x", "style": {"color": "FF0000"}},
    {"type": "table", "data": [["a"]], "font_size": 30},
    {"type": "section", "title": "s", "bold": True},
    {"type": "list", "items": [{"text": "a", "color": "red"}]},
    {"type": "video", "src": "x"},
])
def test_formatting_and_unknown_fields_are_rejected(box):
    with pytest.raises(ValidationError):
        doc(body=[box])


def test_top_level_formatting_fields_are_rejected():
    with pytest.raises(ValidationError):
        doc(font="Arial")


@pytest.mark.parametrize("lang", ["en", "bn", "bn-BD", "ar-SA", "zh-Hans-CN", "hi-IN"])
def test_language_tags_accepted(lang):
    assert doc(language=lang).language == lang


@pytest.mark.parametrize("lang", ["", "e", "english language", 'en"><x', "en_US_" + "x" * 20])
def test_bad_language_tags_rejected(lang):
    with pytest.raises(ValidationError):
        doc(language=lang)


def _nested_list(depth):
    item = {"text": "leaf"}
    for _ in range(depth - 1):
        item = {"text": "x", "children": [item]}
    return {"type": "list", "items": [item]}


def _nested_sections(depth):
    box = {"type": "paragraph", "text": "leaf"}
    for _ in range(depth):
        box = {"type": "section", "title": "s", "content": [box]}
    return box


def test_list_depth_limited_to_word_levels():
    doc(body=[_nested_list(9)])
    with pytest.raises(ValidationError, match="nest"):
        doc(body=[_nested_list(10)])


def test_section_depth_limit_guards_against_recursion_bombs():
    doc(body=[_nested_sections(20)])                 # deeper than 9 is clamped (with a warning) by the generator
    with pytest.raises(ValidationError, match="nest"):
        doc(body=[_nested_sections(21)])


def test_deep_json_nesting_fails_cleanly():
    box = {"type": "paragraph", "text": "x"}
    for _ in range(3000):
        box = {"type": "section", "title": "s", "content": [box]}
    with pytest.raises(ValidationError):
        DocumentContent.model_validate_json(json.dumps({"body": [box]}))


def test_table_limits():
    TableBox(data=[["a"] * 63])
    with pytest.raises(ValidationError):
        TableBox(data=[["a"] * 64])                  # Word's column maximum is 63
    with pytest.raises(ValidationError):
        TableBox(data=[["a"]], header_rows=-1)
    assert TableBox(data=[["a"], ["b"]], header_rows=5).header_rows == 2   # clamped to the row count
    assert TableBox(data=[], header_rows=1).header_rows == 0


def test_table_cells_must_be_text():
    with pytest.raises(ValidationError):
        TableBox(data=[[{"text": "a", "bold": True}]])


# ------------------------------------------------------------------ profile schema
def test_profile_defaults_and_round_trip():
    p = FormattingProfile()
    assert p.table.label == "Table" and p.figure.label == "Figure"
    assert p.labels.source == "Source" and p.labels.note == "Note"
    assert FormattingProfile.model_validate_json(p.model_dump_json()) == p


def test_caption_labels_are_configurable_per_profile():
    p = FormattingProfile.model_validate({"table": {"label": "সারণি"}, "figure": {"label": "চিত্র"},
                                          "labels": {"source": "উৎস", "note": "টীকা"}})
    assert (p.table.label, p.figure.label, p.labels.source, p.labels.note) == ("সারণি", "চিত্র", "উৎস", "টীকা")


def test_profile_roles_must_be_known():
    FormattingProfile(roles={"heading_1": "Heading1", "list_bullet": "ListBullet", "caption": "Caption"})
    with pytest.raises(ValidationError, match="role"):
        FormattingProfile(roles={"heading_10": "Heading10"})
    with pytest.raises(ValidationError):
        FormattingProfile(roles={"body": ""})


def test_profile_origins_values_are_restricted():
    FormattingProfile(origins={"roles.body": "template", "table.borders": "default",
                               "table.alignment": "inferred", "labels.source": "user"})
    with pytest.raises(ValidationError):
        FormattingProfile(origins={"roles.body": "guess"})


@pytest.mark.parametrize("shading, ok", [("D9D9D9", True), ("abcdef", True), (None, True),
                                          ("#D9D9D9", False), ("red", False), ('D9"/><x', False)])
def test_header_shading_must_be_hex(shading, ok):
    if ok:
        FormattingProfile.model_validate({"table": {"header_shading": shading}})
    else:
        with pytest.raises(ValidationError):
            FormattingProfile.model_validate({"table": {"header_shading": shading}})


def test_profile_rejects_unknown_fields_and_future_versions():
    with pytest.raises(ValidationError):
        FormattingProfile.model_validate({"table": {"font": "Arial"}})
    with pytest.raises(ValidationError, match="schema_version"):
        FormattingProfile(schema_version=99)
    with pytest.raises(ValidationError):
        FormattingProfile.model_validate({"language": {"code": "bad code"}})


@pytest.mark.parametrize("field, value", [("table.wide_table_font_pt", 0), ("table.cell_font_pt", -1),
                                          ("table.wide_table_columns", 0), ("figure.max_height_cm", 0)])
def test_profile_numeric_ranges(field, value):
    section, key = field.split(".")
    with pytest.raises(ValidationError):
        FormattingProfile.model_validate({section: {key: value}})


def test_template_fields_are_validated():
    assert doc(fields={"DOI": "10.1/x", "AFFILIATION_1": "Dhaka"}).fields["DOI"] == "10.1/x"
    with pytest.raises(ValidationError):
        doc(fields={"bad key!": "x"})
    with pytest.raises(ValidationError):
        doc(fields={"X": "y" * 10_001})
