"""Phase 6: hostile uploads, images, passwords/tokens, rate limiting, isolated PDF conversion."""
import io
import os
import subprocess
import sys
import threading
import time

import pytest
from PIL import Image

from app.core import security
from app.core.ratelimit import RateLimiter
from app.core.uploads import UploadRejected, check_docx, safe_xml, sanitize_image
from tests.conftest import needs_soffice
from tests.make_attacks import allowed, attacks


@pytest.fixture(scope="module")
def base(templates):
    return open(templates["university"], "rb").read()


ATTACK_NAMES = ["wrong_extension", "doc_binary", "password_protected", "oversized", "zip_bomb", "size_lie",
                "too_many_entries", "encrypted_entry", "duplicate_entry", "macro_vba", "macro_content_type",
                "activex", "ole_embedding", "xxe", "billion_laughs", "xxe_utf16", "xxe_hidden_part",
                "traversal_dotdot", "traversal_absolute", "traversal_drive", "traversal_backslash",
                "remote_template", "remote_template_single_quotes", "remote_image", "remote_frame",
                "dde_split_field", "includepicture_field", "includetext_field"]


def test_attack_list_is_complete(base):
    assert sorted(attacks(base)) == sorted(ATTACK_NAMES)


@pytest.mark.parametrize("name", ATTACK_NAMES)
def test_attack_is_rejected_before_parsing(base, name, monkeypatch):
    data, filename, msg = attacks(base)[name]
    # nothing may hand the file to python-docx before the checks finish
    import docx
    monkeypatch.setattr(docx, "Document", lambda *a, **k: pytest.fail("parsed before checking"))
    t0 = time.time()
    with pytest.raises(UploadRejected) as e:
        check_docx(data, filename)
    assert msg.lower() in str(e.value).lower(), str(e.value)
    assert time.time() - t0 < 10


@pytest.mark.parametrize("name", ["plain", "external_hyperlink", "page_field", "hyperlink_field",
                                  "chart_workbook", "compressed_media"])
def test_normal_template_features_are_allowed(base, name):
    check_docx(allowed(base)[name], "ok.docx")


@pytest.mark.parametrize("fixture", ["default", "university", "messy", "bangla", "twocol", "rtl"])
def test_all_fixture_templates_pass(templates, fixture):
    check_docx(open(templates[fixture], "rb").read(), f"{fixture}.docx")


def test_rejection_messages_do_not_leak_internals(base):
    for name, (data, filename, _) in attacks(base).items():
        try:
            check_docx(data, filename)
        except UploadRejected as e:
            text = str(e)
            assert "Traceback" not in text and "\\" not in text and "/tmp" not in text and len(text) < 200, name


def test_safe_xml_parser_never_resolves_entities():
    root = safe_xml(b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY e "EXPANDED">]><r>&e;</r>')
    assert "EXPANDED" not in (root.text or "")


def test_theme_is_parsed_with_the_safe_parser():
    import app.template_engine.ooxml as ooxml
    src = open(ooxml.__file__, encoding="utf-8").read()
    assert "etree.fromstring(part.blob)" not in src


# ------------------------------------------------------------------ images
def _png(size=(50, 30), mode="RGB", **save):
    b = io.BytesIO()
    Image.new(mode, size, (10, 200, 30) if mode == "RGB" else None).save(b, "PNG", **save)
    return b.getvalue()


