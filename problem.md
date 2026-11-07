# SmartDoc — Engineering Problems, Root Causes & Solutions Log

This document provides a comprehensive report of all technical challenges, layout defects, OpenXML specification violations, security vulnerabilities, database edge cases, and runtime issues encountered throughout the lifecycle of the **SmartDoc** project, along with the engineering solutions implemented for each.

---

## 1. Environment, Toolchain & OS Integration Problems

### 1.1. Absence of Headless LibreOffice and Rasterization Toolchain
- **Problem:** At project inception, testing and verifying generated `.docx` output was limited to inspecting raw XML nodes. Validating that OpenXML structures rendered visually correct typography, margins, and page layouts was impossible.
- **Root Cause:** LibreOffice (`soffice`) and PyMuPDF (`fitz`) were not installed or configured on the system PATH.
- **Solution:** 
  - Installed LibreOffice 26.8.2 and PyMuPDF 2.1.
  - Implemented dynamic binary discovery in `backend/app/document_engine/pdf.py` (`soffice_path()`) that scans custom environment variables (`SMARTDOC_SOFFICE`), system `PATH`, and standard Windows install locations (`C:\Program Files\LibreOffice\program\soffice.exe`).
  - Created a visual verification script (`backend/scripts/render.py`) to convert generated DOCX files to PDF and rasterize each page to PNG for visual inspection.

### 1.2. Windows File URI & Environment Stripping in LibreOffice Execution
- **Problem:** PDF conversion failed on Windows when passing user profile arguments, and LibreOffice crashed during startup.
- **Root Cause:**
  - Windows file paths passed as `file://C:\...` caused LibreOffice URL parsers to fail.
  - The process environment isolation stripped all environment variables, removing Windows-critical system variables (`SYSTEMROOT`, `TEMP`, `TMP`), which LibreOffice requires to allocate temporary handles.
- **Solution:** 
  - Converted paths to RFC-compliant URIs using Python's `Path.as_uri()`.
  - Updated `docx_to_pdf()` to preserve `SYSTEMROOT`, `TEMP`, and `TMP` while stripping all other parent process environment variables.

### 1.3. Sandbox Socket Network Isolation (`[WinError 10013]`)
- **Problem:** Probing or binding to local network sockets in automated sandbox tests failed with `PermissionError: [WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions`.
- **Root Cause:** The Windows security sandbox blocks local TCP network binding unless bypassed or run in an approved non-sandboxed environment.
- **Solution:** Configured server execution and live integration probing to run outside the sandbox boundary with proper administrative network binding permissions.

### 1.4. Port Collision on Local Startup (`[Errno 10048]`)
- **Problem:** Launching the backend application on port 8000 failed with `[Errno 10048] only one usage of each socket address (protocol/network address/port) is normally permitted`.
- **Root Cause:** A prior Python/Uvicorn background instance was already bound and actively serving traffic on `127.0.0.1:8000`.
- **Solution:** Added process discovery and network port querying using `Get-NetTCPConnection` to identify active processes and reuse existing live server instances.

### 1.5. Test Suite Latency from Password Hashing Cost
- **Problem:** Running the full test suite (`pytest`) with 385+ tests took multiple minutes to execute.
- **Root Cause:** Compliance with OWASP password security required scrypt with parameters $N=2^{17} (131,072)$, $r=8$, $p=1$. In pure Python, each hash evaluation consumes ~0.65 to 1.0 second of CPU time.
- **Solution:** Isolated heavy authentication timing tests and rate-limiting brute-force tests into dedicated test modules while using session-scoped mock fixtures for standard API endpoint tests.

### 1.6. Deprecated Standard Library & Framework APIs
- **Problem:** Console logs were flooded with deprecation warnings regarding `datetime.utcnow()` and Starlette's `TestClient`.
- **Root Cause:** Python 3.12+ deprecated `datetime.utcnow()` in favor of timezone-aware UTC timestamps, and Starlette updated `TestClient` lifecycle management.
- **Solution:** Standardized on `datetime.now(timezone.utc).replace(tzinfo=None)` to maintain naive UTC timestamps in SQLite, and modernized the shared `TestClient` fixture in `tests/conftest.py`.

