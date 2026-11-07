"""A neutral sample article used to preview a design in the gallery (any design, no real people)."""
from ..schemas.article import ArticleContent

_P = ("This paragraph shows the body text of the design: font, size, alignment, spacing and the indent of "
      "paragraphs that follow the first one after a heading. ")


def sample_article() -> ArticleContent:
    return ArticleContent.model_validate({
        "metadata": {
            "title": "Title of the Research Article", "doi": "10.0000/sample.0001", "volume": "1", "issue": "1",
            "pages": "1-10", "year": "2026", "received": "1 January 2026", "accepted": "1 February 2026",
            "published": "1 March 2026", "corresponding_email": "author@example.org",
            "affiliations": [{"id": "1", "department": "Department", "institution": "University", "country": "Country"},
                             {"id": "2", "institution": "Research Institute", "country": "Country"}],
            "authors": [{"name": "First Author", "affiliations": ["1"], "corresponding": True},
                        {"name": "Second Author", "affiliations": ["1", "2"]}]},
        "abstract": "The abstract summarises the article. " * 4,
        "keywords": ["keyword one", "keyword two", "keyword three"],
        "body": [
            {"type": "section", "title": "First section", "content": [
                {"type": "paragraph", "text": _P}, {"type": "paragraph", "text": _P},
                {"type": "section", "title": "A subsection", "content": [
                    {"type": "paragraph", "text": _P},
                    {"type": "list", "ordered": False, "items": [{"text": "A bullet point"}, {"text": "Another point"}]},
                    {"type": "table", "caption": "A table caption", "source": "Source of the data",
                     "data": [["Column", "Value"], ["A", "1"], ["B", "2"]]}]}]},
            {"type": "section", "title": "Second section", "content": [{"type": "paragraph", "text": _P}]}],
        "back_matter": {"acknowledgements": "Acknowledgement text.", "funding": "Funding statement."},
        "references": ["Author, A.A. and Author, B.B. (2025) 'Title of article', Journal Name, 1(1), pp. 1-10."],
    })
