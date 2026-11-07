# SmartDoc — plan

## Starting point (Phase 0 audit, 2026-11-04)
The repo already contains an MVP (~7.4k lines) covering every module in the brief. Rather than rewrite it, each phase hardens one area against the design rules in `CLAUDE.md`, test-first, with rendered verification.

Baseline on this machine (Windows 11, Python 3.14.2, Node 24.15, git 2.47):
- `pytest`: **84 passed, 7 skipped**. All 7 skips are "LibreOffice not installed" (render/PDF tests).
- `test_api.py` now runs (FastAPI 0.139, SQLAlchemy 2.0.45, httpx 0.27 present) — previously never executed.
- Frontend: `tsc --noEmit` clean; `vite build` succeeds (364 kB JS).
- Rule-by-rule grep: code exists for schema_version, origins, SEQ, bidi/bidiVisual, cs/eastAsia/szCs, scrypt, HMAC, DOCTYPE, attachedTemplate, vbaProject/ActiveX, encrypted entries, mso-list, PDF timeout/profile. No percentage score in the validator.

**Blocker:** LibreOffice (`soffice`) is not installed, so no DOCX→PDF→PNG rendering can be verified. A rasterizer (PyMuPDF) is also missing. Until both are installed, nothing layout-related is claimed as verified.

Cleanups noted: `datetime.utcnow()` deprecations (models/db.py, routes/templates.py); starlette/httpx TestClient deprecation warning.

### Toolchain update (2026-11-04)
Installed LibreOffice 26.8.2 (winget, `C:\Program Files\LibreOffice`, not on PATH) and PyMuPDF 2.1.
- `soffice_path()` now checks `SMARTDOC_SOFFICE`, PATH, then the standard Windows install dirs.
- `docx_to_pdf` fixed for Windows: profile URL via `Path.as_uri()` (was `file://C:\...`), and the stripped env keeps `SYSTEMROOT`/`TEMP`/`TMP`.
- Render tests use the shared `needs_soffice` marker and `docx_to_pdf`; `pdftotext` replaced by PyMuPDF.
- `pytest`: **91 passed, 0 skipped**.
- `scripts/render.py` renders the sample for every fixture to PDF + PNGs.

### Render findings (inspected PNGs, not yet fixed)
Verified visually: template headers/footers + page numbers kept; heading numbering (university); two-column layout; SEQ captions numbered 1..3 with Source lines; figure placement; Bangla glyph shaping (conjuncts render; which system font LibreOffice substituted was not checked); RTL paragraphs right-aligned and table columns mirrored (bidiVisual).
Defects (each scheduled in the phase that owns it):
1. ~~Nested items under a **bullet** list render as `1. 2.` in university/bangla/twocol/rtl (messy is correct with `–`).~~ **Fixed:** the templates' List Bullet/List Number numbering is singleLevel, so `ilvl≥1` was undefined. The generator now clones such numbering and fills the missing levels (`_complete_abstract`). Re-rendered all six: nested bullets show `–`, nested numbers `a.`.
2. twocol: `First paragraph.
Second line.` is justified with a huge gap — soft line break in a justified paragraph. **Fixed (Phase 3):** `w:doNotExpandShiftReturn` in settings; render confirms (LibreOffice; Word not checked).
3. ~~university: Title and Subtitle get a first-line indent inherited from the body style.~~ **Not a bug (Phase 2):** Title is basedOn Normal, which has a 1 cm first-line indent, so Word indents it too. The analyzer now reports `INHERITED_FIRST_LINE_INDENT` so the user sees why.
4. Bangla doc: ~~`Abstract`, `Keywords`, `Table` labels stay English~~ **labels fixed in Phase 2** (rendered: সারসংক্ষেপ, মূলশব্দ, সারণি; Arabic: الملخص, جدول, المصدر). Digits: **Phase 3** writes SEQ cached numbers in native digits (`language.native_digits`). LibreOffice recomputes SEQ fields and shows Latin digits anyway (tested `\* ARABIC` and `\* HINDIARABIC`), so PDF export shows 1, 2, 3. Heading/list numbers stay Latin (Word has no Bengali numFmt).
5. rtl sample text is Bangla, not Arabic (`sample_content` returns Bangla for any non-en language); LTR fragments in RTL paragraphs show `.Deep text`. **Fixed (Phase 3):** sample has real Arabic; paragraph direction follows the first strong character, so `Deep text.` renders LTR with the period at the end.
6. A template whose RTL Normal style has `w:bidi` + `jc=right` renders headings/body/lists **left**-aligned (tables still mirror). Seen while building the rtl fixture; the fixture now omits `jc`. **Phase 3 finding:** in bidi paragraphs LibreOffice treats `left/right` as start/end, so `jc=right` means the left edge. My reading of the spec is that Word does the same (transitional left/right = start/end), which would make this the template's own setting, not a generator bug. **Not verified in Word.**