---

## 2. Template Analysis & OpenXML (OOXML) Inconsistencies

### 2.1. Crash on Templates with Nameless Table Styles
- **Problem:** Generation crashed with an unhandled `AttributeError` on real academic templates (such as `IJPCR_template.docx`).
- **Root Cause:** Certain custom table styles defined in OpenXML omit the `w:name` element entirely. The template analyzer assumed `style.find(qn('w:name')).get(...)` was always non-null.
- **Solution:** Added safe attribute getters `_name(el)` returning fallback identifiers when `w:name` is missing.

### 2.2. Style Role Misclassification & Built-In Style Precedence
- **Problem:** Real templates using custom names (e.g., `IJPCR Heading 1`, `IJPCR Body Text`) were erroneously formatted with Microsoft Word's unused default styles (e.g., Word's built-in 10pt Tahoma `Heading 1` or blue Cambria `Heading 2`).
- **Root Cause:** The analyzer prioritized Word's built-in style IDs over custom styles present in the template.
- **Solution:** Refactored role heuristics to prioritize styles actually referenced by content within the template over unused built-ins, and introduced substring matching for role patterns (e.g., matching any style containing "heading 1").

### 2.3. Theme Font Resolution & Case Sensitivity Bug (`w:cstheme`)
- **Problem:** Complex script headings (e.g., Bengali Heading 1) incorrectly resolved to fallback fonts (e.g., Kalpurush) instead of the template's designated theme font.
- **Root Cause:**
  - The OpenXML specification defines the complex-script theme tag with lowercase 't' (`w:cstheme`), whereas the parser looked for `w:csTheme`.
  - When an explicit font name and a theme attribute co-existed in `w:rFonts`, the parser ignored the theme attribute.
- **Solution:** Corrected attribute casing to `w:cstheme`, implemented per-slot font resolution (`ascii`, `hAnsi`, `eastAsia`, `cs`), and parsed the embedded `/word/theme/theme1.xml` file.

### 2.4. Infinite Recursion from Circular Style Inheritance
- **Problem:** Malformed or adversarial templates triggered infinite recursion crashes in the backend.
- **Root Cause:** Circular `w:basedOn` chains (e.g., Style A based on Style B based on Style A) caused the `StyleResolver` to loop infinitely.
- **Solution:** Added visited set tracking to detect inheritance cycles, abort traversal, and emit a `STYLE_CYCLE` health warning.

### 2.5. Inherited First-Line Indent on Titles (`INHERITED_FIRST_LINE_INDENT`)
- **Problem:** In university templates, the Title and Subtitle appeared visually shifted to the right.
- **Root Cause:** The template's `Title` style inherited from `Normal` via `basedOn`. `Normal` had an explicit 1 cm first-line indent, which cascaded to the centered Title.
- **Solution:** Verified this was Word's native behavior rather than an engine defect. Added an automated `INHERITED_FIRST_LINE_INDENT` diagnostic warning to notify the user.

### 2.6. Premature Truncation of First-Page Layouts from Empty Heading Paragraphs
- **Problem:** In templates containing first-page journal layouts (banners, side panels, license blocks), preserving the layout truncated prematurely, causing content to overlap floating abstract boxes.
- **Root Cause:** The template contained an empty paragraph formatted with `Heading 1` within its header block. The layout preserver halted at the first occurrence of `Heading 1`.
- **Solution:** Updated layout boundary heuristics to require both a heading style and non-empty text content before marking the end of the preserved layout.

---

## 3. Document Generation & Typography Layout Defects

