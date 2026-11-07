"""Phase 4: the paste normalizer on realistic clipboard content (tests/paste_samples/)."""
import os

import pytest

from app.paste.normalizer import normalize
from app.schemas.content import FigureBox, ListBox, ParagraphBox, SectionBox, TableBox

D = os.path.join(os.path.dirname(__file__), "paste_samples")


def load(name):
    raw = open(os.path.join(D, name), encoding="utf-8", newline="").read()
    return normalize(html=raw) if name.endswith(".html") else normalize(text=raw)


def walk(boxes):
    for b in boxes:
        yield b
        if isinstance(b, SectionBox):
            yield from walk(b.content)


def of(res, kind):
    return [b for b in walk(res.boxes) if isinstance(b, kind)]


def titles(boxes, depth=1):
    out = []
    for b in boxes:
        if isinstance(b, SectionBox):
            out.append((depth, b.title))
            out += titles(b.content, depth + 1)
    return out


def tree(items):
    return [(it.text, tree(it.children)) if it.children else it.text for it in items]


def codes(res):
    return {w["code"] for w in res.warnings}


# ------------------------------------------------------------------ Word
def test_word_structure():
    r = load("word.html")
    assert r.title == "Water Quality in Urban Rivers"
    assert titles(r.boxes) == [(1, "Introduction"), (2, "Study area"), (1, "Conclusion")]
    lists = of(r, ListBox)
    assert [l.ordered for l in lists] == [False, True]
    assert tree(lists[0].items) == [("Upstream site", ["Forest catchment"]), "Downstream site"]
    assert tree(lists[1].items) == [("Collect 1 L of water", ["Rinse the bottle twice"]), "Cool to 4 °C"]
    t = of(r, TableBox)[0]
    assert t.caption == "Mean concentrations by site" and t.source == "Field survey, 2023"


def test_word_source_newlines_are_spaces_not_line_breaks():
    r = load("word.html")
    para = of(r, ParagraphBox)[0].text
    assert "\n" not in para
    assert para.startswith("Rivers in fast-growing cities carry **nitrates**, *E. coli*")


def test_word_drops_source_formatting_and_keeps_semantics():
    r = load("word.html")
    para = of(r, ParagraphBox)[0].text
    assert "NO~3~" in para.replace("^~", "~^") or "NO~3" in para       # subscript survives
    for b in walk(r.boxes):
        assert "Times New Roman" not in str(b) and "#2F5496" not in str(b) and "color" not in str(b)


def test_header_row_cells_carry_no_bold_markup():
    for name in ("word.html", "gdocs.html"):
        t = of(load(name), TableBox)[0]
        assert not any("**" in c for c in t.data[0]), (name, t.data[0])
    assert of(load("word.html"), TableBox)[0].data[0] == ["Site", "NO~3~ (mg/L)"]


# ------------------------------------------------------------------ Google Docs
def test_gdocs_title_nested_list_caption_note():
    r = load("gdocs.html")
    assert r.title == "Annual Report 2024"
    assert titles(r.boxes) == [(1, "Overview"), (2, "Outlook")]          # <h1> then <h2>
    lst = of(r, ListBox)[0]
    assert tree(lst.items) == [("Asia", ["Bangladesh"]), "Europe"]
    t = of(r, TableBox)[0]
    assert t.caption == "Revenue by region" and t.note == "Unaudited figures."
    assert "HEADING_GUESSED" not in codes(r)


def test_gdocs_inline_emphasis():
    p = of(load("gdocs.html"), ParagraphBox)[0].text
    assert p == "Revenue grew **18%** *year on year*; see the table.^1^"


# ------------------------------------------------------------------ Excel
def test_excel_html_table():
    t = of(load("excel.html"), TableBox)[0]
    assert t.data == [["District", "2022", "2023", "Change"], ["Dhaka", "1,250", "1,310", "4.8"],
                      ["Sylhet", "410", "", "-"]]


def test_excel_tsv_quoted_cells_and_empty_cells():
    r = load("excel.tsv")
    tables = of(r, TableBox)
    assert len(tables) == 1 and not of(r, ParagraphBox)
    assert tables[0].data == [["Item", "Qty", "Notes"], ["Pens", "12", "blue and\nblack"],
                              ["Paper", "500", ""], ["Ink", "", 'out of "stock"']]


