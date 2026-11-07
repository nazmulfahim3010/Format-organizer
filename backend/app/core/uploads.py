"""Safe handling of untrusted uploads.

A DOCX is an untrusted ZIP of XML files. We check it BEFORE any parser sees it:
extension, signature, size, ZIP bombs (measured by actually inflating, not by trusting the
headers), duplicate or unsafe entry names, encrypted entries, macros, ActiveX and OLE objects,
XML DTD/entities in any encoding (XXE / billion laughs), external relationships that would make
Word or LibreOffice fetch something (remote templates, linked images, frames), and fields that
run or include things (DDE, INCLUDEPICTURE, INCLUDETEXT, LINK). Images are decoded and
re-encoded so metadata and any embedded payload are dropped.
"""
from __future__ import annotations

import hashlib
import io
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass
from typing import List, Tuple

from lxml import etree
from PIL import Image, ImageOps

MAX_DOCX_BYTES = 20 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
MAX_ENTRIES = 3000
MAX_RATIO = 200                    # per-entry uncompressed / compressed
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_SIDE = 4000
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "GIF", "BMP", "TIFF", "WEBP"}

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS   # Pillow raises DecompressionBombError beyond 2x this

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
DANGEROUS_PARTS = re.compile(r"(vbaProject\.bin|vbaData\.xml|/activeX/|^word/activeX|macrosheets/|\.vbs$)", re.I)
# embedded objects other than Office Open XML packages (charts keep their .xlsx) are refused
EMBEDDING = re.compile(r"(^|/)embeddings/", re.I)
SAFE_EMBEDDING = re.compile(r"\.(xlsx|docx|pptx)$", re.I)
DTD = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.I)
# relationships that may point outside the package (everything else must stay inside)
EXTERNAL_OK = {"hyperlink"}
DANGEROUS_FIELD = re.compile(r"^\s*(DDE|DDEAUTO|INCLUDETEXT|INCLUDEPICTURE|INCLUDE|LINK|IMPORT)\b", re.I)
MEDIA = re.compile(r"\.(png|jpe?g|gif|bmp|tiff?|emf|wmf|webp|svg|ico|wdp)$", re.I)
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CHUNK = 1 << 16

_SAFE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


def safe_xml(blob: bytes):
    """Parse XML that came from a user. No DTD loading, no entity expansion, no network."""
    return etree.fromstring(blob, _SAFE_PARSER)


class UploadRejected(ValueError):
    """Raised with a message that is safe to show to the user."""


@dataclass
class CheckedDocx:
    sha256: str
    size: int


def _xml_text(blob: bytes) -> str:
    """Decode an XML part the way an XML parser would (UTF-8, UTF-16 with or without a BOM)."""
    if blob[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(blob) > 1 and (blob[0] == 0 or blob[1] == 0)):
        for enc in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                return blob.decode(enc)
            except UnicodeDecodeError:
                continue
    return blob.decode("utf-8", errors="replace")


def _looks_like_xml(name: str, blob: bytes) -> bool:
    if name.endswith((".xml", ".rels")):
        return True
    if MEDIA.search(name):
        return False
    head = _xml_text(blob[:200]).lstrip("﻿ \r\n\t")
    return head.startswith("<")


def _inflate_sizes(data: bytes, infos: List[zipfile.ZipInfo]) -> None:
    """Inflate every entry from its raw stream with a hard budget: headers can lie about sizes."""
    total = 0
    for info in infos:
        off = info.header_offset
        if data[off:off + 4] != b"PK\x03\x04":
            raise UploadRejected("This is not a valid .docx file (corrupt archive).")
        name_len, extra_len = struct.unpack("<HH", data[off + 26:off + 30])
        start = off + 30 + name_len + extra_len
        raw = memoryview(data)[start:start + info.compress_size]
        if info.compress_type == zipfile.ZIP_STORED:
            size = len(raw)
        elif info.compress_type == zipfile.ZIP_DEFLATED:
            # never hold more than CHUNK of output; stop as soon as the ratio or total budget is exceeded
            budget = min(MAX_UNCOMPRESSED_BYTES - total, max(len(raw), 1) * MAX_RATIO + 1_000_000)
            d = zlib.decompressobj(-15)
            size = 0
            try:
                for pos in range(0, len(raw), CHUNK):
                    buf = raw[pos:pos + CHUNK]
                    while buf:
                        size += len(d.decompress(buf, CHUNK))
                        if size > budget:
                            raise UploadRejected("The document looks like a compression bomb.")
                        buf = d.unconsumed_tail
                size += len(d.flush())
            except zlib.error:
                raise UploadRejected("This is not a valid .docx file (corrupt archive).")
        else:
            raise UploadRejected("The document uses an unsupported compression method.")
        if size != info.file_size:
            raise UploadRejected("The archive's size information is inconsistent (possible compression bomb).")
        total += size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise UploadRejected("The document expands to an unreasonable size (compression bomb).")


def _check_relationships(blob: bytes) -> None:
    root = safe_xml(blob)
    for rel in root.iter():                       # every element, whatever the root is
        if not isinstance(rel.tag, str) or etree.QName(rel).localname != "Relationship":
            continue
        if (rel.get("TargetMode") or "").lower() == "external":
            kind = (rel.get("Type") or "").rsplit("/", 1)[-1]
            if kind not in EXTERNAL_OK:
                what = "template" if kind == "attachedTemplate" else kind
                raise UploadRejected(f"The document links to a remote {what}, which is not allowed.")