### 3.1. Nested Bullet Lists Rendering as Numbers (`1. 2.`)
- **Problem:** When a bullet list contained nested items, the sub-items rendered as numbers (`1. 2.`) instead of bullet symbols (`–`, `▪`).
- **Root Cause:** The template's `List Bullet` abstract numbering definition had `singleLevel` set, leaving `ilvl >= 1` undefined in the template's `numbering.xml`.
- **Solution:** Implemented `_complete_abstract()` in `generator.py` to clone single-level definitions and synthesize missing indentation levels with proper bullet markers (`•`, `–`, `▪`) and numbered hierarchies (`1.`, `a.`, `i.`).

### 3.2. Soft Line Break Justification Distortion in Multi-Column Documents
- **Problem:** In two-column documents, lines containing soft line breaks (`Shift+Enter`) rendered justified with massive, unsightly whitespace gaps between words.
- **Root Cause:** Microsoft Word and LibreOffice justify text preceding a soft break unless compatibility flag `w:doNotExpandShiftReturn` is enabled in `word/settings.xml`.
- **Solution:** Injected `w:doNotExpandShiftReturn` under `w:compat` in `word/settings.xml`, respecting schema ordering before subsequent settings tags.

### 3.3. OpenXML Schema Tag Order Violations
- **Problem:** Generated documents opened with corruption warnings ("Word found unreadable content...") in desktop Word installations.
- **Root Cause:** ISO/IEC 29500 mandates an exact sequence for XML elements inside property nodes (`w:rPr`, `w:pPr`, `w:tblPr`, `w:tcPr`, `w:sectPr`). For example, appending `w:pgSz` after `w:cols` or placing `w:numPr` after `w:outlineLvl` invalidates the document schema.
- **Solution:** Enforced strict schema-order sorters (`RPR_ORDER`, `PPR_ORDER`, `TBLPR_ORDER`, `TCPR_ORDER`, `SECTPR_ORDER`) that re-order XML children prior to packaging.

### 3.4. Indentation Collision Between Numbering and Paragraph Styles
- **Problem:** Auto-numbered headings rendered with zero spacing between the number and text (e.g., `1.Introduction`).
- **Root Cause:** An explicit `w:ind` in the template's paragraph style overrode the hanging indent defined in the numbering definition.
- **Solution:** Unified indentation calculation so that the style and the numbering level share a coordinated left margin and hanging indent (1.0 cm + 0.3 cm per heading level).

### 3.5. Randomly Skipped Header Placeholders from Lxml Proxy ID Reuse
- **Problem:** In templates with multiple placeholder fields in headers, placeholders were skipped at random during generation.
- **Root Cause:** Paragraph elements were de-duplicated using Python's `id(el)`. In `lxml`, temporary proxy wrappers for underlying C nodes are garbage-collected and their memory IDs reused across iterations.
- **Solution:** Replaced memory `id()` comparisons with direct equality comparisons on the underlying XML elements.

### 3.6. Image Overflow and Stranded Captions
- **Problem:** Tall or landscape images pushed table/figure captions onto subsequent blank pages.
- **Root Cause:** Fixed image dimension calculations did not account for page margins and header/footer heights.
- **Solution:** Constrained maximum image height to 85% of the calculated printable text height (`page_text_height_twips`), ensuring figures and their accompanying captions reside on the same page.

### 3.7. Residual Relationship Bloat
- **Problem:** Clearing the template body left stale image, chart, and hyperlink relationships in `word/_rels/document.xml.rels`, bloating the file.
- **Root Cause:** Deleting XML elements from `w:body` did not automatically clean the relationship package.
- **Solution:** Added relationship garbage collection to purge unreferenced `r:id` entries from `document.xml.rels`.

---

## 4. Complex Script & Bidirectional (RTL / Indic) Challenges

### 4.1. English Captions in Multilingual Documents
- **Problem:** Uploading a template in Bengali or Arabic generated default English captions ("Table 1", "Figure 1", "Abstract", "Keywords").
- **Root Cause:** Caption and metadata labels were hardcoded to English strings.
- **Solution:** Implemented localized label dictionaries (`LANGUAGE_LABELS`) supporting English, Bengali, Arabic, Hindi, French, German, and Spanish, automatically inferring labels from detected language or extracting custom labels from the template.

