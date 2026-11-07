"""Built-in sample document used to preview a profile BEFORE it is approved."""
import io

from PIL import Image, ImageDraw

from ..schemas.content import DocumentContent


def sample_image_bytes() -> bytes:
    im = Image.new("RGB", (1200, 700), (236, 241, 250))
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, 1160, 660], outline=(40, 70, 150), width=8)
    d.line([40, 40, 1160, 660], fill=(200, 60, 60), width=6)
    b = io.BytesIO(); im.save(b, "PNG", dpi=(96, 96)); return b.getvalue()


def sample_content(language: str = "en") -> DocumentContent:
    return DocumentContent.model_validate({
        "language": language,
        "title": "Sample Document Title", "subtitle": "Preview of your formatting rules",
        "authors": [{"name": "Author One", "affiliation": "Example University", "email": "author@example.org"}],
        "abstract": "This sample shows **bold**, *italic*, H~2~O and x^2^ using your template styles.",
        "keywords": ["template", "formatting"],
        "body": [
            {"type": "section", "title": "Introduction", "content": [
                {"type": "paragraph", "text": "A normal paragraph of body text, formatted by the style mapped to the body role."},
                {"type": "section", "title": "Background", "content": [
                    {"type": "paragraph", "text": "A paragraph inside a subsection."},
                    {"type": "section", "title": "Details", "content": [{"type": "paragraph", "text": "A third-level paragraph."}]}]},
                {"type": "list", "ordered": False, "items": [{"text": "First point", "children": [{"text": "Nested point"}]}, {"text": "Second point"}]},
                {"type": "list", "ordered": True, "items": [{"text": "Step one"}, {"text": "Step two"}]}]},
            {"type": "section", "title": "Results", "content": [
                {"type": "table", "caption": "Sample results", "source": "Author",
                 "data": [["Method", "Accuracy", "F1"], ["A", "91%", "0.90"], ["B", "94%", "0.93"]]},
                {"type": "figure", "asset_id": "__sample__", "caption": "Sample figure", "source": "Author"}]},
        ],
    })