def _check_fields(blob: bytes) -> None:
    """DDE / INCLUDE* / LINK fields, including instructions split over several runs."""
    root = safe_xml(blob)
    stack: List[List[str]] = []
    for el in root.iter(f"{{{W_NS}}}fldChar", f"{{{W_NS}}}instrText", f"{{{W_NS}}}fldSimple"):
        tag = etree.QName(el).localname
        if tag == "fldSimple":
            instrs = [el.get(f"{{{W_NS}}}instr") or ""]
        elif tag == "instrText":
            if stack:
                stack[-1].append(el.text or "")
            continue
        else:
            kind = el.get(f"{{{W_NS}}}fldCharType")
            if kind == "begin":
                stack.append([])
                continue
            if kind not in ("separate", "end") or not stack:
                continue
            instrs = ["".join(stack[-1])]
            if kind == "end":
                stack.pop()
            else:
                stack[-1] = []
        for instr in instrs:
            if DANGEROUS_FIELD.match(instr):
                raise UploadRejected("The document contains a field that runs or includes outside content "
                                     "(DDE, INCLUDEPICTURE, INCLUDETEXT or LINK), which is not allowed.")


def check_docx(data: bytes, filename: str = "") -> CheckedDocx:
    if filename and not filename.lower().endswith(".docx"):
        raise UploadRejected("Only .docx files are accepted (not .doc, .docm or .dotx).")
    if len(data) > MAX_DOCX_BYTES:
        raise UploadRejected(f"File is larger than {MAX_DOCX_BYTES // (1024 * 1024)} MB.")
    if data[:4] == OLE_MAGIC[:4]:
        raise UploadRejected("This file is password-protected or an old Word (.doc) file. "
                             "Remove the password and save it as .docx.")
    if data[:4] != b"PK\x03\x04":
        raise UploadRejected("This is not a valid .docx file (bad file signature).")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError, struct.error):
        raise UploadRejected("This is not a valid .docx file (corrupt archive).")
    if len(infos) > MAX_ENTRIES:
        raise UploadRejected("The document contains too many parts.")
    names = set()
    for i in infos:
        if i.flag_bits & 0x1:
            raise UploadRejected("Password-protected documents are not supported.")
        name = i.filename
        if (name.startswith("/") or ".." in re.split(r"[/\\]", name) or "\\" in name or ":" in name
                or any(ord(c) < 32 for c in name)):
            raise UploadRejected("The document contains unsafe file paths.")
        if name in names:
            raise UploadRejected("The document contains the same part twice, which is not allowed.")
        names.add(name)
        if DANGEROUS_PARTS.search(name):
            raise UploadRejected("Macro-enabled or ActiveX content is not allowed. Save the template as a plain .docx.")
        if EMBEDDING.search(name) and not SAFE_EMBEDDING.search(name):
            raise UploadRejected("The document contains an embedded object (OLE), which is not allowed.")
    if "[Content_Types].xml" not in names or "word/document.xml" not in names:
        raise UploadRejected("This does not look like a Word document.")
    _inflate_sizes(data, infos)                    # sizes are now known to be honest and bounded
    try:
        ct = zf.read("[Content_Types].xml")
        if b"macroEnabled" in ct:
            raise UploadRejected("Macro-enabled documents are not allowed.")
        for info in infos:
            blob = zf.read(info)
            if not _looks_like_xml(info.filename, blob):
                continue
            if DTD.search(_xml_text(blob)):
                raise UploadRejected("The document contains an XML DOCTYPE/entity declaration, which is not allowed.")
            if info.filename.endswith(".rels"):
                _check_relationships(blob)
            elif info.filename.startswith("word/") and info.filename.endswith(".xml"):
                _check_fields(blob)
    except UploadRejected:
        raise
    except (zipfile.BadZipFile, etree.XMLSyntaxError, RuntimeError, zlib.error):
        raise UploadRejected("This is not a valid .docx file (corrupt archive).")
    return CheckedDocx(hashlib.sha256(data).hexdigest(), len(data))


def sanitize_image(data: bytes) -> Tuple[bytes, str, int, int]:
    """Decode and re-encode an image. Returns (bytes, extension, width, height)."""
    if len(data) > MAX_IMAGE_BYTES:
        raise UploadRejected(f"Image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
    try:
        probe = Image.open(io.BytesIO(data))
        fmt = (probe.format or "").upper()
        if fmt not in ALLOWED_IMAGE_FORMATS:
            raise UploadRejected("Unsupported image type. Use PNG, JPEG, GIF, BMP, TIFF or WEBP.")
        if probe.width * probe.height > MAX_IMAGE_PIXELS:      # from the header, before decoding
            raise UploadRejected("The image has too many pixels.")
        probe.verify()
        im = Image.open(io.BytesIO(data))
        im.load()
    except UploadRejected:
        raise
    except Exception:
        raise UploadRejected("The image is corrupt or too large.")
    dpi = im.info.get("dpi")
    im = ImageOps.exif_transpose(im)              # phone photos: apply the rotation before EXIF is dropped
    if max(im.size) > MAX_IMAGE_SIDE:
        im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    if fmt == "JPEG":
        im.convert("RGB").save(out, "JPEG", quality=90, optimize=True,
                               dpi=dpi if dpi else (96, 96))
        ext = "jpg"
    else:
        if im.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            im = im.convert("RGBA")
        if im.mode == "P":
            im = im.convert("RGBA")
        im.save(out, "PNG", optimize=True, dpi=dpi if dpi else (96, 96))
        ext = "png"
    return out.getvalue(), ext, im.width, im.height
