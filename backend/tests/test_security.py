import io
import time
import zipfile

import pytest
from PIL import Image

from app.core.ratelimit import RateLimiter
from app.core.security import create_token, hash_password, read_token, verify_password
from app.core.uploads import UploadRejected, check_docx, sanitize_image
from app.document_engine.pdf import PdfExportError, docx_to_pdf
from tests.conftest import needs_soffice


def _zip(files: dict) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return b.getvalue()


GOOD = {"[Content_Types].xml": "<Types/>", "_rels/.rels": "<Relationships/>",
        "word/document.xml": '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'}


def test_real_template_is_accepted(templates):
    data = open(templates["university"], "rb").read()
    assert check_docx(data, "t.docx").size == len(data)


@pytest.mark.parametrize("name,data,msg", [
    ("a.doc", b"PK\x03\x04", "Only .docx"),
    ("a.docx", b"MZ not a zip", "signature"),
    ("a.docx", b"PK\x03\x04garbage", "corrupt"),
    ("a.docx", _zip({"x.txt": "hi"}), "Word document"),
    ("a.docx", _zip({**GOOD, "word/vbaProject.bin": "x"}), "Macro"),
    ("a.docx", _zip({**GOOD, "[Content_Types].xml": "<Types ContentType='application/vnd.ms-word.document.macroEnabled.main+xml'/>"}), "Macro"),
    ("a.docx", _zip({**GOOD, "word/document.xml": '<!DOCTYPE x [<!ENTITY a "b">]><w:document/>'}), "DOCTYPE"),
    ("a.docx", _zip({**GOOD, "word/_rels/settings.xml.rels": '<Relationship Type="http://x/attachedTemplate" Target="http://evil/t.dotm" TargetMode="External"/>'}), "remote template"),
    ("a.docx", _zip({**GOOD, "../evil.xml": "x"}), "unsafe"),
])
def test_dangerous_docx_is_rejected(name, data, msg):
    with pytest.raises(UploadRejected) as e:
        check_docx(data, name)
    assert msg.lower() in str(e.value).lower()


def test_zip_bomb_rejected():
    data = _zip({**GOOD, "word/big.xml": "0" * (60 * 1024 * 1024)})
    assert len(data) < 200_000
    with pytest.raises(UploadRejected) as e:
        check_docx(data, "a.docx")
    assert "bomb" in str(e.value).lower() or "unreasonable" in str(e.value).lower()


def test_oversize_rejected():
    with pytest.raises(UploadRejected):
        check_docx(b"PK\x03\x04" + b"0" * (21 * 1024 * 1024), "a.docx")


def _img(fmt, size=(50, 40), mode="RGB", **kw):
    b = io.BytesIO(); Image.new(mode, size, (10, 20, 30)).save(b, fmt, **kw); return b.getvalue()


def test_image_sanitized_and_exif_removed():
    im = Image.new("RGB", (60, 40), (1, 2, 3))
    exif = Image.Exif(); exif[0x010E] = "SECRET-DESCRIPTION"
    b = io.BytesIO(); im.save(b, "JPEG", exif=exif.tobytes())
    assert b"SECRET-DESCRIPTION" in b.getvalue()
    out, ext, w, h = sanitize_image(b.getvalue())
    assert ext == "jpg" and (w, h) == (60, 40) and b"SECRET-DESCRIPTION" not in out


def test_png_with_alpha_and_gif_are_converted():
    out, ext, *_ = sanitize_image(_img("PNG", mode="RGBA"))
    assert ext == "png" and Image.open(io.BytesIO(out)).mode == "RGBA"
    out, ext, *_ = sanitize_image(_img("GIF", mode="P"))
    assert ext == "png"


def test_large_image_is_downscaled():
    out, ext, w, h = sanitize_image(_img("PNG", size=(5000, 2500)))
    assert max(w, h) == 4000 and w / h == pytest.approx(2.0, abs=0.01)


@pytest.mark.parametrize("data", [b"not an image", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"GIF89a" + b"\x00" * 5])
def test_bad_images_rejected(data):
    with pytest.raises(UploadRejected):
        sanitize_image(data)


def test_passwords_and_tokens():
    h = hash_password("pw-1234")
    assert verify_password("pw-1234", h) and not verify_password("nope", h) and not verify_password("x", "garbage")
    t = create_token(7, "secret")
    assert read_token(t, "secret") == 7
    assert read_token(t, "other") is None
    assert read_token(t[:-2] + "xx", "secret") is None
    assert read_token(create_token(7, "secret", ttl_seconds=-1), "secret") is None
    assert read_token("garbage", "secret") is None


def test_rate_limiter():
    now = [0.0]
    rl = RateLimiter(3, 10, clock=lambda: now[0])
    assert [rl.allow("u") for _ in range(4)] == [True, True, True, False]
    assert rl.allow("other")
    now[0] = 11
    assert rl.allow("u")


@needs_soffice
def test_pdf_export(templates, tmp_path):
    out = docx_to_pdf(templates["university"], str(tmp_path / "o.pdf"))
    assert open(out, "rb").read(5) == b"%PDF-"


def test_pdf_export_without_libreoffice_gives_clear_error(monkeypatch, tmp_path):
    import app.document_engine.pdf as pdf
    monkeypatch.setattr(pdf, "soffice_path", lambda: None)
    with pytest.raises(PdfExportError) as e:
        pdf.docx_to_pdf("x.docx", str(tmp_path / "o.pdf"))
    assert "not installed" in str(e.value)


@needs_soffice
def test_pdf_export_timeout_is_reported(templates, tmp_path):
    with pytest.raises(PdfExportError) as e:
        docx_to_pdf(templates["university"], str(tmp_path / "o.pdf"), timeout=0.001)
    assert "timed out" in str(e.value)