def test_tsv_leading_empty_cell_keeps_columns():
    r = normalize(text="\tQ1\tQ2\nNorth\t5\t6\n")
    assert of(r, TableBox)[0].data == [["", "Q1", "Q2"], ["North", "5", "6"]]


# ------------------------------------------------------------------ Markdown (AI chat)
def test_chatgpt_markdown():
    r = load("chatgpt.md")
    assert r.title == "Impact of Remote Work on Productivity"
    assert titles(r.boxes) == [(1, "Introduction"), (1, "Methodology"), (2, "Data sources"),
                               (1, "Results"), (1, "Conclusion")]
    t = of(r, TableBox)[0]
    assert t.caption == "Productivity change by role" and t.source == "Company survey, 2024"
    assert t.data[1] == ["Engineer", "+12", "540"]
    first = of(r, ListBox)[0]
    assert first.ordered and tree(first.items)[0] == ("**Survey** of 1,200 employees", ["Online questionnaire", "25 questions"])


# ------------------------------------------------------------------ plain text, Bangla and others
def test_bangla_plain_text():
    r = load("bangla.txt")
    assert r.title == "ঢাকা শহরের বায়ুদূষণ: একটি সমীক্ষা"
    assert titles(r.boxes) == [(1, "ভূমিকা"), (2, "গবেষণার উদ্দেশ্য"), (2, "পদ্ধতি"), (1, "উপসংহার")]
    bullets, steps = of(r, ListBox)
    assert tree(bullets.items) == ["দূষণের উৎস চিহ্নিত করা", ("স্বাস্থ্যঝুঁকি মূল্যায়ন", ["শিশুদের ঝুঁকি"]), "সমাধান প্রস্তাব"]
    assert steps.ordered and tree(steps.items) == ["এলাকা নির্বাচন", "নমুনা সংগ্রহ", "বিশ্লেষণ"]
    t = of(r, TableBox)[0]
    assert t.caption == "এলাকাভিত্তিক বায়ুমান সূচক" and t.source == "পরিবেশ অধিদপ্তর, ২০২৩"
    assert t.data[1] == ["মিরপুর", "১৮৫", "অস্বাস্থ্যকর"]
    fig = of(r, FigureBox)[0]                       # typed caption without an image -> figure slot to upload
    assert fig.caption == "মাসিক গড় দূষণ" and fig.src is None
    assert "FIGURE_NEEDS_UPLOAD" in codes(r)


def test_plain_text_letter_lists_and_note_source_lines():
    r = load("plain_mixed.txt")
    lst = of(r, ListBox)[0]
    assert lst.ordered and tree(lst.items) == ["higher rents", "longer commutes", "more noise"]
    assert of(r, ParagraphBox)[1].text == "Smith (2019) found three effects:"
    t = of(r, TableBox)[0]
    assert t.caption == "Population by year (thousands)"
    assert t.note == "Estimates for 2021." and t.source == "National census"
    fig = of(r, FigureBox)[0]
    assert fig.caption == "Map of the study area"


def test_plain_text_numbered_headings_in_several_scripts():
    r = load("plain_mixed.txt")
    assert titles(r.boxes) == [(1, "Background"), (2, "Earlier studies"), (2, "Gaps"), (1, "Data"),
                               (1, "النتائج"), (1, "निष्कर्ष")]


@pytest.mark.parametrize("text", [
    "a) one\nb) two\nc) three\n",
    "i. one\nii. two\niii. three\n",
    "(a) one\n(b) two\n",
    "A. one\nB. two\n",
])
def test_letter_and_roman_lists(text):
    r = normalize(text=text)
    lst = of(r, ListBox)
    assert lst and lst[0].ordered and [it.text for it in lst[0].items][0] == "one"


def test_a_lone_letter_line_is_not_a_list():
    r = normalize(text="a) this is just one line that happens to start like a list item.\n")
    assert not of(r, ListBox)


def test_title_is_not_taken_from_a_sentence():
    r = normalize(text="This is a normal sentence that ends with a period.\n\n# Heading\nBody.\n")
    assert r.title == ""


def test_caption_never_becomes_a_heading():
    r = normalize(html="<p><b>Figure 3: Workflow</b></p><p><b>Methods</b></p><p>text</p>")
    assert titles(r.boxes) == [(1, "Methods")]
    assert of(r, FigureBox)[0].caption == "Workflow"