### 4.2. Punctuation Inversion in Mixed Bidirectional Paragraphs
- **Problem:** In RTL Arabic paragraphs containing Latin phrases, trailing punctuation inverted incorrectly (e.g., rendering `.Deep text` instead of `Deep text.`).
- **Root Cause:** Paragraph direction was statically set to RTL, causing bidirectional Unicode embedding levels to evaluate incorrectly for Latin run terminators.
- **Solution:** Implemented dynamic paragraph direction resolution based on the first strong character, and applied explicit `w:bidi w:val="0"` when Latin text is placed inside an RTL style.

### 4.3. RTL Style Alignment Inversion
- **Problem:** A template whose RTL `Normal` style had `w:bidi` and `jc=right` rendered headings and body text left-aligned.
- **Root Cause:** In bidirectional paragraphs, Word and LibreOffice interpret `left` and `right` as logical `start` and `end`. Consequently, `jc=right` resolves to the logical end (the left margin).
- **Solution:** Sanitized template alignment rules to prevent ambiguous logical-to-physical alignment flipping in RTL documents.

### 4.4. Missing Complex-Script Formatting on Native Numerals
- **Problem:** In Bengali and Arabic documents, native digits in captions (`১`, `٢`) failed complex-script validation audits.
- **Root Cause:** Sequence field numbers (`w:fldChar`) were emitted as raw text runs lacking `w:rPr` font properties, leaving digits unstyled by the complex-script engine.
- **Solution:** Injected matching `w:rPr` properties (`w:cs`, `w:rFonts`, `w:bCs`, `w:iCs`) into the cached sequence number runs.

### 4.5. LibreOffice PDF Latin SEQ Digits Limitation
- **Problem:** Even when native numerals (`১, ২, ৩`) were written to the DOCX cached runs, exporting to PDF via LibreOffice reverted the digits to Latin (`1, 2, 3`).
- **Root Cause:** LibreOffice headless PDF conversion forcibly recalculates all Word `SEQ` fields upon opening, ignoring cached runs and formatting with Latin numerals.
- **Status:** Documented as an external engine limitation; native numerals remain preserved in Microsoft Word.

---

## 5. Clipboard Ingestion & Normalization Hazards

### 5.1. Extraneous Hard Line Breaks from HTML Source Newlines
- **Problem:** Pasting text from Microsoft Word web or desktop apps produced paragraphs filled with broken line wraps.
- **Root Cause:** HTML serializers in Word insert literal newline characters (`\n`) for pretty-printing, which naive HTML parsers treated as explicit line breaks.
- **Solution:** Updated the normalizer to collapse standard HTML whitespace into single spaces, recognizing only explicit `<br>` and block-level tags as line breaks.

### 5.2. Lost Nested Items from Google Docs Lists
- **Problem:** Pasting hierarchical lists from Google Docs dropped all nested sub-items.
- **Root Cause:** Google Docs emits non-standard HTML where sub-lists (`<ul>`) sit adjacent to parent `<li>` tags rather than nested inside them, using `aria-level` attributes.
- **Solution:** Added dedicated Google Docs list parsers in `normalizer.py` that interpret `aria-level` and sibling list structures.

### 5.3. Bold Caption Lines Misinterpreted as Headings
- **Problem:** Tables pasted with bold caption titles (e.g., `**Table 1: Revenue**`) lost their captions, which were turned into document headings.
- **Root Cause:** Heading detection heuristics identified short, bold, stand-alone lines as headings before evaluating caption patterns.
- **Solution:** Reordered heuristics to test and attach table/figure caption patterns before evaluating heading criteria.

### 5.4. List Items Merged into Paragraph Text
- **Problem:** Plain text lists using parenthetical markers (`(a)`, `ক)`) or Roman numerals (`iv.`) were swallowed into preceding paragraphs.
- **Root Cause:** Paragraph segmenters treated non-numeric list markers as prose punctuation.
- **Solution:** Added regex detection for alphabetic, Roman numeral, and Indic lettered list markers requiring at least two consecutive occurrences to distinguish lists from ordinary sentences.