## Phases (the user's list)
0. Skeleton and fixtures: layout, requirements, pytest config, six fixture builders, a test that opens each. **Done.**
1. Schemas and inline markup: content/profile models, inline parser + serializer with escapes, round-trip and edge-case tests. **Done.**
2. Template analyzer: StyleResolver (basedOn, docDefaults, theme fonts), role detection, page/header/footer/table/figure/language detection, health report, build_default_profile with origins. **Done.**
3. Generator: clear body keep sectPr, fallback styles, heading numbering, lists, SEQ captions, table rules, CS/RTL, schema order, multi-column width, image scaling — render after each feature. **Done.**
4. Paste normalizer: HTML (Word/Google Docs), Markdown, plain text, typed numbering, captions, Source/Note, TSV tables, title detection, heading-level fixes; realistic samples incl. Bangla. **Done.**
5. Validator: statuses and kinds, manual visual checks, no score. **Done.**
6. Security: upload checks, image re-encoding, scrypt/tokens, rate limiter, isolated PDF; attack fixtures. **Done.**
7. API and database: models, versioning, routes; RUN test_api.py. **Done.**
8. Frontend: pages/components, typecheck, real `npm run build`, drive the app in a browser end to end. **Done.**
9. Hardening with the user's real templates; README and limitations. **Done.**

Existing MVP code covers parts of every phase; each phase audits it against the brief, fills gaps test-first, and renders.

## Phase 0 — done
- [x] Repo layout (backend/app modules, tests, frontend), `requirements.txt`, `backend/pytest.ini`
- [x] `tests/make_templates.py` builds default, university, messy, bangla, twocol, rtl (`python -m tests.make_templates` refreshes `tests/fixtures/`)
  - messy now has odd style names (`bdy txt FINAL`, `Normal1`, `Para (copy) 2`, `zz_old_STYLE`) and still no heading styles/numbering
  - rtl now has real RTL defaults on Normal (`w:bidi`, `w:rtl`, `lang bidi=ar-SA`)
- [x] `tests/test_fixtures.py`: every built and committed fixture opens; each has the features it exists for
- [x] Toolchain: LibreOffice 26.8.2, PyMuPDF 2.1; `scripts/render.py` renders all fixtures
- [x] `pytest`: 103 passed, 0 skipped

## Phase 1 — done
Inline markup (`app/core/inline.py`), rewritten:
- Fixed: serializer output could re-parse differently (`*a****b***` lost the bold); now one marker per attribute change, fuzz-tested over 3000 random run lists.
- Fixed: stray symbols in prose were formatted (`2 * 3 * 4`, `~5 to ~10 km`). Markers now format only when paired and flanked by non-space; `^`/`~` content may not contain whitespace (`\ ` escapes a space).
- Serializer moves styling off leading/trailing whitespace and merges equal neighbours.
Content schema (`app/schemas/content.py`):
- `extra="forbid"` on every box: fonts/colours/sizes or unknown box types are rejected, not silently stored (rule 4).
- `schema_version` must be 1..current; BCP-47-shaped `language`; list nesting <= 9 (Word levels); section nesting <= 20; tables <= 63 columns, <= 10000 rows; `header_rows` >= 0 and clamped to row count.
Profile schema (`app/schemas/profile.py`): `extra="forbid"`; roles must be known and non-empty; `origins` values limited to template|inferred|default|user; hex shading; numeric ranges; BCP-47 language; own `PROFILE_SCHEMA_VERSION`. Caption labels (Table, Figure, Source, Note) configurable — tested with Bangla labels.
Tests: `tests/test_schemas_inline.py` (72). Full suite 175 passed.
Notes for Phase 8 (frontend): shading input sends partial hex while typing (now a 422); B/I buttons should trim whitespace from the selection before wrapping.

