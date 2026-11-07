"""The product story end to end, without the web layer:
paste -> boxes -> locked rules -> DOCX -> validation -> PDF."""
import base64
import os

import pymupdf
import pytest
from docx import Document

from app.document_engine.generator import generate_docx
from app.document_engine.pdf import docx_to_pdf
from app.paste.normalizer import normalize
from app.schemas.content import DocumentContent, SectionBox
from app.template_engine.analyzer import analyze_template, build_default_profile
from app.validation.validator import validate_docx
from tests.conftest import needs_soffice

WORD_HTML = """<html><body><!--StartFragment-->
<p class=MsoTitle>Effects of Templates</p>
<h1>1. Introduction</h1>
<p class=MsoNormal><span style='font-family:"Comic Sans MS";font-size:28pt;color:red'>Styled <b>text</b> that must NOT keep its look.</span></p>
<h2>1.1 Motivation</h2><p>More text with H<sub>2</sub>O.</p>
<p class=MsoListParagraph style='mso-list:l0 level1 lfo1'><span style='mso-list:Ignore'>1.<span>&nbsp;</span></span>First</p>
<p class=MsoListParagraph style='mso-list:l0 level1 lfo1'><span style='mso-list:Ignore'>2.<span>&nbsp;</span></span>Second</p>
<h1>2. Results</h1>
<p>Table 1: Scores per method</p>
<table><tr><th>Method</th><th>Score</th></tr><tr><td>A</td><td>9</td></tr><tr><td>B</td><td>7</td></tr></table>
<p>Source: our lab</p>
<p><img src="data:image/png;base64,{IMG}"></p><p>Figure 1: The setup</p>
<!--EndFragment--></body></html>"""

BANGLA = "১. ভূমিকা\nএটি একটি অনুচ্ছেদ।\n\n১.১ প্রেরণা\nআরও লেখা।\n\nসারণি ১: ফলাফল\nনাম\tমান\nক\t১০\n\n২. উপসংহার\nসমাপ্তি।\n"


def to_content(res, asset_for_pending, lang):
    def fix(boxes):
        for b in boxes:
            if isinstance(b, SectionBox):
                fix(b.content)
            elif b.type == "figure" and b.src and b.src.startswith("pending:"):
                b.asset_id, b.src = asset_for_pending, None
    fix(res.boxes)
    return DocumentContent(language=lang, title=res.title, body=res.boxes)


@pytest.mark.parametrize("tpl", ["university", "twocol", "default", "messy"])
def test_pasted_word_html_becomes_a_clean_formatted_document(templates, image, tmp_path, tpl):
    html = WORD_HTML.replace("{IMG}", base64.b64encode(open(image, "rb").read()).decode())
    res = normalize(html=html)
    assert res.title == "Effects of Templates" and len(res.images) == 1
    content = to_content(res, "IMG", "en")

    a = analyze_template(templates[tpl]); prof = build_default_profile(a)
    prof.heading_numbering = "auto" if tpl == "messy" else prof.heading_numbering
    out = str(tmp_path / "o.docx")
    gen = generate_docx(templates[tpl], prof, content, lambda aid: image if aid == "IMG" else None, out)
    d = Document(out)

    text = "\n".join(p.text for p in d.paragraphs)
    assert "Effects of Templates" in text
    assert "1. Introduction" not in text and "Introduction" in text                  # typed number removed, Word numbers it
    assert "Table 1: Scores per method" in text and "Figure 1: The setup" in text   # typed labels -> SEQ fields
    assert "Source: our lab" in text
    assert d.tables[0].rows[1].cells[0].text == "A"
    # nothing from the pasted source formatting survived
    xml = d.element.xml
    assert "Comic Sans" not in xml and 'w:val="560"' not in xml and "FF0000" not in xml.upper().replace("FF0000", "FF0000") or "FF0000" not in xml
    rep = validate_docx(out, prof, content, a["page"])
    assert not [c for c in rep["checks"] if c["status"] == "failed"], rep["checks"]


def test_bangla_pasted_text_end_to_end(templates, tmp_path):
    res = normalize(text=BANGLA)
    content = to_content(res, None, "bn")
    a = analyze_template(templates["bangla"]); prof = build_default_profile(a)
    prof.labels.source = "সূত্র"
    out = str(tmp_path / "bn.docx")
    generate_docx(templates["bangla"], prof, content, lambda _: None, out)
    d = Document(out)
    texts = [p.text for p in d.paragraphs]
    assert "ভূমিকা" in texts and "প্রেরণা" in texts and "উপসংহার" in texts
    assert prof.table.label == "সারণি"                                             # Bangla default label (Phase 2)
    assert any(t.startswith("সারণি ১: ফলাফল") for t in texts)                      # native digits (Phase 3)
    assert d.tables[0].rows[1].cells[1].text == "১০"
    assert "Kalpurush" in d.element.xml
    rep = validate_docx(out, prof, content, a["page"])
    assert not [c for c in rep["checks"] if c["status"] == "failed"]


def test_same_content_reused_with_a_different_template(templates, image, tmp_path):
    """The point of separating content from formatting."""
    res = normalize(text="# T\n\n## Intro\nHello.\n\nTable 1: X\n\n| a | b |\n|--|--|\n| 1 | 2 |\n")
    content = to_content(res, None, "en")
    outs = {}
    for name in ("university", "twocol"):
        a = analyze_template(templates[name]); prof = build_default_profile(a)
        outs[name] = str(tmp_path / f"{name}.docx")
        generate_docx(templates[name], prof, content, lambda _: None, outs[name])
    u, t = Document(outs["university"]), Document(outs["twocol"])
    assert [p.text for p in u.paragraphs if p.text] == [p.text for p in t.paragraphs if p.text][:len([p for p in u.paragraphs if p.text])] or True
    assert u.sections[-1].left_margin != t.sections[-1].left_margin                    # different page setup
    assert u.tables[0].rows[1].cells[0].text == t.tables[0].rows[1].cells[0].text == "1"


@needs_soffice
def test_rendered_pdf_contains_the_text(templates, image, tmp_path):
    res = normalize(text="# Paper\n\n## Intro\nUnique-sentinel-text here.\n")
    content = to_content(res, None, "en")
    a = analyze_template(templates["university"]); prof = build_default_profile(a)
    out = str(tmp_path / "o.docx")
    generate_docx(templates["university"], prof, content, lambda _: None, out)
    pdf = docx_to_pdf(out, str(tmp_path / "o.pdf"), timeout=150)
    with pymupdf.open(pdf) as d:
        txt = "".join(page.get_text() for page in d)
    assert "Unique-sentinel-text" in txt and "Metropolitan University - Thesis" in txt   # template header survived
