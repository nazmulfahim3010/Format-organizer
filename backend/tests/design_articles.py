"""Article fixtures for the predefined-design tests (the scenarios from the feature request)."""
from PIL import Image, ImageDraw

LOREM = ("Water scarcity shapes local politics in ways that national statistics rarely capture. Village councils, "
         "informal mediators and religious leaders negotiate access to wells and canals, and these negotiations "
         "decide whether a dry season ends in cooperation or in conflict. ")


def make_figure(path, size=(1200, 700)):
    im = Image.new("RGB", size, (232, 238, 247))
    d = ImageDraw.Draw(im)
    d.rectangle([30, 30, size[0] - 30, size[1] - 30], outline=(0, 51, 102), width=8)
    d.line([30, size[1] - 30, size[0] - 30, 30], fill=(180, 40, 40), width=6)
    im.save(path)
    return path


def meta(authors=1, affiliations=1, title="Water Scarcity and Local Peacebuilding in Northern Bangladesh"):
    affs = [{"id": str(i + 1), "department": f"Department {i + 1}", "institution": f"University {i + 1}",
             "country": "Bangladesh"} for i in range(affiliations)]
    names = ["Rahima Akter", "Mohammad Karim Rahman", "Sadia Islam", "Tanvir Hasan", "Nusrat Jahan", "Arif Chowdhury"]
    auths = [{"name": names[i % len(names)], "affiliations": [str((i % affiliations) + 1)],
              "corresponding": i == 0, "orcid": "0000-0002-1825-0097" if i == 0 else None} for i in range(authors)]
    return {"title": title, "doi": "10.5281/ijpcr.2026.0142", "volume": "01", "issue": "04", "pages": "12-27",
            "year": "2026", "received": "12 June 2026", "accepted": "2 September 2026",
            "published": "30 October 2026", "corresponding_email": "rahima@example.org",
            "affiliations": affs, "authors": auths}


def section(title, *content):
    return {"type": "section", "title": title, "content": list(content)}


def para(text):
    return {"type": "paragraph", "text": text}


def table(caption, rows=4, cols=3):
    return {"type": "table", "caption": caption, "source": "Field survey, 2026",
            "data": [[f"Head {c + 1}" for c in range(cols)]] + [[f"{r}.{c}" for c in range(cols)] for r in range(1, rows)]}


def figure(caption):
    return {"type": "figure", "asset_id": "fig", "caption": caption, "source": "Authors"}


BACK = {"acknowledgements": "We thank the village councils.", "competing_interests": "None declared.",
        "ai_declaration": "No generative AI was used.", "funding": "This work received no external funding."}


def short_intro():
    return {"metadata": meta(), "abstract": "A short abstract.", "keywords": ["water", "peace"],
            "body": [section("Introduction", para("A short introduction."))]}


def multi_sections():
    return {"metadata": meta(), "abstract": LOREM, "keywords": ["water", "conflict", "mediation"],
            "body": [section("Introduction", para(LOREM), para(LOREM)),
                     section("Literature Review", para(LOREM)),
                     section("Research Methodology", section("Research Design", para(LOREM)),
                             section("Data Collection", para(LOREM), {"type": "list", "ordered": False,
                                     "items": [{"text": "Household survey"}, {"text": "Key-informant interviews"}]})),
                     section("Results and Discussion", section("Experimental Results", para(LOREM), table("Water access by district")),
                             section("Analysis", para(LOREM), figure("Study area"))),
                     section("Conclusion", para(LOREM))],
            "back_matter": BACK, "references": [f"Author{i}, A. ({2000 + i}) Title of article {i}. Journal, 1(1), pp. 1-10." for i in range(8)]}


def deep_nesting():
    leaf = section("Fifth level", para(LOREM))
    for t in ("Fourth level", "Third level", "Second level", "First level"):
        leaf = section(t, para(LOREM), leaf)
    return {"metadata": meta(), "abstract": "Nesting.", "keywords": ["depth"], "body": [leaf, section("Next", para(LOREM))]}


def different_order():
    return {"metadata": meta(), "abstract": "Order.", "keywords": ["order"],
            "body": [section("Conclusion First", para(LOREM)), section("Background", para(LOREM)),
                     section("Methods", para(LOREM))], "references": ["Ref A.", "Ref B."]}


def many_authors():
    return {"metadata": meta(authors=6, affiliations=3), "abstract": LOREM, "keywords": ["team"],
            "body": [section("Introduction", para(LOREM))]}


def long_abstract():
    return {"metadata": meta(authors=3, affiliations=2,
                             title="A Very Long Title About Water Scarcity, Local Institutions and the Everyday Politics "
                                   "of Peacebuilding in the Drought-Prone Districts of Northern Bangladesh"),
            "abstract": (LOREM * 7).strip(), "keywords": ["water", "peace", "institutions", "drought", "Bangladesh"],
            "body": [section("Introduction", para(LOREM))]}


def many_tables_figures():
    return {"metadata": meta(), "abstract": LOREM, "keywords": ["tables"],
            "body": [section("Results", *[x for i in range(4) for x in (para(LOREM), table(f"Result set {i + 1}", rows=6),
                                                                        figure(f"Chart {i + 1}"))])]}


def long_references():
    return {"metadata": meta(), "abstract": LOREM, "keywords": ["references"],
            "body": [section("Introduction", para(LOREM))], "back_matter": BACK,
            "references": [f"Author{i}, A.B. and Writer, C.D. ({1990 + i % 30}) 'A long title for reference number {i} "
                           f"about water governance', Journal of Studies, {i}({i % 4 + 1}), pp. {i}-{i + 20}. "
                           f"Available at: https://doi.org/10.1000/{i}" for i in range(90)]}


def short_document():
    return {"metadata": {"title": "Note"}, "body": [para("Only one paragraph.")]}


def long_document():
    body = [section(f"Chapter {n}", para(LOREM * 3), section(f"Part {n}.1", para(LOREM * 2), table(f"Data {n}")),
                    section(f"Part {n}.2", para(LOREM * 2))) for n in range(1, 13)]
    return {"metadata": meta(authors=2, affiliations=2), "abstract": LOREM * 2, "keywords": ["long"],
            "body": body, "back_matter": BACK, "references": [f"Ref {i}." for i in range(40)]}


SCENARIOS = {"short_intro": short_intro, "multi_sections": multi_sections, "deep_nesting": deep_nesting,
             "different_order": different_order, "many_authors": many_authors, "long_abstract": long_abstract,
             "many_tables_figures": many_tables_figures, "long_references": long_references,
             "short_document": short_document, "long_document": long_document}
