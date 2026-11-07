"""Unit tests for {{PLACEHOLDER}} finding and filling (app/core/placeholders.py)."""
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

from app.core.placeholders import fill, names_in


def _p(*runs):
    rs = "".join(f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>' for t in runs)
    return parse_xml(f"<w:p {nsdecls('w')}>{rs}</w:p>")


def _text(p):
    return "".join(t.text or "" for t in p.iter(qn("w:t")))


def test_single_and_split_runs():
    a, b = _p("Dear {{NAME}},"), _p("{{FIR", "ST}} and ", "{{LAST}}!")
    left = fill([a, b], {"NAME": "Rahima", "FIRST": "A", "LAST": "B"})
    assert (_text(a), _text(b), left) == ("Dear Rahima,", "A and B!", set())


def test_unknown_names_stay_and_are_reported():
    p = _p("{{DOI}} / {{VOLUME}}")
    assert fill([p], {"DOI": "10.1/x"}) == {"VOLUME"} and _text(p) == "10.1/x / {{VOLUME}}"


def test_values_are_plain_text_and_xml_safe():
    p = _p("{{X}}")
    fill([p], {"X": 'a < b & "c"\nnext'})
    assert _text(p) == 'a < b & "c" next'


def test_every_paragraph_is_filled_on_repeated_runs():
    """Regression: paragraphs were de-duplicated by id() of lxml proxies; freed proxies' ids are reused,
    so some paragraphs (often in the header) were skipped at random."""
    for _ in range(30):
        body = [_p(f"line {i}") for i in range(300)]
        header = _p("DOI: {{DOI}}")
        assert fill(body + [header], {"DOI": "1"}) == set() and _text(header) == "DOI: 1"


def test_names_in_keeps_first_appearance_order():
    assert names_in([_p("{{B}} {{A}}"), _p("{{B}} {{C}}")]) == ["B", "A", "C"]
