"""Render the sample document for each fixture template: DOCX -> PDF (LibreOffice) -> PNG per page.

    python scripts/render.py [out_dir] [fixture ...]

Output: <out_dir>/<fixture>.docx, .pdf and <fixture>-p<N>.png. Look at the PNGs; that is the verification.
"""
from __future__ import annotations

import os
import sys

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.document_engine.generator import generate_docx  # noqa: E402
from app.document_engine.pdf import docx_to_pdf  # noqa: E402
from app.template_engine.analyzer import analyze_template, build_default_profile  # noqa: E402
from tests.make_templates import build_all  # noqa: E402
from tests.sample import make_image, sample_content  # noqa: E402

LANGS = {"bangla": "bn", "rtl": "ar"}


def render(out_dir: str, names: list[str], dpi: int = 80) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    templates = build_all(os.path.join(out_dir, "templates"))
    image = make_image(os.path.join(out_dir, "img.png"))
    pngs = []
    for name in names or sorted(templates):
        prof = build_default_profile(analyze_template(templates[name]), name)
        docx = os.path.join(out_dir, f"{name}.docx")
        generate_docx(templates[name], prof, sample_content(LANGS.get(name, "en")),
                      lambda aid: image if aid == "img1" else None, docx)
        pdf = docx_to_pdf(docx, os.path.join(out_dir, f"{name}.pdf"), timeout=150)
        with pymupdf.open(pdf) as d:
            for i, page in enumerate(d, 1):
                png = os.path.join(out_dir, f"{name}-p{i}.png")
                page.get_pixmap(dpi=dpi).save(png)
                pngs.append(png)
            print(f"{name}: {d.page_count} page(s)")
    return pngs


if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else "render_out", sys.argv[2:])
