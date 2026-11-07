from app.core.inline import parse_inline, runs_to_markup, escape, plain
from app.paste.normalizer import normalize
from app.schemas.content import SectionBox


def test_inline_roundtrip():
    src = "a **b** *c* H~2~O x^2^ \\*lit\\*"
    runs = parse_inline(src)
    assert [r.text for r in runs][0] == "a "
    assert any(r.bold and r.text == "b" for r in runs)
    assert any(r.sub and r.text == "2" for r in runs)
    assert plain(src) == "a b c H2O x2 *lit*"
    assert plain(runs_to_markup(runs)) == plain(src)


def test_escape_makes_literal_text_safe():
    assert plain(escape("2*3 ^ ~ \\")) == "2*3 ^ ~ \\"


def _flat(boxes):
    out = []
    for b in boxes:
        out.append(b)
        if isinstance(b, SectionBox):
            out.extend(_flat(b.content))
    return out


def test_markdown_structure_title_caption_source():
    md = """# My Paper

## 1. Introduction
Hello **bold** [link](http://x.y).

- a
  - a1
- b

Table 1: Results

| M | Acc |
|---|-----|
| A | 91% |

Source: Authors
"""
    r = normalize(text=md)
    assert r.title == "My Paper"
    sec = r.boxes[0]
    assert sec.title == "Introduction"                       # typed "1." removed
    kinds = [b.type for b in sec.content]
    assert kinds == ["paragraph", "list", "table"]
    lst = sec.content[1]
    assert [i.text for i in lst.items] == ["a", "b"] and lst.items[0].children[0].text == "a1"
    tbl = sec.content[2]
    assert tbl.caption == "Results" and tbl.source == "Authors"   # label + number removed
    assert tbl.data == [["M", "Acc"], ["A", "91%"]]


def test_bangla_numbered_text_and_caption_and_tab_table():
    tx = "১. ভূমিকা\nএটি অনুচ্ছেদ।\n\n১.১ প্রেরণা\nআরেকটি।\n\nসারণি ১: ফলাফল\nনাম\tমান\nক\t১০\n\n২. পদ্ধতি\n"
    r = normalize(text=tx)
    assert r.source_format == "text"
    assert [b.title for b in r.boxes] == ["ভূমিকা", "পদ্ধতি"]
    sub = r.boxes[0].content[1]
    assert isinstance(sub, SectionBox) and sub.title == "প্রেরণা"      # 1.1 -> nested
    tbl = [b for b in sub.content if b.type == "table"][0]
    assert tbl.caption == "ফলাফল" and tbl.data[1] == ["ক", "১০"]


def test_heading_levels_shift_and_skip_are_handled():
    r = normalize(html="<h3>Top</h3><p>x</p><h5>Deep</h5><p>y</p>")
    assert r.boxes[0].title == "Top"                                   # h3 becomes level 1
    assert r.boxes[0].content[1].title == "Deep"                       # skipped level moved up
    assert "HEADING_LEVEL_SKIPPED" in [w["code"] for w in r.warnings]


def test_word_fake_lists_and_title():
    h = """<p class=MsoTitle>Big Title</p><h1>1. Intro</h1>
    <p class=MsoListParagraph style='mso-list:l0 level1 lfo1'><span style='mso-list:Ignore'>·<span>&nbsp;</span></span>A</p>
    <p class=MsoListParagraph style='mso-list:l0 level2 lfo1'><span style='mso-list:Ignore'>o<span>&nbsp;</span></span>A1</p>
    <p class=MsoListParagraph style='mso-list:l0 level1 lfo1'><span style='mso-list:Ignore'>·<span>&nbsp;</span></span>B</p>"""
    r = normalize(html=h)
    assert r.title == "Big Title"
    lst = r.boxes[0].content[0]
    assert lst.type == "list" and lst.items[0].children[0].text == "A1" and lst.items[1].text == "B"


def test_google_docs_flat_lists_and_data_uri_image():
    g = ('<b style="font-weight:normal;"><h2><span style="font-weight:700">Methods</span></h2>'
         '<ul><li aria-level="1"><p>One</p></li></ul><ul><li aria-level="2"><p>One-a</p></li></ul>'
         '<p><img src="data:image/png;base64,iVBORw0KGgo="></p><p>Figure 3: A diagram</p></b>')
    r = normalize(html=g)
    sec = r.boxes[0]
    assert sec.title == "Methods"                                      # no bold markup leaks into the title
    assert sec.content[0].items[0].children[0].text == "One-a"
    fig = sec.content[1]
    assert fig.type == "figure" and fig.caption == "A diagram" and fig.src == "pending:0"
    assert len(r.images) == 1


def test_html_table_with_merged_cells_warns_and_th_is_header():
    h = "<table><tr><th colspan=2>Head</th></tr><tr><td>1</td><td>2</td></tr></table>"
    r = normalize(html=h)
    t = r.boxes[0]
    assert t.data == [["Head", ""], ["1", "2"]] and t.header_rows == 1
    assert "TABLE_MERGED_CELLS" in [w["code"] for w in r.warnings]


def test_formatting_from_source_is_dropped():
    r = normalize(html='<p style="font-family:Comic Sans;font-size:30pt;color:red">Plain <span style="font-weight:bold">B</span></p>')
    assert r.boxes[0].text == "Plain **B**"


def test_orphan_caption_stays_a_paragraph():
    r = normalize(text="Table 2 shows the results in detail.")
    assert r.boxes[0].type == "paragraph"


def test_sentence_about_a_table_is_not_eaten_as_caption():
    r = normalize(text="Table 2 shows the results in detail.\n\nA\tB\n1\t2\n")
    kinds = [b.type for b in r.boxes]
    assert kinds == ["paragraph", "table"]
    assert r.boxes[1].caption == ""