## Phase 2 — done
StyleResolver (`app/template_engine/ooxml.py`) — bugs found by probing the fixtures and fixed:
- Theme attributes were ignored when an explicit font sat in the same `rFonts` (Word uses the theme). university Heading 1 was reported as Times New Roman; it is the theme major font, which matches what the render shows.
- `w:cstheme` (lower-case t in the spec) was never read, so Bangla Heading 1 was reported as Kalpurush; its cs font actually comes from the theme.
- Fonts now resolve per slot (ascii/hAnsi/eastAsia/cs), last writer wins along basedOn. Theme parsed via the document relationship, including ea/cs and per-script fonts (`Beng`, `Arab`, ...).
- Added bCs/iCs/rtl, right/end indents, firstLine/hanging exclusivity, `numId 0` cancelling inherited numbering, explicit `bidi w:val=0`, basedOn cycle detection.
- `dominant_script()` returns an ISO 15924 code.
Analyzer (`app/template_engine/analyzer.py`):
- Headings: style id, then localized names with native digits (`Überschrift 1`, `শিরোনাম ১`, `शीर्षक २`, `見出し 1`, `عنوان 2` ...), then outline level. Other roles: id hints, then exact names in several languages. A heading style is never reused for another role. `role_evidence` explains each role (style_id / style_name / outline_level / usage / default_style).
- Page: gutter, header/footer distance, column spacing, section RTL (`sectPr/bidi`), page number format/start.
- Header/footer: default/first/even kinds, even-and-odd setting, page fields in any kind.
- Tables: header bold also from the table style's `firstRow` conditional (respecting `tblLook`); caption label + separator parsed from the template's caption (`Table 1: ...` → `Table`, `: `; `চিত্র ১: ...` → `চিত্র`).
- Language: script from the body text; RTL from script, Normal `bidi` or section `bidi` (docDefaults `bidi="ar-SA"` alone no longer counts); suggested code (`bn`, `ar`); cs/ea font from Normal or the theme's script font.
- Health: added `INHERITED_FIRST_LINE_INDENT`, `STYLE_CYCLE`, `BROKEN_NUMBERING`; heading numbering only counts if the numId exists.
build_default_profile: every leaf rule now has an origin (`rule_paths()` in the profile schema). Roles take the origin from their evidence; labels default per language (en, bn, ar, hi, fr, de, es) as `inferred`; caption labels found in the template win as `template`. `carry_over` records origins for roles it adds and drops origins for roles it removes.
Tests: `tests/test_analyzer.py` (45). Full suite 226 passed; frontend `tsc` clean.
Rendered bangla, rtl, university after the change and inspected them: localized labels appear; layout otherwise unchanged.
Note: defect 1 (nested bullets) was fixed by commit 4217dd5, which was made outside this session while Phase 2 was in progress. Its effect was confirmed by bisecting in clean checkouts.

