"""Build app/designs/ijpcr/<version>/design.json from base.docx (the IJPCR reference template).

    python backend/scripts/build_design_ijpcr.py v1

The formatting profile starts from SmartDoc's own analysis of base.docx and is then fixed to the values in
docs/designs/ijpcr-design-spec.md. Approved design versions are never edited: a change means a new version folder.
"""
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.template_engine.analyzer import analyze_template, build_default_profile  # noqa: E402

LICENCE = ("This article is licensed under a Creative Commons Attribution 4.0 International License, which permits "
           "use, sharing, adaptation, distribution, and reproduction in any medium or format, as long as you give "
           "appropriate credit to the original author(s) and the source, provide a link to the Creative Commons "
           "license, and indicate if changes were made. The images or other third-party material in this article are "
           "included in the article’s Creative Commons license, unless indicated otherwise in a credit line to the "
           "material. If material is not included in the article’s Creative Commons license and your intended use "
           "is not permitted by statutory regulation or exceeds the permitted use, you will need to obtain permission "
           "directly from the copyright holder. Visit ")


def build(version: str) -> dict:
    folder = os.path.join(BACKEND, "app", "designs", "ijpcr", version)
    base = os.path.join(folder, "base.docx")
    prof = build_default_profile(analyze_template(base), "IJPCR research paper")
    user = []

    def setv(path, value):
        obj = prof
        *parents, last = path.split(".")
        for p in parents:
            obj = getattr(obj, p)
        setattr(obj, last, value)
        user.append(path)

    roles = {"heading_1": "IJPCRHeading1", "heading_2": "IJPCRHeading2", "heading_3": "IJPCRHeading3",
             "heading_4": "IJPCRHeading4", "heading_5": "IJPCRHeading5", "heading_6": "IJPCRHeading6",
             "body": "IJPCRBody", "body_first": "IJPCRBodyFirst", "list_bullet": "IJPCRListBullet",
             "list_number": "IJPCRListBullet", "quote": "IJPCRBlockQuote", "caption": "IJPCRTableCaption",
             "figure_caption": "IJPCRFigureCaption", "table_text": "IJPCRTableText"}
    prof.roles = roles
    prof.origins = {k: v for k, v in prof.origins.items() if not k.startswith("roles.")}
    prof.origins.update({f"roles.{r}": "user" for r in roles})
    for path, value in (("heading_numbering", "auto"), ("heading_number_suffix", "space"),
                        ("keep_template_layout", False), ("list_mode", "generated"),
                        ("table.caption_position", "above"), ("table.alignment", "center"),
                        ("table.width_percent", 100), ("table.borders", "all"), ("table.template_style_id", None),
                        ("table.header_bold", True), ("table.header_shading", None), ("table.cell_alignment", "auto"),
                        ("figure.caption_position", "below"), ("figure.alignment", "center"),
                        ("figure.max_width_percent", 100), ("labels.caption_separator", ": "),
                        ("language.code", "en"), ("language.rtl", False), ("language.native_digits", False)):
        setv(path, value)
    prof.origins.update({p: "user" for p in user})
    return {
        "id": "ijpcr",
        "version": version,
        "name": "IJPCR research paper",
        "description": "International Journal of Peace and Conflict Research article layout: navy banner, "
                       "side panel with dates and licence, boxed abstract, citation box, numbered sections, "
                       "declarations and author-date references.",
        "base": "base.docx",
        "profile": prof.model_dump(),
        # styles the design adds to base.docx (sections deeper than the template's three levels)
        "extra_styles": [{"id": f"IJPCRHeading{n}", "name": f"IJPCR Heading {n}", "based_on": "IJPCRHeading3",
                          "outline_level": n - 1} for n in (4, 5, 6)],
        "page_one": {
            "banner": {"left": "RESEARCH ARTICLE", "right": "Open Access", "fill": "003366", "color": "FFFFFF",
                       "font": "Tahoma", "size_pt": 13, "bold": True},
            "title": {"font": "Trebuchet MS", "size_pt": 18, "bold": True, "space_before_pt": 8},
            "authors": {"font": "Trebuchet MS", "size_pt": 11, "bold": True, "space_before_pt": 8.9,
                        "orcid_icon": "orcid.png", "orcid_icon_cm": 0.31},
            "panel": {"width_cm": 4.33, "font": "Trebuchet MS", "size_pt": 8.5, "line_pt": 12.3,
                      "rule_width_cm": 3.8, "issn": "3108-6136", "licence_short": "(CC BY 4.0)",
                      "labels": {"corresponding": "*Corresponding Author", "received": "Received:",
                                 "accepted": "Accepted:", "published": "Publication Date:",
                                 "copyright": "© The Author(s)", "issn": "ISSN:",
                                 "email": "Corresponding Author Email:"}},
            "abstract_box": {"width_cm": 12.91, "min_height_cm": 12.82, "border": "003366", "border_pt": 1.0,
                             "heading": "Abstract", "heading_font": "Trebuchet MS", "heading_size_pt": 11,
                             "text_font": "Times New Roman", "text_size_pt": 11, "line_pt": 12.35,
                             "keywords_label": "Keywords:"},
            "citation_box": {"fill": "DAE5F1", "border": "1F3863", "border_pt": 1.0, "font": "Times New Roman",
                             "size_pt": 11, "color": "221F1F", "label": "Cite this article:",
                             "journal": "International Journal of Peace and Conflict Research (IJPCR)",
                             "space_before_pt": 12},
            "licence": {"logo": "logo.png", "logo_cm": 2.26, "logo_cell_cm": 4.33, "font": "Trebuchet MS",
                        "size_pt": 7.5, "lead_size_pt": 8, "copyright": "©The Author(s)",
                        "lead": "Open Access.", "text": LICENCE,
                        "url": "https://creativecommons.org/licenses/by/4.0/", "after_url": " to view a copy of this license.",
                        "space_before_pt": 12},
            "body_starts_on_new_page": True,
        },
        "back_matter": {
            "heading_style": "IJPCRDeclHeading", "text_style": "IJPCRDeclText",
            "items": [["acknowledgements", "Acknowledgements"],
                      ["competing_interests", "Declaration of Competing Interest"],
                      ["ai_declaration", "Declaration of Generative AI and AI-assisted technologies in the writing process"],
                      ["funding", "Funding"]],
            "references_heading": "References", "references_heading_style": "IJPCRRefHeading",
            "reference_style": "IJPCRReference",
        },
        # running-header placeholders and where their values come from
        "header_fields": {"DOI": "doi", "VOLUME": "volume", "ISSUE": "issue", "PAGES": "pages", "YEAR": "year"},
    }


if __name__ == "__main__":
    version = sys.argv[1] if len(sys.argv) > 1 else "v1"
    data = build(version)
    out = os.path.join(BACKEND, "app", "designs", "ijpcr", version, "design.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("wrote", out)
