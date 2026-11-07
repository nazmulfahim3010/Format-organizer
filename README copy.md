# SmartDoc

Template-driven DOCX generation. Upload any Word template (any language, including right-to-left and
complex scripts such as Bangla and Arabic), paste content from Word, Google Docs, Markdown, plain text or
Excel, and get a DOCX that follows the template's own styles, headers, footers, numbering and page setup.
A live side preview shows the generated file. Users supply only data; the look is locked by the template's
approved rules. No paid AI is used at runtime.

## How it works

1. **Template.** The upload is checked as hostile input before anything parses it. The analyzer reads styles
   (resolving `basedOn`, document defaults and theme fonts), page setup, headers and footers, tables, figures,
   caption labels and language, and reports template health problems.
2. **Formatting profile.** A draft profile maps roles (heading levels, body, first paragraph after a heading,
   lists, captions, table text …) to the template's style ids, plus locked table/figure/caption rules, language
   settings and labels. Every rule records where it came from (`template`, `inferred`, `default`, `user`).
   You review and approve it. Approved versions never change; an edit starts a new draft. Each document keeps
   the exact profile version it was made with, and is offered newer approved versions.
3. **Content.** A JSON tree of boxes: section (title + nested content), paragraph, list (nested), table,
   figure, with `schema_version`. Inline markup: `**bold**`, `*italic*`, `^sup^`, `~sub~`, backslash escapes.
   Pasted content is normalised deterministically; source fonts, sizes and colours are discarded.
4. **Generate.** The template's body is cleared; its final section properties, headers, footers, numbering
   and styles are kept. Content is written with the template's styles, real Word numbering, SEQ caption fields
   and complex-script/RTL properties, in the element order Word requires.
   **Fill-in layout templates** (a journal first page with a banner, boxes, logo and `{{TITLE}}`-style
   placeholders): with the profile setting *Keep the template's first-page layout* (on by default when the
   template's body has placeholders), everything before the template's first heading is kept and its
   placeholders are filled. `{{TITLE}}`, `{{SUBTITLE}}`, `{{AUTHORS}}`, `{{ABSTRACT}}` and `{{KEYWORDS}}` come
   from the document; any other `{{NAME}}` (DOI, volume, dates …) from the document's *Template fields*. Header
   and footer placeholders are filled in both modes. Unfilled placeholders stay visible and are reported.
5. **Check.** The validator reports each check as passed / warning / failed / info / manual, kind auto or
   visual. There is no score.

### Predefined designs (no template needed)

Under **Designs** you pick a ready-made journal layout (currently IJPCR research paper) and fill in a form:
title, affiliations, authors (corresponding author, ORCID), dates and DOI, abstract, keywords, the article body
with any sections and subsections you like, declarations and references. The live preview updates as you type;
Check formatting, DOCX and PDF work as for template documents. The first page (banner, title, authors, side
panel, abstract box, citation box, licence) is rebuilt as flowing tables, so long content pushes the boxes
down instead of overlapping. Each article keeps the design version it was created with until you upgrade it.
Designs live in `backend/app/designs/<id>/<version>/`; details in `docs/designs/`.

## Install

Requirements: Python 3.10 or newer (the code needs 3.10; it was only tested on 3.14), Node.js (tested on 24),
and LibreOffice for PDF export (tested with 26.8).

```bash
cd backend
pip install -r requirements.txt
```

```bash
cd frontend
npm install
```

LibreOffice is found on `PATH`, in the standard Windows install folders, or via `SMARTDOC_SOFFICE`. Without it,
everything works except PDF export (the API says so clearly). Complex scripts need a matching font installed
where documents are opened (for example Kalpurush or Noto Sans Bengali for Bangla).

## Run

Production-style (the API also serves the built frontend):

```bash
cd frontend && npm run build
```

```bash
python backend/scripts/dev_server.py --port 8000
```

Open http://localhost:8000. `--data DIR` puts the database, uploads and generated files in a separate folder
(default `backend/storage/`).

Development with hot reload: run the API on port 8000 as above, then `npm run dev` in `frontend/` (Vite on
:5173 proxies `/api` to :8000).

Settings (environment variables): `SMARTDOC_SECRET` (required in production, at least 32 characters),
`SMARTDOC_ENV=production`, `SMARTDOC_DATA_DIR`, `SMARTDOC_DATABASE_URL`, `SMARTDOC_CORS_ORIGINS`,
`SMARTDOC_ALLOW_REGISTRATION`, `SMARTDOC_HEAVY_CALLS_PER_MINUTE` (60), `SMARTDOC_LOGIN_ATTEMPTS_PER_MINUTE` (10),
`SMARTDOC_MAX_PASTE_IMAGES` (50), `SMARTDOC_KEEP_GENERATED_FILES` (20), `SMARTDOC_SOFFICE`.