## Phase 3 — done
Generator (`app/document_engine/generator.py`), each change rendered in LibreOffice and inspected:
- sectPr: missing pgSz/pgMar were appended after `cols`/`docGrid` (schema violation); now sorted (`SECTPR_ORDER`). RTL documents get `sectPr/bidi`.
- Styles: templates are not always schema-ordered (our own university fixture wasn't: `numPr` after `outlineLvl`); every style pPr/rPr is now sorted on output. Fixture builder fixed too.
- Fallback styles mirror b/i/sz into bCs/iCs/szCs; fallback headings reset first-line indent.
- Auto heading numbering: (1) a style reused for several levels was re-linked to each level, ending at the deepest; now each style is linked once. (2) the template's own heading list still claimed the same styles; they are unlinked from it. (3) **Found by rendering:** a style's own `w:ind` overrode the level's hanging indent, so numbers sat 1 cm in and `1.Chapter` had no gap; style and level now share one indent (1.0 cm + 0.3 cm/level). Rendered: numbers hang at the margin.
- Lists: re-verified nesting (1./a./i., •/–/▪) and restart.
- Captions: SEQ cached numbers in native digits when `language.native_digits` (default on for bn, as, ar, fa, ur, ps, hi, mr, ne, origin inferred). Last row of a table keeps with a caption below it.
- Soft line breaks no longer stretch justified lines (`doNotExpandShiftReturn`).
- Columns: unequal columns (`equalWidth=0`) size tables/figures to the narrowest column.
- Images: height limited to 85 % of the page text height (landscape test: tall image fits, caption on the same page).
- Complex scripts: text is split into one run per script; each complex/RTL run gets `lang bidi` of its own script (Arabic inside Bangla = `ar`), `rtl` only on RTL runs, bCs/iCs when the style is bold/italic but lacks bCs/iCs. docDefaults language goes in the slot for the document's script (`bidi` for bn/ar, `eastAsia` for CJK, `val` for Latin) instead of marking Latin text as Bangla.
- Paragraph direction follows the first strong character (explicit `bidi w:val=0` when an RTL style holds LTR text); lists follow the document direction.
Tests: `tests/test_generator.py` (30). Updated two older assertions that encoded the old behaviour (docDefaults `w:val="bn"`; Latin caption digit). Full suite 254 passed, 0 skipped; frontend `tsc` clean.
Not verified: anything in Word itself (no Word on this machine). Rendering is LibreOffice only.
Known limitations added: SEQ numbers render in Latin digits in LibreOffice/PDF; heading and list numbers are Latin digits; when a template has fewer heading styles than the content needs, deeper sections reuse the deepest style and are numbered as that level (e.g. 1.1.2 instead of 1.1.1.1).

## Phase 4 — done
Realistic clipboard samples in `backend/tests/paste_samples/`: Word HTML (mso-list fake lists incl. numbered headings, MsoTitle, MsoCaption with a SEQ field, MsoTableGrid, footnote ref, fonts/colours), Google Docs HTML (docs-internal-guid wrapper, span styles, aria-level lists, bold caption line, note), Excel HTML and Excel text (CRLF, quoted multi-line cell, doubled quotes, empty cells), ChatGPT Markdown, Bangla plain text, mixed plain text (Chapter/1.1/letter lists/Arabic-Indic and Devanagari numbering).
Bugs found by probing the samples and fixed (`app/paste/normalizer.py`):
- HTML source newlines were kept as line breaks: every Word paragraph and the title were full of hard breaks. Source whitespace now collapses (except `<pre>`); only `<br>` breaks.
- Google Docs nested lists (`<ul>` beside the `<li>`) lost their nested items.
- A bold caption line ("Table 1. Revenue by region") was guessed as a heading, so the table lost its caption. Caption-shaped lines are never headings.
- Titles: a short first paragraph directly followed by a heading is the title (Google Docs Title, plain text).
- Plain text: lettered / roman / Bangla-lettered lists (`a)`, `(b)`, `ii.`, `B.`, `ক)`) were merged into the paragraph; now lists (needs two consecutive items, so a lone "a) ..." sentence stays text).
- Plain text: `Note:` / `Source:` / caption lines on consecutive lines were glued into one paragraph; they now stand alone.
- Typed figure caption with no image (plain text cannot carry one) becomes a figure slot with that caption + `FIGURE_NEEDS_UPLOAD`.
- Excel text: quoted cells with line breaks split the table and kept their quotes; `line.strip()` dropped empty first/last cells and shifted columns. Now parsed with `csv` (tab delimiter).
- Header-row cells no longer carry source bold markup (header bold is a profile rule).
Tests: `tests/test_paste_samples.py` (20). Full suite 276 passed.
Rendered end to end (LibreOffice) and inspected: bangla.txt → bangla template, word.html → university, gdocs.html → twocol. Structure, emphasis, sub/superscript, captions (moved to the profile's position), Source/Note lines and nested lists all appear; source fonts/colours do not.
Known limitations added: nested items inherit the list kind of the top level (a bullet under a numbered item renders numbered; ListItem has no per-item kind); lettered lists become ordered lists whose marker style comes from the template; Word footnotes arrive as plain "[1]" text; images that are links or local files (Word clipboard `file:///` images) need a manual upload.

## Phase 5 — done
Validator (`app/validation/validator.py`). Every check has `status` in passed|warning|failed|info|manual (`STATUSES`) and `kind` auto|visual; no score anywhere in the report (tested). `validate_docx(..., analysis=)` takes the template analysis; the API route now passes it.
Kept: page_setup, required_sections, heading_hierarchy, heading_numbering, direct_formatting, table_captions, figure_captions, numbering_continuity (SEQ), table_structure, empty_sections, fonts_used (info), 4 manual visual checks.
Added (auto):
- header_footer: the template's default/first/even headers and footers are present with the same text, and its page-number fields survive.
- page_setup also compares the column count.
- list_numbering: every numbered paragraph points to a numId that exists and an ilvl its abstractNum defines.
- typed_numbering: warns about "1. Introduction" / "1) first" typed on top of Word numbering (native digits recognised).
- xml_order: pPr/rPr/tblPr/tcPr/sectPr child order in document, styles and numbering parts.
- table_fit / figure_fit: width against the (narrowest) text column, figure height against the page.
- figure_images: figures still showing the missing-image placeholder.
- caption_labels: SEQ captions start with the profile's label.
- complex_script: cs font on complex-script runs, w:rtl on RTL runs (judged by letters; Arabic-Indic digits are neutral), bCs on bold complex runs, bidiVisual tables and sectPr/bidi in RTL documents.
- document_language: docDefaults language in the slot for the document's script.
- fonts_used now shows the complex-script font too.
Added (visual, manual): visual_script for complex-script / RTL documents.
Found by the new checks and fixed in the generator: SEQ caption-number runs had no run properties, so native digits (১, ١) had no complex-script font or language. They now get the same script properties as the label.
Tests: `tests/test_validator.py` (24, each breaks a good document one way) + 1 generator test. Full suite 301 passed. Reports for messy, bangla and rtl read clean: no warnings or failures, only the expected info/manual items. rtl re-rendered after the generator change; unchanged.

## Phase 6 — done
Attack fixtures: `backend/tests/make_attacks.py` builds 28 hostile files from the real university template (one attack each, rest of the package valid) plus 6 normal-but-unusual templates that must be accepted. `tests/test_attacks.py` also asserts nothing parses the file before the checks finish.
Upload checks (`app/core/uploads.py`), gaps found by auditing and fixed:
- Remote content: only `attachedTemplate` with double-quoted attributes was refused. Every `.rels` is now parsed (safe parser) and any `TargetMode="External"` except hyperlinks is refused (templates, linked images, frames ...), so LibreOffice cannot be made to fetch a URL during PDF export.
- Fields: DDE / DDEAUTO / INCLUDEPICTURE / INCLUDETEXT / LINK / IMPORT refused, including instructions split across runs and `fldSimple`.
- DOCTYPE/ENTITY scan decoded UTF-16 parts (raw-byte regex missed them) and scans XML hidden under non-.xml names.
- ZIP bombs measured by inflating each raw stream with a budget instead of trusting header sizes (a 50 MB part declared as 1 KB is refused); size mismatch = refused.
- Duplicate entry names, drive-letter / control-character names, OLE `.bin` embeddings (Office packages like chart `.xlsx` still allowed) refused; password-protected/old `.doc` files get a clear message.
- `safe_xml()` (no DTD, no entities, no network) is used for the theme too (it used lxml's default parser).
Images: EXIF orientation applied before metadata is dropped (phone photos were sideways); pixel limit checked from the header before decoding; trailing payloads/text chunks verified gone.
Passwords/tokens: scrypt raised to OWASP minimum N=2^17,r=8,p=1 (0.65 s per hash here), parameters stored in the hash, legacy hashes verify and are re-hashed at login; >1024-char passwords refused before hashing; tampered/expired tokens tested; production refuses a secret under 32 chars.
Rate limiting: limiter is thread-safe and forgets idle keys. Failed sign-ins limited per account (10/min) and per address (50/min); a blocked account is refused even with the right password; unknown accounts cost the same time as wrong passwords. Template upload, new version, media upload and paste now use the heavy-operation limit; one paste keeps at most 50 images.
PDF: LibreOffice runs in its own process group with stdin closed, `--nologo --nodefault --nolockcheck`; on timeout the whole tree is killed (`taskkill /T` / `killpg`). Verified on Windows: no `soffice.bin` survives a timeout — note it did not survive before the change either (measured). The POSIX path is NOT verified (no Linux here).
Tests: 64 in `test_attacks.py`, 6 new API tests. Full suite 371 passed.
Known limits: rate limits are per process (several workers = several budgets); no token revocation on password change; LibreOffice sandboxing is process-level only (no container/seccomp).

## Phase 7 — done
fastapi 0.139, SQLAlchemy 2.0.45 and httpx 0.27 were already installed; `test_api.py` runs (13 tests, first executed in Phase 0) plus the new `test_api_versions.py` (13).
Test isolation: the throw-away data dir / database / secret moved into `conftest.py`, set before anything imports `app.config`, so no API test can touch `backend/storage/` (before, only `test_api.py` did this; another API test module run alone would have used the real DB). Shared `client` fixture + `tests/api_helpers.py`.
Gaps found and fixed:
- Approved ProfileVersion immutability was enforced only in the PUT route. Now a SQLAlchemy `before_flush` guard (`ImmutableVersionError`) refuses any change to rules/approved/version/template of an approved row and its deletion; deleting a whole unused template sets an explicit session flag.
- Origins were whatever the client sent. The server now computes them on every rules save (`record_user_edits`): changed rules/roles become `user`, the rest keep their origin; forged origins are ignored (tested).
- New `GET /api/templates/{id}/profiles`: every profile version of every template version, newest first.
- `DocumentCreate.language` had no pattern: a bad tag raised inside the route (500). Now 422.
- Generated files and validation reports grew without limit; the newest `SMARTDOC_KEEP_GENERATED_FILES` (20) are kept per document, older files deleted from disk.
- SQLite now runs with `foreign_keys=ON`, WAL and a 10 s busy timeout (concurrent saves wait instead of "database is locked").
- `datetime.utcnow()` replaced (deprecated).
Verified by tests: editing an approved profile makes version 2 as a draft and leaves version 1 and its documents unchanged; a new template version carries user choices (with `user` origins) as an unapproved draft; an old document is still built from template version 1 (one column) after version 2 (two columns) is uploaded, and from version 2 after switching profiles; each generated file records its profile version; a template in use cannot be deleted; 19 resource routes return 404 to another user, including building on or switching to someone else's profile; another user's image id in my content is not embedded.
Full suite 384 passed; frontend `npm run build` OK.
Known limitations: no schema migrations (tables come from `create_all`; an existing dev database keeps old columns and old content that the stricter Phase 1 schemas may now refuse); frontend does not use the profile-history endpoint yet (Phase 8).

## Phase 8 — done
`npm run build` (tsc + Vite) passes; new `npm test` runs frontend unit tests for the editing helpers (esbuild bundle + node:test, 6 tests).
Fixed before the browser run (known from earlier phases / code reading):
- Shading box sent half-typed hex (now refused by the API); `HexInput` only commits empty or 6 digits and shows a hint.
- B/I/x²/x₂ wrapped edge spaces (`** word **` stays literal); `wrapText` trims them and escapes spaces in sup/sub.
- Excel paste into the table grid split quoted multi-line cells; `parseTsv` handles quotes, doubled quotes, CRLF, empty cells.
- Document template picker could not show the pinned profile version; documents now report template id/name/version, rules version and the newest approved profile (API + test), and the editor shows "name (template vN, rules vM)" plus a "Use the newer version" notice.
- Template editor: uses the server's returned rules/origins after saving, native-digits checkbox, version history panel; paste box gets "Analyse typed text".
Browser run (built-in browser, production build served by the API on :8001 with a throw-away data dir; another uvicorn someone runs on :8000 was left alone, so the Vite dev server, which proxies to :8000, was not used):
register → upload university.docx → template editor (analysis, health, role map with resolved theme fonts) → sample preview (docx-preview) → partial hex refused, E2EFDA saved → approve v1 → create document → paste Word clipboard HTML (3 sections, 1 table, title) → insert → autosave → live preview refresh → formatting checks (16 passed, 0 warnings, 0 failed, 4 manual) → Download DOCX (generate + download 200) → Export PDF (200, ~8 s) → table grid Excel paste → bold button on a selection with spaces → figure upload (preview shows the image) → upload template v2, approve → document shows the newer-version notice → switch → picker shows template v2. No console errors; server log shows only favicon 404s.
The downloaded DOCX was rendered with LibreOffice and inspected: header, numbered headings, lists, the table with the E2EFDA header shading set in the UI, caption and source line.
How files were provided: the pane has no file-picker tool, so fixtures were fetched from a temporary `dist/e2e/` folder and placed into the hidden file inputs with DataTransfer + a change event; clipboard pastes were dispatched as real `paste` events with the Word HTML / TSV payloads. The OS file dialog and the system clipboard themselves were not exercised.
Bugs found by the browser run and fixed: version history did not refresh after uploading a new template version; table cells were one-line inputs, so a pasted cell line break would be lost on the next edit (now auto-sized textareas); the editor showed `NO~3^~−^` (serializer now closes markers before opening: `NO~3~^−^`, fuzz test still passes); missing favicon. All re-checked in the browser after the fix.
New dev helper: `backend/scripts/dev_server.py --data DIR --port N`.
Not verified: the Vite dev server (`npm run dev`), mobile layout, Safari/Firefox, keyboard-only use, screen readers.
Full suite 386 passed.

## Phase 9 — done
Real templates: the two files the user uploaded on 2026-11-04 through the server on :8000 (`backend/storage/templates/1/`): `IJPCR_template.docx` (International Journal of Peace and Conflict Research layout template) and `Proofreading_42_IJPCR.docx` (an article in that layout). Worked on copies; the storage folder and its database were only read.
Found and fixed (each with a test on a new synthetic `journal` fixture modelled on IJPCR):
- **Crash:** generation failed on both templates (`AttributeError`): two table styles have no `w:name`. Every preview/download would have been a 500.
- **Wrong styles:** the template's sample content uses its own `IJPCR Heading 1..3`, `IJPCR Body Text`, `IJPCR Body First`, `IJPCR List Bullet`, `IJPCR Table Caption`, `IJPCR Table Text`, `IJPCR Block Quote`, while Word's built-in Heading 1..6 and Caption are unused. The analyzer picked the unused built-ins (H1 rendered as 10 pt Tahoma, H2 as Word's blue Cambria). Now: names that contain the role keyword or "heading N" are matched, and styles the template actually uses beat unused built-ins; Word templates keep their built-in mapping (tested).
- **New role `body_first`** (first paragraph after a heading, no first-line indent), which this template documents; detected by name, used by the generator after section headings only, optional.
- **Leftover media:** relationships of the cleared body (images, charts, links) are dropped. The IJPCR output stays ~4 MB because the template embeds ~6.7 MB of fonts — that is the template's design and is kept.
- **Health:** `BODY_LAYOUT_REMOVED` (images/text boxes/placeholders in the body, e.g. a first-page banner, side panel, abstract box and licence block — all removed by design rule 1) and `PLACEHOLDERS` (`{{DOI}}`, `{{VOLUME}}` … in the header are kept as typed text, not filled).
Rendered before and after and inspected: after the fix, IJPCR output uses the journal's headings (Trebuchet bold caps / title case / bold italic), Body First then indented Body Text, bold centred table captions above tables. Proofreading manuscript: a finished article formatted with direct formatting rather than styles; it keeps the built-in mapping and the HEAVY_DIRECT_FORMATTING warning explains why.
Decision left to the user (not implemented): keeping the first-page body layout and filling `{{PLACEHOLDERS}}` would contradict design rule 1.
README rewritten: install, run, test, what is verified and how, what is not verified, known limitations.
Full suite 393 passed; frontend build and `npm test` pass; new role checked in the browser.

## Phase 9b — keep the template's first-page layout and fill placeholders (user approved 2026-11-06)
CLAUDE.md rule 1 amended accordingly.
- Profile `keep_template_layout` (inferred on when the template body has `{{PLACEHOLDERS}}`): the body up to the template's first heading **with text** is kept; content replaces the rest. A hidden `_SmartDocContent` bookmark marks where content starts so the validator judges only content (kept banner tables / logos are not "tables without captions").
- `app/core/placeholders.py`: find/fill `{{NAME}}` across split runs; value takes the formatting of the run where the placeholder starts; complex-script properties added for non-Latin values. TITLE/SUBTITLE/AUTHORS/ABSTRACT/KEYWORDS from the document, others from `DocumentContent.fields` (new, validated). Header/footer placeholders filled in both modes. The generator does not add its own title/author/abstract/keywords when the kept layout already shows them.
- Analyzer: `placeholders` list (name + where) in the analysis; `BODY_LAYOUT` and `PLACEHOLDERS` health messages describe the setting. Validator: `placeholders` check (warning per unfilled one); `header_footer` accepts filled placeholders as unchanged text.
- API: documents list their template's placeholders; frontend: layout toggle in the template editor, "Template fields" box in the document editor.
Bugs found while building it and fixed with tests:
- `fill()` de-duplicated paragraphs by `id()` of lxml proxies; freed proxies' ids are reused, so header paragraphs were skipped at random (first generation in a process failed, later ones passed). Now keeps the elements themselves; regression test repeats 30×.
- IJPCR has an **empty paragraph styled Heading 1** inside its first-page layout; the kept part ended there and lost the "Cite this article" box and licence block, and content overlapped the floating abstract box. Empty heading-styled paragraphs no longer end the layout (journal fixture reproduces it).
- `header_footer` reported a filled header as "changed".
Rendered the user's IJPCR template with realistic values and inspected: page 1 is the journal's own first page with banner, title, author + ORCID icon, side panel (dates, ISSN, email, affiliation), abstract box, filled "Cite this article" box, licence block with logo; header shows DOI/volume/issue/pages; page 2 continues with the pasted content in the journal's styles. Validator: 0 failed. Browser: upload of the real template → toggle on by default, health messages, approve, document shows 12 template fields, typing the DOI updates the live preview's header.
Not verified: Word itself; templates whose layout continues past their first heading; text-box contents that overflow when a long title is filled (Word may grow or clip the box).
Full suite 411 passed; frontend build and tests pass.

## Feature — predefined visual designs with form-based generation (Workflow B, 2026-11-06)
Workflow B: choose a design → fill a form → live preview → check → DOCX/PDF. First design: IJPCR (from the user's `IJPCR_template.docx`). Workflow A (custom template upload) is untouched. Detailed spec: `docs/designs/ijpcr-design-spec.md`; integration plan and risks: `docs/designs/predefined-designs-plan.md`.

Decisions
- **First page rebuilt as flowing tables** (user chose option B): the template's fixed-position shapes are not reused; banner, title, authors, side panel + abstract box, citation box and licence/logo are tables and paragraphs that grow with their content, so a long abstract or many authors push the rest down instead of overlapping.
- Three separate parts: the document schema (`app/schemas/article.py`, `ArticleContent`), the design package (`app/designs/ijpcr/v1/`: `base.docx`, `design.json`, logo, ORCID icon; built by `scripts/build_design_ijpcr.py`) and the fixed generator (`app/designs/generator.py`, `DesignGenerator` subclass of `Generator`). Section names are never hardcoded: the body is the ordinary box tree, any titles, any order, any depth.
- Base engine changes, all defaulted so Workflow A is unchanged: a no-op `add_back_matter()` hook; profile `heading_number_suffix` ("tab" default, "space"); optional `figure_caption` role, used only when mapped.
- Database: two new tables only (`design_documents`, `design_generated_files`), created by `create_all`. Checked on a copy of the real database: only the two tables were added, existing rows unchanged. No reset, no deletion.
- Versioning: a document is pinned to the design version it was created with; a newer version is offered and applied only on "upgrade".
- No external AI calls.

API: `GET /api/designs`, `POST /api/designs/{id}/sample`, CRUD on `/api/design-documents`, `…/{id}/upgrade|preview|generate|validate|pdf`, `…/{id}/files`, `…/files/{fid}/download`. Every route answers 404 to other users.
Frontend: `#/designs` gallery (sample preview, create, list), `#/articles/{id}` editor (metadata, affiliations, authors with corresponding/ORCID/reorder, abstract, keywords, free body via the existing box editor, declarations, references manager with bulk add, autosave + live preview, checks, DOCX, PDF, upgrade notice).

Tests: `test_article_schema.py` (13), `test_design_ijpcr.py` (22: registry, the 16 requested scenarios, rendered checks), `test_api_designs.py` (9). The original tests were not changed to make the feature pass.
Rendered and inspected (LibreOffice → PNG): page 1 against the reference; long abstract (box grows, citation box moves below, no overlap); six authors / three affiliations; 5-level nesting (1 … 1.1.1.1.1); many tables and figures (captions in place); long references (hanging indent across pages); long document (header and page numbers on every page).
Browser run (production build, throw-away data folder): gallery, sample preview, create article, affiliation + author, abstract, section, reference bulk add, autosave and live preview, Check formatting (11 passed · 2 warnings · 0 failed · 4 visual), Download DOCX (generate + download 200).

Preserved: page size and margins, header with DOI/volume/issue/pages, footer page number, banner colour and text, fonts and sizes, side panel, abstract and citation box colours and borders, logo and licence, body styles, embedded fonts.
Approximated: abstract box corners are square (template: rounded shape); positions follow content instead of being fixed; the body starts on page 2 (new page) rather than flowing beside the boxes; small gap between the ORCID icon and the next comma.
Unsupported / not verified: Microsoft Word itself; the output is about 7 MB because the template embeds 12 fonts; docx-preview crops the wide page slightly.
Full suite 458 passed (411 earlier + 47 new); frontend build and `npm test` pass.
