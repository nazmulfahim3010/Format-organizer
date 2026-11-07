"""Predefined designs, component 1: the article document schema (independent of any visual design)."""
import pytest
from pydantic import ValidationError

from app.schemas.article import ARTICLE_SCHEMA_VERSION, ArticleContent


def article(**kw):
    base = {"metadata": {"title": "T"}}
    base.update(kw)
    return ArticleContent.model_validate(base)


def test_minimal_article_and_defaults():
    a = article()
    assert a.schema_version == ARTICLE_SCHEMA_VERSION and a.body == [] and a.references == []
    assert a.back_matter.acknowledgements == "" and a.metadata.authors == []


def test_full_article_round_trip():
    data = {
        "metadata": {
            "title": "Water and Peace", "doi": "10.1/x", "volume": "01", "issue": "04", "pages": "1-9", "year": "2026",
            "received": "1 May 2026", "accepted": "2 June 2026", "published": "3 July 2026",
            "corresponding_email": "a@example.org",
            "affiliations": [{"id": "1", "department": "Dept A", "institution": "Uni A", "country": "Bangladesh"},
                             {"id": "2", "institution": "Uni B"}],
            "authors": [{"name": "A One", "affiliations": ["1"], "corresponding": True, "orcid": "0000-0002-1825-0097"},
                        {"name": "B Two", "affiliations": ["1", "2"]}]},
        "abstract": "We **study** it.", "keywords": ["water", "peace"],
        "body": [{"type": "section", "title": "Introduction", "content": [{"type": "paragraph", "text": "x"},
                 {"type": "section", "title": "Background", "content": [{"type": "table", "data": [["a"]]}]}]}],
        "back_matter": {"acknowledgements": "Thanks.", "funding": "None."},
        "references": ["Author, A. (2020) Title.", "Author, B. (2021) Other."],
    }
    a = ArticleContent.model_validate(data)
    assert ArticleContent.model_validate_json(a.model_dump_json()) == a
    assert a.metadata.corresponding_author.name == "A One"


def test_author_affiliations_must_exist():
    with pytest.raises(ValidationError, match="affiliation"):
        article(metadata={"title": "T", "affiliations": [{"id": "1", "institution": "U"}],
                          "authors": [{"name": "A", "affiliations": ["9"]}]})


def test_duplicate_affiliation_ids_rejected():
    with pytest.raises(ValidationError):
        article(metadata={"title": "T", "affiliations": [{"id": "1"}, {"id": "1"}]})


@pytest.mark.parametrize("orcid, ok", [("0000-0002-1825-0097", True), ("0000-0002-1694-233X", True),
                                       ("https://orcid.org/0000-0002-1825-0097", True), ("1234", False)])
def test_orcid_format(orcid, ok):
    payload = {"metadata": {"title": "T", "authors": [{"name": "A", "orcid": orcid}]}}
    if ok:
        assert ArticleContent.model_validate(payload).metadata.authors[0].orcid.endswith(orcid[-19:])
    else:
        with pytest.raises(ValidationError):
            ArticleContent.model_validate(payload)


def test_only_one_corresponding_author():
    with pytest.raises(ValidationError, match="corresponding"):
        article(metadata={"title": "T", "authors": [{"name": "A", "corresponding": True},
                                                    {"name": "B", "corresponding": True}]})


def test_formatting_fields_and_unknown_keys_are_rejected():
    with pytest.raises(ValidationError):
        article(font="Arial")
    with pytest.raises(ValidationError):
        article(metadata={"title": "T", "title_font_size": 30})
    with pytest.raises(ValidationError):
        article(body=[{"type": "paragraph", "text": "x", "color": "red"}])


def test_body_uses_the_shared_depth_limits():
    box = {"type": "paragraph", "text": "leaf"}
    for _ in range(21):
        box = {"type": "section", "title": "s", "content": [box]}
    with pytest.raises(ValidationError, match="nest"):
        article(body=[box])


def test_no_section_names_are_required():
    a = article(body=[{"type": "section", "title": "Whatever the author wants", "content": []}])
    assert a.body[0].title == "Whatever the author wants"


def test_size_limits():
    with pytest.raises(ValidationError):
        article(references=["x"] * 2001)
    with pytest.raises(ValidationError):
        article(keywords=["k"] * 51)
    with pytest.raises(ValidationError):
        article(abstract="x" * 20_001)
