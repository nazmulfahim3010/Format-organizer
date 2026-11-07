# Predefined design templates — integration plan

Status: proposal, not implemented. Visual reference: [ijpcr-design-spec.md](ijpcr-design-spec.md).

## Current state (read from the repository, 2026-11-06)

- Phases 0–9 plus "keep first-page layout" are done: **411 backend tests** pass (the request says 386; that was the
  count after Phase 8). Rendering tests run with LibreOffice 26.8.
- Workflow A already handles the IJPCR file when uploaded as a custom template: its first page is kept and
  `{{PLACEHOLDERS}}` are filled (Phase 9b). Workflow B below is separate and does not change that.
- Note on "the original 386 tests must not be modified": some tests were already updated in Phases 9/9b, each with a
  documented reason in PLAN.md (e.g. the `BODY_LAYOUT_REMOVED` health code was renamed). From here on, no existing test
  is changed for this feature.

## Reuse (no behaviour change)

| Existing part | Used for |
|---|---|
| `Generator` (`document_engine/generator.py`) | Body: sections with generated 1 / 1.1 / 1.1.1 numbering, `body_first`, lists, tables, figures, SEQ captions, Source/Note lines, complex scripts, schema order |
| Content boxes (`schemas/content.py`) | The article body *is* a list of the existing boxes: users get unlimited sections, nesting, paragraphs, lists, tables, figures exactly as in Workflow A |
| Template analyzer + FormattingProfile | Build the IJPCR design's profile once, from the bundled DOCX (roles → IJPCR styles) |
| Placeholder filling (`core/placeholders.py`) | Running header (DOI, volume, issue, pages, year) |
| Validator, PDF export, media uploads, auth, ownership (404), rate limits | Unchanged, called from the new routes |
| Frontend `BoxList`, `TableGrid`, figure upload, `PreviewPane`, `ValidationPanel` | Main content builder, preview and checks |

## New components (the three required by the request)

1. **Document schema** — `schemas/article.py`, independent of any design:
   `ArticleContent { schema_version, metadata { title, authors[ {name, affiliations[ids], corresponding, orcid} ],
   affiliations[ {id, department, institution, country} ], corresponding_email, doi, volume, issue, pages, year,
   received, accepted, published }, abstract, keywords[], body: [Box], back_matter { acknowledgements,
   competing_interests, ai_declaration, funding }, references[] }`. All back-matter items optional.
2. **Visual design profile** — `designs/ijpcr/` = `base.docx` (the IJPCR file with its body removed: keeps styles,
   page setup, header, footer, embedded fonts, logo image) + `design.json` (version, FormattingProfile, first-page
   layout parameters: colours, sizes, labels, banner/citation/licence texts, ISSN). No section names anywhere.
3. **Fixed template generator** — `designs/generator.py`: `DesignGenerator(Generator)` (a subclass, so the existing
   class is not edited) builds the first page, then lets the inherited code write `body`, then appends declarations
   and references with the design's styles. Running header filled from metadata.

## Database (additive only)

New tables created by `create_all` (existing tables are not altered, nothing is reset):
`design_documents` (id, owner_id, design_id, design_version, content JSON, created/updated) and
`design_generated_files`. Each document stores the design **version** it was made with; `designs/ijpcr/` keeps
older versions so old documents regenerate identically.

## API (new routes only)

`GET /api/designs`, `GET /api/designs/{id}` (description + preview sample), `POST/GET/PUT/DELETE
/api/design-documents[/{id}]`, `POST …/{id}/preview | generate | validate | pdf`, `GET …/files/{fid}/download`.
Same auth, ownership (404) and rate limits as the existing routes.

## Frontend (new pages, existing pages untouched)

Nav entry **Designs** → gallery (IJPCR card with a rendered preview) → article editor: article information
(authors and affiliations repeaters, corresponding author, dates, DOI/volume/issue/pages), abstract, keyword chips,
the existing section builder, optional declarations, reference list (add / reorder / delete), live preview,
checks, DOCX and PDF download.

## Decision needed — first-page construction (R1)

The reference places the abstract box, citation box and logo at **fixed positions**. Two options:

| | A. Reuse the reference shapes | B. Rebuild the first page as flowing tables (recommended) |
|---|---|---|
| Sample-sized content | identical to the reference | very close: same colours, fonts, sizes, widths; abstract box corners square instead of rounded |
| Long abstract, long title, 3+ authors, several affiliations | text overflows the fixed 12.8 cm box; citation box and logo stay pinned and can overlap text | everything grows and moves down; never overlaps |
| Editing in Word | floating shapes are fiddly | ordinary table cells |

## Risks and how they are handled

| # | Risk | Mitigation |
|---|---|---|
| R1 | Fixed-position first page vs variable content | Option B; tests for long abstract, long title, many authors/affiliations, rendered and inspected |
| R2 | Regressions in Workflow A | No edits to `Generator` behaviour (subclass + at most small hooks with defaults); full 411-test suite after every step |
| R3 | ~7 MB embedded fonts in every generated file | Keep (fonts look identical where not installed); documented; optional "do not embed" design setting later |
| R4 | Bundling the journal's DOCX and logo in the repository | Assumes you have the right to use the IJPCR branding; otherwise `base.docx` stays outside git |
| R5 | One affiliation and a placeholder ORCID link in the reference | Numbered affiliations list and optional per-author ORCID, marked as extensions |
| R6 | Pagination differences (LibreOffice vs Word) | Rendered checks for short/long papers and references over several pages; Word not available here |
| R7 | Old documents after a design update | Design versions are immutable; documents pin `design_version` |
| R8 | Future designs | New design = new folder (`base.docx` + `design.json`); the form and schema stay the same |

## Steps (each: tests first, full suite, render, small commit)

1. Schema `ArticleContent` + validation tests.
2. Design package: `base.docx` from the reference + `design.json`; tests that styles, header, footer, page setup survive.
3. `DesignGenerator`: first page (Option B), body via the inherited generator, back matter, header fill; the 16 test
   scenarios from the request; renders inspected against the reference.
4. Models + API + tests (ownership, versions, generation, PDF).
5. Frontend gallery + article editor; build, unit tests, browser run.
6. PLAN.md / README: scope, decisions, changed files, tests, render results, preserved / approximated / unsupported.
