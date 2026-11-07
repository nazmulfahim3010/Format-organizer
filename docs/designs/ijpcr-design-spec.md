# IJPCR research paper — visual design specification

Source: `IJPCR_template.docx` (SHA-256 `812adfd9…`, identical to the copy uploaded on 2026-11-04). Values below were
read from the OOXML (`document.xml`, `styles.xml`, headers/footers, relationships) and checked against LibreOffice
renders of the file. No screenshots were supplied with the request, so the renders are the visual reference.
Measurements: 1 cm = 567 twips = 360 000 EMU.

Legend: **E** = extracted from the DOCX · **D** = SmartDoc default where the reference sets nothing (configurable).

## 1. Page

| Property | Value | |
|---|---|---|
| Page size | 11 910 × 15 880 twips = **21.01 × 28.01 cm** (not A4, not Letter) | E |
| Margins | top 1.48 cm, bottom 0.49 cm, left 1.75 cm, right 1.75 cm; header 1.16 cm from edge, footer 0 | E |
| Text width | 17.51 cm, one column | E |
| Page numbering | starts at 1, `PAGE` field in the footer (right aligned) | E |
| Headers | default header on every page including page 1 (`titlePg` is not set, so the empty "first" header is unused) | E |
| Fonts | 12 embedded font files (Times New Roman, Trebuchet MS, Georgia, Tahoma …), `embedTrueTypeFonts` on, ~7 MB | E |

## 2. Running header and footer

- Header, Trebuchet MS italic, black: line 1 `DOI: {DOI}` 12 pt; line 2 `Vol. {VOLUME}, Issue {ISSUE}, pp. {PAGES}, {YEAR}` 10 pt
  with a right tab to *International Journal of Peace and Conflict Research (IJPCR)* 10 pt; thin rule below (1-pixel
  image + paragraph border). **E**
- Footer: page number only. **E**

## 3. First page (top to bottom)

| Element | Reference construction | Look | |
|---|---|---|---|
| Banner | inline drawing group 17.36 × 0.64 cm | solid **#003366**, **Tahoma 13 pt bold white**: "RESEARCH ARTICLE" left, "Open Access" right | E |
| Title | paragraph, centred, 8 pt before | Trebuchet MS **18 pt bold**, black | E |
| Authors | paragraph, centred, 8.9 pt before | Trebuchet MS bold 11 pt; superscript affiliation marker + `*` for the corresponding author; ORCID icon (0.31 cm, 24 px image) linked to orcid.org | E |
| Side panel (left, 3.8 cm wide) | ordinary paragraphs with a **13.38 cm right indent** | Trebuchet MS **8.5 pt**, 12.3 pt line: thin 3.8 cm rule, "\*Corresponding Author", Received / Accepted, Publication Date, © The Author(s) {YEAR} (CC BY 4.0), ISSN 3108-6136, corresponding e-mail, affiliation(s) "1 Department, Institution" | E |
| Abstract box (right) | **floating** group 12.91 × 12.82 cm at column + 4.33 cm, no wrap | rounded border **#003366**; "Abstract" Trebuchet MS bold 11 pt; abstract Times New Roman 11 pt justified, 12.35 pt line; "*Keywords:*" bold italic + italic keywords | E |
| Citation box | **floating** rectangle 17.12 × 1.59 cm, fixed at 21.33 cm from the page top | fill **#DAE5F1**, border **#1F3863**; Times New Roman 11 pt, colour #221F1F, justified: "**Cite this article:** Authors (Year). Title. *International Journal of Peace and Conflict Research (IJPCR)*, Vol(Issue), pages. DOI" | E |
| Logo | **floating** image 2.26 × 2.26 cm fixed at (3.45 cm, 24.41 cm) on the page | `image2.png` (journal logo, 196 px) | E |
| Licence | paragraph to the right of the logo, Trebuchet MS 7.5 pt ("**Open Access.**" 8 pt bold), justified; continues onto page 2 | "©The Author(s) {YEAR}. Open Access. This article is licensed under a Creative Commons Attribution 4.0 …" with a link to creativecommons.org | E |

### Flowing reconstruction (chosen: option B)