def test_exif_orientation_is_applied_before_metadata_is_dropped():
    im = Image.new("RGB", (200, 100), (255, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6                      # "rotate 90° CW to display"
    exif[0x010F] = "SecretCam"            # camera make: must not survive
    b = io.BytesIO()
    im.save(b, "JPEG", exif=exif)
    clean, ext, w, h = sanitize_image(b.getvalue())
    assert (w, h) == (100, 200)
    out = Image.open(io.BytesIO(clean))
    assert out.size == (100, 200) and not out.getexif()


def test_pixel_bomb_is_rejected_before_decoding(monkeypatch):
    # 9000 x 9000 = 81 Mpx in a tiny file; must be refused from the header alone
    b = io.BytesIO()
    Image.new("1", (9000, 9000)).save(b, "PNG")
    assert len(b.getvalue()) < 200_000
    decoded = []
    real_load = Image.Image.load
    monkeypatch.setattr(Image.Image, "load", lambda self: decoded.append(self.size) or real_load(self))
    with pytest.raises(UploadRejected):
        sanitize_image(b.getvalue())
    assert decoded == []


def test_trailing_payload_and_text_chunks_are_dropped():
    from PIL import PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "<script>alert(1)</script>")
    data = _png(pnginfo=info) + b"PK\x03\x04appended-zip-polyglot"
    clean, *_ = sanitize_image(data)
    assert b"script" not in clean and b"PK\x03\x04" not in clean


@pytest.mark.parametrize("data", [
    b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    b"GIF89a" + b"\x00" * 10,
    _png()[:60],
])
def test_non_raster_or_broken_images_rejected(data):
    with pytest.raises(UploadRejected):
        sanitize_image(data)


# ------------------------------------------------------------------ passwords and tokens
def test_scrypt_meets_owasp_minimum_and_stores_its_parameters():
    h = security.hash_password("correct horse battery")
    scheme, n, r, p, salt, dk = h.split("$")
    assert scheme == "scrypt" and int(n) >= 2 ** 17 and int(r) >= 8 and int(p) >= 1
    assert security.verify_password("correct horse battery", h)
    assert not security.verify_password("wrong", h)


def test_legacy_hashes_still_verify():
    import base64, hashlib
    salt = os.urandom(16)
    dk = hashlib.scrypt(b"old-password", salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    legacy = f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"
    assert security.verify_password("old-password", legacy)
    assert security.needs_rehash(legacy) and not security.needs_rehash(security.hash_password("x" * 8))


def test_overlong_passwords_are_refused_without_hashing():
    assert not security.verify_password("x" * 10_000, security.hash_password("short-pass"))


@pytest.mark.parametrize("mutate", [
    lambda t: t + "x",
    lambda t: t.split(".")[0] + "." + "A" * 43,
    lambda t: "e30." + t.split(".")[1],                 # "{}" payload with a stolen signature
    lambda t: "",
    lambda t: "a.b.c",
])
def test_tampered_tokens_are_rejected(mutate):
    tok = security.create_token(7, "s" * 32)
    assert security.read_token(tok, "s" * 32) == 7
    assert security.read_token(mutate(tok), "s" * 32) is None


def test_token_expiry_and_wrong_secret():
    tok = security.create_token(7, "s" * 32, ttl_seconds=-1)
    assert security.read_token(tok, "s" * 32) is None
    assert security.read_token(security.create_token(7, "s" * 32), "t" * 32) is None


def test_production_requires_a_strong_secret(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("SMARTDOC_ENV", "production")
    monkeypatch.setenv("SMARTDOC_SECRET", "short")
    with pytest.raises(RuntimeError):
        Settings()


# ------------------------------------------------------------------ rate limiting
def test_rate_limiter_forgets_idle_keys():
    now = [0.0]
    rl = RateLimiter(2, 10, clock=lambda: now[0])
    for i in range(5000):
        rl.allow(f"k{i}")
    now[0] = 100
    rl.allow("fresh")
    assert len(rl.hits) <= 2


def test_rate_limiter_is_thread_safe():
    rl = RateLimiter(1000, 60)
    allowed_count = []

    def hammer():
        for _ in range(500):
            if rl.allow("same"):
                allowed_count.append(1)
    ts = [threading.Thread(target=hammer) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(allowed_count) == 1000


# ------------------------------------------------------------------ PDF isolation
def _soffice_bin_pids():
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq soffice.bin", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True).stdout
        return {line.split(",")[1].strip('"') for line in out.splitlines() if "soffice.bin" in line}
    out = subprocess.run(["pgrep", "-f", "soffice.bin"], capture_output=True, text=True).stdout
    return set(out.split())


@needs_soffice
def test_timeout_kills_the_whole_libreoffice_tree(templates, tmp_path):
    from app.document_engine.pdf import PdfExportError, docx_to_pdf
    before = _soffice_bin_pids()
    with pytest.raises(PdfExportError):
        docx_to_pdf(templates["university"], str(tmp_path / "o.pdf"), timeout=2)
    deadline = time.time() + 10
    while time.time() < deadline and _soffice_bin_pids() - before:
        time.sleep(0.5)
    assert _soffice_bin_pids() - before == set()


def test_pdf_subprocess_gets_a_stripped_environment(monkeypatch, tmp_path, templates):
    import app.document_engine.pdf as pdf
    seen = {}

    class FakeProc:
        returncode = 0
        def __init__(self, args, **kw):
            seen.update(kw); seen["args"] = args
        def communicate(self, timeout=None):
            return b"", b""
        def wait(self, timeout=None):
            return 0
        pid = 0
    monkeypatch.setattr(pdf, "soffice_path", lambda: sys.executable)
    monkeypatch.setattr(pdf.subprocess, "Popen", FakeProc)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak-me")
    with pytest.raises(pdf.PdfExportError):            # the fake produces no PDF
        pdf.docx_to_pdf(templates["university"], str(tmp_path / "o.pdf"))
    env = seen["env"]
    assert "AWS_SECRET_ACCESS_KEY" not in env and "SMARTDOC_SECRET" not in env
    assert any("UserInstallation=file:" in a for a in seen["args"])
    assert seen.get("stdin") == subprocess.DEVNULL