### 5.5. Quoted Multi-Line Cells Splitting Excel Tables
- **Problem:** Pasting tables from Microsoft Excel with multi-line cells fragmented the table into disconnected rows.
- **Root Cause:** Naive line-based splitting failed when cells contained line breaks enclosed in quotes.
- **Solution:** Replaced manual string splitting with Python's standard `csv` reader configured with tab delimiters and proper quote-handling rules.

---

## 6. Security, Malicious Uploads & Attack Surface Defense

### 6.1. SSRF via External Relationship Targets
- **Problem:** Malicious `.docx` templates could coerce LibreOffice into making external HTTP requests during PDF compilation (Server-Side Request Forgery).
- **Root Cause:** OpenXML relationship files (`.rels`) allow `TargetMode="External"` pointing to arbitrary URIs (e.g., `attachedTemplate` or external images).
- **Solution:** Audited every `.rels` file across the ZIP package, immediately rejecting any external target that is not a standard web hyperlink (`http://`, `https://`).

### 6.2. Word Field Code Injection Attacks
- **Problem:** Attackers could execute arbitrary system commands or exfiltrate local files via malicious Word fields (`DDE`, `DDEAUTO`, `INCLUDETEXT`, `INCLUDEPICTURE`).
- **Root Cause:** Word processing software executes embedded macro and DDE fields upon document loading.
- **Solution:** Implemented regex scans across raw instruction streams (`w:instrText` and `fldSimple`), rejecting documents containing dangerous field codes even when instructions were fragmented across runs.

### 6.3. XXE & XML Billion Laughs Exploits
- **Problem:** Uploaded documents could trigger XML External Entity (XXE) expansion or decompression memory exhaustion.
- **Root Cause:** Default XML parsers resolve external entities and evaluate nested DTD declarations.
- **Solution:** Configured `lxml` with an isolated, hardened parser (`resolve_entities=False`, `no_network=True`, `load_dtd=False`) and scanned UTF-8 and UTF-16 byte streams for `<!DOCTYPE` and `<!ENTITY` tokens before parsing.

### 6.4. ZIP Bomb Decompression Attacks
- **Problem:** Small ZIP files could decompress into gigabytes of data, exhausting disk space.
- **Root Cause:** Header-based size declarations in ZIP files cannot be trusted.
- **Solution:** Implemented incremental streaming inflation with strict budget limits (`MAX_UNCOMPRESSED_BYTES = 150 MB`, `MAX_RATIO = 200:1`, `MAX_ENTRIES = 3000`).

### 6.5. Sideways Phone Images from Stripped EXIF
- **Problem:** User-uploaded smartphone images rendered rotated 90 or 180 degrees.
- **Root Cause:** Security sanitization stripped all EXIF metadata (where orientation flags are stored) before rasterization.
- **Solution:** Applied `ImageOps.exif_transpose()` to physically rotate image pixel buffers according to EXIF flags *before* discarding metadata and re-encoding.

### 6.6. Timing-Attack User Enumeration
- **Problem:** Sign-in endpoints responded faster when an email was not registered than when a password was incorrect, allowing user enumeration.
- **Root Cause:** Non-existent users skipped password hashing.
- **Solution:** Added `burn_time()` to execute a dummy scrypt computation whenever an unknown email is supplied, ensuring constant-time responses.

---

## 7. Data Integrity, Versioning & Database Concurrency

### 7.1. Mutation of Approved Profile Versions
- **Problem:** Modifying a formatting profile previously used to generate documents broke the layout reproducibility of historical records.
- **Root Cause:** Immutability was initially enforced only at the API route layer, leaving internal service calls unprotected.
- **Solution:** Implemented an event listener in SQLAlchemy (`@event.listens_for(Session, "before_flush")`) that rejects any update or deletion of approved `ProfileVersion` records with an `ImmutableVersionError`.