## Test

```bash
cd backend && python -m pytest -q
```

```bash
cd frontend && npm run build && npm test
```

Backend: 458 tests (about 4–7 minutes; the rendering tests need LibreOffice and are skipped without it).
Fixture templates are generated by `backend/tests/make_templates.py` (default, university, messy, bangla,
twocol, rtl, journal); attack files by `backend/tests/make_attacks.py`; realistic paste samples live in
`backend/tests/paste_samples/`. Tests never touch `backend/storage/` (a throw-away data folder is set in
`conftest.py`).

Render any fixture to page images to look at the result:

```bash
python backend/scripts/render.py render_out
```

## What is verified, and how

Verified on Windows 11 with Python 3.14, Node 24 and LibreOffice 26.8:

- **Engine and analyzer:** every fixture and the user's real IJPCR journal template generated, validated,
  converted to PDF with LibreOffice and rasterized, and the pages inspected. This covers headers/footers,
  heading numbering (template and generated), nested lists, captions, tables in one and two columns, image
  scaling, Bangla shaping, Arabic RTL paragraphs and mirrored tables.
- **Paste:** Word, Google Docs, Excel (HTML and tab-separated) and ChatGPT samples plus Bangla and mixed-script
  plain text, rendered end to end into templates and inspected.
- **Security:** 28 hostile files (zip bombs including lying headers, macros, ActiveX, OLE, XXE incl. UTF-16,
  path traversal, remote templates/images/frames, DDE/INCLUDE fields, encrypted entries, duplicates) are refused
  before parsing; image re-encoding, scrypt, tokens, rate limits, and the LibreOffice timeout (no process
  survives on Windows).
- **API:** versioning, carry-over to new template versions, immutability enforced in the database layer,
  ownership (19 routes answer 404 to other users).
- **Frontend:** typecheck and production build; editing helpers unit-tested; the whole flow driven in a
  browser against the production build: register, upload, review and approve rules, sample preview, create a
  document, paste Word content, autosave and live preview, formatting checks, DOCX download, PDF export, Excel
  paste into a table, inline markup buttons, figure upload, new template version and document upgrade.
- **Predefined designs:** 16 scenarios (different section names, orders and depths, many authors, long
  abstract, many tables/figures, long references, short and long documents) generated, rendered and inspected;
  the form flow driven in a browser through to formatting checks and DOCX download.

## Not verified

- **Microsoft Word itself.** No Word on the development machine; all rendering was checked in LibreOffice and
  docx-preview. In particular: how Word treats `left/right` alignment in RTL paragraphs, `doNotExpandShiftReturn`,
  and native-digit caption numbers after a field update.
- Stopping LibreOffice on timeout on Linux/macOS (the process-group code path).
- The Vite dev server in this environment, mobile layouts, Firefox and Safari, keyboard-only use and screen
  readers.
- The operating system file dialog and clipboard: in the browser run, files were placed in the upload fields
  and pastes dispatched by script.

## Known limitations

- **No table of contents, equations or citations yet.**
- **Layout mode keeps everything before the template's first heading.** A template whose layout continues
  after that heading, or that has no heading in its body, cannot keep it (the body is then replaced and the
  user is told). Placeholder values are plain text and take the formatting of the placeholder in the template;
  placeholders must be written as `{{NAME}}` (letters, digits, `_`). Without layout mode the whole body is
  replaced.
- At narrow window widths the editor scrolls sideways because the preview shows a full-width page.
- Only the template's last section (page setup, headers, footers) is kept.
- Merged table cells in pasted tables are split into separate cells.
- A bullet nested inside a numbered list becomes numbered (list items have no per-item kind); lettered lists
  become ordered lists in the template's number style.
- Caption numbers can be written in the language's own digits, but LibreOffice (and therefore PDF export) shows
  1, 2, 3; heading and list numbers always use Latin digits.
- When a template has fewer heading styles than the content needs, deeper sections reuse the deepest style.
- Word footnotes in pasted content arrive as plain text such as "[1]"; images pasted as file links need a
  manual upload.
- docx-preview (the browser preview) is close to Word but not identical; download the DOCX for the final check.
- Predefined IJPCR design: the abstract box has square corners (the original is a rounded shape), the body
  starts on page 2, files are about 7 MB because the design embeds its fonts, and there is a small gap after
  the ORCID icon. Only one design exists so far.
- No database migrations (tables are created when missing); rate limits are per server process; changing a
  password does not revoke existing tokens.
- AI assistance is not implemented; it is planned as a later, optional phase.