The same elements are written as ordinary content so the page grows with any title, author list or abstract:
banner = 1×2 table with #003366 shading; side panel + abstract = 2-column table (left 4.33 cm incl. gap, right
12.91 cm with a 1 pt #003366 border, minimum row height 12.82 cm so a sample-length abstract gives the reference's
proportions); citation = 1-cell table (#DAE5F1 fill, #1F3863 border); logo + licence = borderless 2-column table.
Differences from the reference: square instead of rounded abstract-box corners; positions follow the content
instead of fixed page coordinates; the article body starts on a new page (in the reference it starts on page 2
because page 1 is full) — **D**, a design setting.

The fixed positions are why the sample looks exact — and why the reference itself does not adapt to longer
content (see the plan, risk R1).

## 4. Body (styles defined in the template)

| Role | Style id | Font / size | Paragraph | |
|---|---|---|---|---|
| Main heading | `IJPCRHeading1` | Trebuchet MS 12 pt bold **ALL CAPS** | left, 18 pt before, 0 after, keep with next; numbered "1." | E (numbers typed manually in the reference; SmartDoc generates them) |
| Sub-section | `IJPCRHeading2` | Trebuchet MS 12 pt bold, title case | left, 18 pt before; "1.1" | E |
| Third level | `IJPCRHeading3` | Trebuchet MS 12 pt bold italic | left, 12 pt before; "1.1.1" | E (the template notes it is "an assumption") |
| Levels 4+ | — | reuse level 3 look | | D |
| First paragraph after a heading | `IJPCRBodyFirst` | Times New Roman 12 pt | justified, 0 before, 6 pt after, no indent | E |
| Following paragraphs | `IJPCRBody` | Times New Roman 12 pt | justified, 6 pt before/after, **0.51 cm first-line indent** | E |
| Bullet list | `IJPCRListBullet` | Times New Roman 12 pt | justified, 1.27 cm left, 0.63 cm hanging, 3 pt after | E |
| Numbered list | — | same as bullet list, decimal numbering | | D |
| Block quote | `IJPCRBlockQuote` | Times New Roman 11 pt | justified, indented 1.27 cm both sides | E |
| Table caption | `IJPCRTableCaption` | Times New Roman 11 pt bold | centred, **above** the table, 12 pt before, keep with next; "Table 1: …" | E |
| Table text | `IJPCRTableText` | Times New Roman 10 pt | left, 1 pt before/after | E |
| Table borders/header | — | single black borders, bold header row, no shading | | D (no table in the reference) |
| Figure caption | `IJPCRFigureCaption` | Times New Roman 11 pt bold | centred, **below** the figure; "Figure 1: …" | E |
| Figure | — | centred, scaled to the text width | | D |
| Declarations heading | `IJPCRDeclHeading` | Trebuchet MS 12 pt bold | justified, 12 pt before; unnumbered: Acknowledgements, Declaration of Competing Interest, Declaration of Generative AI …, Funding | E |
| Declarations text | `IJPCRDeclText` | Times New Roman 12 pt | justified, no spacing | E |
| References heading | `IJPCRRefHeading` | Trebuchet MS 12 pt bold ALL CAPS | left, 18 pt before, 6 pt after; unnumbered | E |
| Reference entry | `IJPCRReference` | Times New Roman 12 pt | left, 4.8 pt before/after, **1.27 cm hanging indent** | E |
| Source / Note lines | — | Times New Roman 10 pt under tables/figures | | D |

Order in the reference: numbered sections → declarations → references. The section *names* in the sample
("Main Section Heading", "Conclusion") are placeholders and are not part of the design.

## 5. What can be preserved, approximated or not supported

| Item | Status |
|---|---|
| Page size, margins, header, footer, page numbers, embedded fonts, all body styles | **Preserved** (taken from the template file itself) |
| Banner colours and text, title and author typography, side-panel typography, citation-box colours, logo, licence text | **Preserved** |
| Abstract box with rounded corners at a fixed size | **Approximated** if it must grow with the abstract (see plan R1) |
| Exact page-1 positions of the citation box and logo | **Approximated** for content longer than the sample |
| Multiple affiliations (reference shows one) and per-author ORCID (reference links a placeholder 0000-0000-0000-0000) | Extended pattern, not in the reference |
| Equations, citations/cross-references, table of contents | **Not supported** (existing SmartDoc limitation) |