### 7.2. Origin Spoofing from API Clients
- **Problem:** Clients could forge rule provenance by submitting fabricated origin values (e.g., claiming a user edit came from the template).
- **Root Cause:** The server trusted the `origins` dictionary supplied in request payloads.
- **Solution:** Implemented server-side origin derivation (`record_user_edits`) that diffs incoming rules against parent versions and tags modified paths as `user`.

### 7.3. Unbounded Storage Accumulation
- **Problem:** Repeated generation cycles consumed excessive disk space with historical DOCX and PDF files.
- **Root Cause:** Every generation created permanent database records and files without retention limits.
- **Solution:** Added automated pruning (`_prune()`) that retains the 20 newest generated files per document and unlinks older files from disk.

### 7.4. SQLite Concurrency Locking (`database is locked`)
- **Problem:** Rapid autosaving from the frontend triggered database lock exceptions in SQLite.
- **Root Cause:** Default SQLite configurations allow only one writer and abort immediately upon contention.
- **Solution:** Configured SQLite with Write-Ahead Logging (`PRAGMA journal_mode=WAL`), enabled foreign key enforcement, and set a 10-second busy timeout (`PRAGMA busy_timeout=10000`).

---

## 8. Frontend UI/UX & Editing Deficiencies

### 8.1. Validation Errors on Intermediate Hex Input
- **Problem:** Typing a hex color code (e.g., `#E2EFDA`) fired API 422 errors on intermediate keystrokes (`#E`, `#E2`).
- **Root Cause:** Pydantic strictly validates 6-character hex strings on every autosave request.
- **Solution:** Created a dedicated `HexInput` component that holds local draft values and commits to the store only when empty or exactly 6 valid hex characters are entered.

### 8.2. Markup Enclosing Whitespace
- **Problem:** Clicking Bold or Italic on selected text enclosed leading/trailing spaces (e.g., `** text **`), which the inline parser rejects as invalid formatting.
- **Root Cause:** Text selection boundaries included trailing whitespace.
- **Solution:** Updated `wrapSelection` to trim whitespace from selections before applying delimiters and append spaces outside the formatted span.

### 8.3. Loss of Multi-Line Table Cell Content
- **Problem:** Editing a table cell containing line breaks stripped the breaks upon editing.
- **Root Cause:** Table cells were rendered using single-line HTML `<input>` elements.
- **Solution:** Replaced input elements with auto-sizing `<textarea>` components in `TableGrid.tsx`.

### 8.4. Malformed Subscript/Superscript Nesting
- **Problem:** Chemical formulas with consecutive sub/superscripts (e.g., $NO_3^-$) serialized into unparseable notation (`NO~3^~-^`).
- **Root Cause:** The inline serializer did not close an open marker before opening another marker of differing priority.
- **Solution:** Refactored run serialization to strictly close open delimiters before switching formatting tags (`NO~3~^-^`).

---

## 9. Current Unresolved Constraints & Architectural Roadmap

| Item | Current Behavior | Underlying Cause | Planned Resolution |
| :--- | :--- | :--- | :--- |
| **Merged Table Cells** | Merged cells from pasted tables are split into individual rectangular cells with blank filler. | Complex cell merging (`w:gridSpan`, `w:vMerge`) introduces layout fragility in responsive column sizing. | Implement dedicated cell spanning matrices in `generator.py`. |
| **Table of Contents (TOC)** | Document TOC fields are not automatically generated. | OpenXML TOCs require dynamic field update pagination (`w:fldSimple` / `TOC`), which requires Word runtime pagination. | Implement automated TOC macro injection and post-processing field updates. |
| **Mathematical Equations**| Inline math is rendered as plain text or superscript/subscript notation. | Office MathML (`m:oMath`) requires dedicated LaTeX/MathML-to-OMML conversion pipelines. | Integrate OMML XML generator for MathML inputs. |
| **Client-Side Preview Approximation** | `docx-preview` in the browser provides an approximate view of pagination and complex font conjuncts. | JavaScript DOM rendering engines do not possess the proprietary OpenType shaping and pagination logic of desktop Microsoft Word. | Final layout checks should be validated via DOCX or PDF export. |

