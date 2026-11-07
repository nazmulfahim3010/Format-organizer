# SmartDoc — Automated Template-Driven DOCX Generation Platform

## 1. Executive Summary

**SmartDoc** is an enterprise-grade, deterministic document generation platform that transforms unstructured or semi-structured pasted text into professionally styled Microsoft Word (`.docx`) and Adobe PDF documents. The platform operates on a **template-first paradigm**: users upload any existing `.docx` template (regardless of language, script, or page geometry), and SmartDoc automatically extracts the document’s design DNA (styles, margins, headers, footers, page numbering, themes, and scripts). When new content is authored or pasted into the system, SmartDoc strips out all external source formatting and synthesizes a pristine document that strictly obeys the template’s native styles.

### Core Value Proposition
- **100% Deterministic — Zero Runtime AI:** Unlike AI-based document formatters that suffer from formatting drift, hallucinated typography, non-deterministic layouts, and recurring token costs, SmartDoc employs strict OpenXML (OOXML) tree manipulation algorithms and deterministic heuristics.
- **True Word Fidelity:** Instead of simulating Word features via HTML-to-Word conversions or typed plain text, SmartDoc leverages native Microsoft Word capabilities: dynamic Word `abstractNum`/`numId` numbering definitions, native field codes (`SEQ` fields for captions), real table properties (`tblLook`, `tblBorders`, `bidiVisual`), and proper section properties (`sectPr`).
- **Universal Multi-Script & RTL Support:** Built from the ground up for complex scripts (such as Bengali / Indic scripts) and Right-to-Left (RTL) languages (Arabic, Hebrew, Persian, Urdu), properly managing bidirectional text, font slots (`ascii`, `cs`, `eastAsia`), and mirrored table layouts.
- **Hostile-Input Hardened:** Treats all uploaded `.docx` templates, images, and pasted text as untrusted and potentially malicious, enforcing rigorous anti-exploit, anti-decompression bomb, and strict XML security safeguards before any parsing occurs.

---

## 2. Non-Negotiable Architectural Principles

SmartDoc is governed by strict system invariants that guarantee reproducibility, document integrity, and security:

1. **Template as the Base Document:** The uploaded `.docx` template is never discarded or re-synthesized from scratch. The generator loads the actual template file, strips all paragraphs and tables from its main document body (`w:body`), but strictly preserves the final section properties (`w:sectPr`), document defaults (`w:docDefaults`), style definitions (`w:styles`), numbering schemes (`w:numbering`), relationship mappings (`_rels`), headers, footers, logos, watermarks, and page setup.
2. **Strict Separation of Content and Presentation:**
   - **Content** is represented exclusively as an abstract JSON tree of semantic *Boxes* (`SectionBox`, `ParagraphBox`, `ListBox`, `TableBox`, `FigureBox`). Content models explicitly forbid styling attributes (`extra = "forbid"` in Pydantic); content carries zero fonts, point sizes, margins, or color values.
   - **Presentation** is dictated entirely by a versioned **FormattingProfile**, which maps abstract document roles (`heading_1` through `heading_9`, `body`, `title`, `subtitle`, `caption`, `table_text`, etc.) to specific Word style identifiers found within the template.
3. **Pasted Source Formatting is Discarded:** When content is pasted from Microsoft Word, Google Docs, ChatGPT, websites, or Excel, the normalizer strips away all inline colors, font names, font sizes, margins, and idiosyncratic styling. Only raw structure and intentional inline emphasis (`**bold**`, `*italic*`, `^sup^`, `~sub~`) survive.
4. **Immutability of Approved Profiles:** Formatting profiles undergo an explicit user approval step. Once approved, a `ProfileVersion` database entity is strictly immutable (enforced by SQLAlchemy `before_flush` database hooks). Any subsequent adjustments create a new draft version, ensuring that previously generated documents remain 100% reproducible over time.
5. **Schema-Compliant OOXML Writing:** WordprocessingML demands that XML children appear in an exact sequence dictated by the ISO/IEC 29500 specification. SmartDoc strictly sorts and re-orders all XML children in properties elements (`rPr`, `pPr`, `tblPr`, `tcPr`, `sectPr`) before committing to disk.
6. **No Arbitrary Percentage Validation:** Automated quality checks report categorical statuses (`passed`, `warning`, `failed`, `info`, `manual`) split into automated checks (`auto`) and human visual inspections (`visual`). No meaningless "92% formatting score" is presented to the user.

---

## 3. Technology Stack & System Requirements

| Domain | Technology / Library | Purpose |
| :--- | :--- | :--- |
| **Backend Framework** | Python 3.10+, FastAPI | High-performance asynchronous REST API |
| **Data Validation** | Pydantic v2 (Strict Mode) | Schema definition, JSON serialization, and structural validation |
| **Database & ORM** | SQLAlchemy 2.0, SQLite (WAL Mode) | Persistent transactional storage, relationship mapping, and audit trails |
| **OOXML Engine** | `python-docx`, `lxml` | Parsing, manipulating, and assembling OpenXML packages and XML DOMs |
| **Image Processing** | Pillow (PIL) | Hostile image validation, metadata stripping, EXIF re-orientation, re-encoding |
| **PDF Conversion** | LibreOffice (`soffice`) in headless mode | High-fidelity headless rendering of `.docx` to PDF |
| **PDF Inspection** | PyMuPDF (`fitz`) | Programmatic rasterization and visual inspection of rendered pages |
| **Security & Auth** | `hashlib` (scrypt, sha256), `hmac` | OWASP-compliant password hashing, tamper-proof session tokens |
| **Frontend Framework**| React 18, TypeScript, Vite | Single-page application, responsive user interface |
| **Styling** | Tailwind CSS 3, PostCSS | Utility-first, responsive design |
| **In-Browser Preview**| `docx-preview` | Client-side DOM rendering of real generated `.docx` binary blobs |

---

## 4. High-Level Architecture & End-to-End Workflow

```
+----------------------------------------------------------------------------------------------------+
|                                         SMARTDOC WORKFLOW                                          |
+----------------------------------------------------------------------------------------------------+

 [ User Uploads .docx Template ]
                |
                v
 [ Pre-Ingestion Security Checks ] (ZIP bomb check, macro check, XXE/DTD check, external rels check)
                |
                v
 [ Template Analyzer (ooxml.py & analyzer.py) ]
    ├── Resolves font inheritance, themes, docDefaults, and basedOn chains
    ├── Detects roles (Title, Body, Heading 1..9, Captions, Lists, Tables)
    ├── Detects language, script, RTL flags, and margin geometries
    └── Generates default FormattingProfile (Draft)
                |
                v
 [ Profile Review & Approval ] (User reviews mapping -> Approves -> ProfileVersion locked)
                |
                +-------------------------------+
                                                |
 [ Content Ingestion ]                          |
    ├── Paste from Word / Docs / Web / Excel    |
    ├── Paste Normalizer (normalizer.py)        |
    │     ├── Strips colors, fonts, sizes       |
    │     ├── Extracts tables, lists, captions  |
    │     └── Preserves inline **b**, *i*, ^s^  |
    └── Box-Tree Content Model (content.py)     |
                |                               |
                +---------------+---------------+
                                |
                                v
               [ Document Engine Generator (generator.py) ]
                  ├── Clears template body; preserves sectPr, headers, footers
                  ├── Injects Box tree mapped to approved template styles
                  ├── Links heading levels to native numbering lists
                  ├── Injects dynamic SEQ fields for Table & Figure captions
                  ├── Handles complex scripts (bidi, bidiVisual, cs/eastAsia fonts)
                  └── Sorts XML nodes in ISO schema order
                                |
                +---------------+---------------+
                |                               |
                v                               v
    [ In-Browser Preview ]            [ Quality Validator ]
    (docx-preview DOM render)         (30+ automated checks: headings,
                                       captions, XML order, table fit)
                |                               |
                +---------------+---------------+
                                |
                                v
                   [ Output Generation / Export ]
                      ├── Download Formatted .docx
                      └── Headless LibreOffice Export -> Download PDF
```

---

## 5. Detailed Directory Structure

```text
project_for_automated_docx formated/
├── .vscode/                               # Editor configuration
├── CLAUDE.md                              # Non-negotiable design rules and working principles
├── PLAN.md                                # Phase-by-phase implementation and verification audit
├── README.md                              # Project setup, quickstart, and known limitations
├── desq.md                                # Comprehensive project description (this document)
│
├── backend/                               # Python FastAPI backend
│   ├── pytest.ini                         # Pytest configuration and test path setup
│   ├── requirements.txt                   # Backend Python dependencies
│   │
│   ├── app/                               # Core backend application package
│   │   ├── __init__.py
│   │   ├── config.py                      # Global application settings & env variables
│   │   ├── main.py                        # FastAPI application instance, CORS, routes & SPA mount
│   │   │
│   │   ├── api/                           # REST API layer
│   │   │   ├── __init__.py
│   │   │   ├── deps.py                    # Dependencies: auth, db session, rate limits, ownership
│   │   │   └── routes/                    # API route controllers
│   │   │       ├── __init__.py
│   │   │       ├── auth.py                # User registration, login (scrypt + timing safety), /me
│   │   │       ├── documents.py           # Document CRUD, content updates, generate, preview, PDF
│   │   │       ├── media.py               # Image upload, sanitization, asset retrieval
│   │   │       ├── paste.py               # Clipboard content normalization endpoint
│   │   │       └── templates.py           # Template upload, analysis, profile management, approval
│   │   │
│   │   ├── core/                          # Security, utilities, and parsing primitives
│   │   │   ├── __init__.py
│   │   │   ├── inline.py                  # Custom inline markup parser & serializer (bold/italic/etc.)
│   │   │   ├── ratelimit.py               # In-memory thread-safe sliding window rate limiter
│   │   │   ├── security.py                # Scrypt hashing, HMAC token issuance & verification
│   │   │   └── uploads.py                 # Hostile upload detection, ZIP bomb & XML bomb protection
│   │   │
│   │   ├── database/                      # Persistence layer
│   │   │   ├── __init__.py
│   │   │   └── session.py                 # SQLite configuration (WAL mode, busy timeout, foreign keys)
│   │   │
│   │   ├── document_engine/               # OpenXML generation & PDF compilation
│   │   │   ├── __init__.py
│   │   │   ├── generator.py               # Deterministic OOXML document assembler
│   │   │   ├── pdf.py                     # Headless LibreOffice PDF converter with timeout/sandbox
│   │   │   └── sample.py                  # Sample document tree generator for template testing
│   │   │
│   │   ├── models/                        # SQLAlchemy database models
│   │   │   ├── __init__.py
│   │   │   └── db.py                      # User, Template, TemplateVersion, ProfileVersion, Document
│   │   │
│   │   ├── paste/                         # Clipboard normalizer engine
│   │   │   ├── __init__.py
│   │   │   └── normalizer.py              # HTML/MD/Plaintext parser into clean semantic Box trees
│   │   │
│   │   ├── schemas/                       # Pydantic validation schemas
│   │   │   ├── __init__.py
│   │   │   ├── api.py                     # Request/response DTOs for REST endpoints
│   │   │   ├── content.py                 # Strict Box content model (Section, Paragraph, List, etc.)
│   │   │   └── profile.py                 # FormattingProfile model (roles, tables, figures, rules)
│   │   │
│   │   ├── services/                      # Application business logic services
│   │   │   ├── __init__.py
│   │   │   ├── documents.py               # Generation orchestration and context loaders
│   │   │   ├── profiles.py                # Profile migration, diffing, user-edit provenance tracking
│   │   │   └── storage.py                 # Filesystem asset management with quiet cleanup
│   │   │
│   │   └── validation/                    # Document quality inspection
│   │       ├── __init__.py
│   │       └── validator.py               # Structural and visual QA verification engine
│   │
│   ├── scripts/                           # Maintenance and development scripts
│   │   └── render.py                      # Multi-fixture rendering tool (DOCX -> PDF -> PNG per page)
│   │
│   ├── storage/                           # Persistent file storage (templates, media, generated files)
│   │   └── smartdoc.db                    # Primary SQLite database
│   │
│   └── tests/                             # Comprehensive test suite (385+ tests)
│       ├── __init__.py
│       ├── api_helpers.py                 # Test client fixtures and helper wrappers
│       ├── conftest.py                    # Pytest environment isolation setup
│       ├── make_attacks.py                # Generator for hostile test files (ZIP bombs, XXE, macros)
│       ├── make_templates.py              # Generator for standard fixture templates
│       ├── sample.py                      # Test fixture generators and dummy content
│       ├── test_analyzer.py               # Tests for style resolver and template analyzer
│       ├── test_api.py                    # API route authentication and lifecycle tests
│       ├── test_api_versions.py           # Immutability and versioning API tests
│       ├── test_attacks.py                # Security & hostile upload defense verification
│       ├── test_engine.py                 # Document engine unit tests
│       ├── test_fixtures.py               # Template fixture integrity tests
│       ├── test_generator.py              # OOXML generator tests (lists, captions, scripts, margins)
│       ├── test_inline_and_paste.py       # Inline markup & paste normalizer tests
│       ├── test_paste_samples.py          # Real-world paste samples (Word, GDocs, Excel, Bangla)
│       ├── test_pipeline.py               # End-to-end integration tests (paste -> generate -> PDF)
│       ├── test_profiles.py               # Profile logic and inheritance tests
│       ├── test_schemas_inline.py         # Pydantic schema validation tests
│       ├── test_security.py               # Cryptography, tokens, and rate limiter tests
│       ├── test_validator.py              # Validator rule verification tests
│       ├── fixtures/                      # Pre-compiled .docx test templates
│       └── paste_samples/                 # Sample raw inputs (HTML, TSV, Markdown, Bangla)
│
└── frontend/                              # React 18 TypeScript frontend
    ├── index.html                         # SPA HTML entry point
    ├── package.json                       # Frontend dependencies & npm scripts
    ├── postcss.config.js                  # PostCSS configuration
    ├── tailwind.config.js                 # Tailwind CSS theme configuration
    ├── tsconfig.json                      # TypeScript compiler options
    ├── vite.config.ts                     # Vite build & development proxy configuration
    │
    └── src/                               # Application source code
        ├── App.tsx                        # Main application shell with hash-based router
        ├── api.ts                         # REST API fetch client with token handling
        ├── index.css                      # Global Tailwind styles & utility classes
        ├── main.tsx                       # React application root DOM mount
        ├── ops.ts                         # Immutable Box-tree operations (insert, move, nest, wrap)
        ├── types.ts                       # TypeScript interfaces mirroring backend Pydantic schemas
        ├── vite-env.d.ts                  # Vite environment typings
        │
        ├── components/                    # Reusable UI components
        │   ├── BoxEditor.tsx              # Recursive box-tree content editor
        │   ├── PasteZone.tsx              # Clipboard ingestion zone with source analysis
        │   ├── PreviewPane.tsx            # In-browser live DOCX viewer using `docx-preview`
        │   ├── TableGrid.tsx              # Interactive spreadsheet-like visual table editor
        │   └── ValidationPanel.tsx        # Document QA validation report checklist UI
        │
        └── pages/                         # Application page views
            ├── DocumentEditor.tsx         # Complete document authoring, preview, & export view
            ├── Documents.tsx              # User document dashboard and creation modal
            ├── Login.tsx                  # Authentication view (Sign In / Register)
            ├── TemplateEditor.tsx         # Template inspection, style mapping, & profile approval
            └── Templates.tsx              # Template manager and upload interface
```

---

## 6. Detailed Component & Subsystem Breakdown

### 6.1. Template Engine & Style Resolver (`backend/app/template_engine/`)

The Template Engine is responsible for deeply analyzing any `.docx` file uploaded by a user.
- **`ooxml.py` (Low-Level OOXML Parser):**
  - **StyleResolver:** Traverses Word’s complex inheritance hierarchy (`basedOn` chains) and parses `w:docDefaults` and `w:theme` font schemes to determine the true computed properties of any style (including primary font, font size, line spacing, paragraph alignment, indents, and outline levels).
  - **Multi-Script Font Resolution:** OpenXML styles define fonts across four separate slots: `w:ascii` (Latin), `w:hAnsi` (High ANSI), `w:eastAsia` (CJK), and `w:cs` (Complex Scripts like Arabic, Hebrew, Bengali, Devanagari). The resolver evaluates them per slot and inspects `w:themeFontLang` and script mappings.
  - **Theme Resolution:** Resolves theme references (e.g., `majorFont`, `minorFont`, `w:cstheme`) to actual typeface names by parsing the template's embedded `/word/theme/theme1.xml` file.
  - **Cycle & Error Detection:** Detects circular `basedOn` inheritance loops (`STYLE_CYCLE`), missing abstract numbering links (`BROKEN_NUMBERING`), and inherited first-line indents.
- **`analyzer.py` (High-Level Style & Layout Classifier):**
  - **Role Heuristics:** Maps template styles to canonical roles (`title`, `subtitle`, `heading_1`–`heading_9`, `body`, `caption`, `quote`, `list_bullet`, `list_number`, `table_text`). It utilizes a multi-lingual semantic keyword dictionary covering English, French, German, Spanish, Italian, Russian, Chinese, Japanese, Arabic, and Bengali.
  - **Outline Level Priority:** Explicit Word outline levels (`w:outlineLvl`) take precedence over style names for heading classification.
  - **Geometry & Page Layout Detection:** Extracts page width, page height, margins, gutter, header/footer distances, column counts, column spacing, and section orientation.
  - **Header & Footer Inspection:** Inspects default, first-page, and even-page header/footer parts, checking for dynamic page number fields (`w:fldSimple` or `PAGE` / `NUMPAGES`).
  - **Profile Synthesis (`build_default_profile`):** Assembles a draft `FormattingProfile` populated with discovered rules, assigning an origin (`template`, `inferred`, or `default`) to every single setting.

---

### 6.2. Document Generator Engine (`backend/app/document_engine/`)

The Document Generator (`generator.py`) is the core synthesis engine.
- **Preservation of the Structural Skeleton:**
  - Loads the uploaded template `.docx` using `python-docx` / `lxml`.
  - Clears all child paragraphs and tables inside the document body (`w:body`), leaving the trailing `w:sectPr` untouched.
  - Retains all header and footer parts, numbering definitions, media assets, custom themes, and document settings.
- **Native Word Numbering Schemes:**
  - **Heading Numbering:** Connects headings to a native Word multilevel list. When template numbering is absent or single-level, it generates an ISO-compliant multilevel numbering definition linked directly to the mapped heading styles.
  - **List Restart & Hierarchy:** When nested lists occur, the engine injects new abstract number definitions (`_complete_abstract`) to ensure that sub-items (e.g., bullets `•`, `–`, `▪` or numbers `1.`, `a.`, `i.`) indent and restart properly without bleeding across unrelated sections.
- **Dynamic Field Code Captions (`SEQ` Fields):**
  - Captions for Tables and Figures do not contain hardcoded, static numbers. Instead, SmartDoc emits standard Word `SEQ` field instructions (e.g., `SEQ Table \* ARABIC` or `SEQ Figure \* ARABIC`), followed by a cached numeric run. When opened in Microsoft Word, Word dynamically maintains and recalculates the sequence numbers.
  - In languages configured for native digits (e.g., Bengali, Arabic), the cached display digit is rendered in native numerals (১, ۲).
- **Complex Script & Bidirectional (Bidi) Engine:**
  - Splits text runs based on script transitions using Unicode block classification.
  - Sets appropriate script tags: `w:rtl` for right-to-left runs, `w:cs` for complex script characters, and applies `w:bCs` (bold CS), `w:iCs` (italic CS), and `w:szCs` (font size CS) to ensure typography renders identically across Word and LibreOffice.
  - Automatically marks tables with `w:bidiVisual` in RTL contexts so columns order correctly from right to left.
- **OOXML Schema Ordering Enforcement:**
  - Word documents frequently corrupt if XML tags violate schema ordering. The generator strictly sorts children in:
    - `w:rPr` (`rStyle` -> `rFonts` -> `b` -> `bCs` -> `i` -> `iCs` -> `color` -> `sz` -> `szCs` -> `rtl` -> `cs` -> `lang`)
    - `w:pPr` (`pStyle` -> `keepNext` -> `numPr` -> `bidi` -> `spacing` -> `ind` -> `jc` -> `outlineLvl` -> `rPr`)
    - `w:tblPr` (`tblStyle` -> `bidiVisual` -> `tblW` -> `jc` -> `tblBorders` -> `shd` -> `tblLayout` -> `tblLook`)
    - `w:sectPr` (`headerReference` -> `footerReference` -> `pgSz` -> `pgMar` -> `cols` -> `bidi` -> `docGrid`)
- **Table & Figure Sizing Heuristics:**
  - Tables automatically adapt to document columns. In multi-column layouts, table widths and figure bounding boxes are clamped to the narrowest text column to prevent overflow.
  - Figure images are proportionally scaled, strictly bounding them to 85% of the printable page height to prevent captions from being pushed onto blank orphan pages.

---

### 6.3. Content Ingestion & Normalizer (`backend/app/paste/`)

The normalizer (`normalizer.py`) processes messy clipboard data:
- **Clipboard Source Discrimination:** Accepts HTML (Word HTML, Google Docs HTML, web pages), GitHub/ChatGPT-flavored Markdown, tab-separated values (TSV), and unformatted plain text.
- **Total De-Styling:** Strips away all CSS classes (`MsoNormal`), explicit font faces (`font-family: Arial`), inline font sizes (`font-size: 11pt`), colors, background tints, and line-heights.
- **Structural Reconstruction:**
  - **Headings:** Deduces hierarchy from HTML heading tags (`<h1>`–`<h6>`), outline levels, markdown hashes (`#`), or typed numbering conventions (`1.1 Introduction`, `১.১ ভূমিকা`).
  - **Lists:** Deduces lists from `<ul>`/`<ol>`, HTML `mso-list` attributes, Google Docs `aria-level` spans, and typed bullet markers (`•`, `-`, `*`) or typed numbering (`1.`, `a)`, `(i)`).
  - **Tables:** Parses HTML tables or tab-separated Excel data. Handles multiline quoted CSV cells correctly via Python’s `csv` module and splits or normalizes merged cells.
  - **Captions & Citations:** Detects caption patterns (`Table 1: Description`, `চিত্র ২: ফলাফল`) and re-associates them with the corresponding table or figure box, removing the hardcoded label so the document generator can inject dynamic `SEQ` fields. Separates trailing `Source:` and `Note:` lines into structured metadata fields.
  - **Pasted Images:** Automatically extracts inline `data:image/...;base64` URIs, assigns pending asset IDs, and routes them to the media storage service for validation and sanitization.

---

### 6.4. Inline Text Syntax & Tokenizer (`backend/app/core/inline.py`)

SmartDoc represents inline formatting via an unambiguous, lightweight escaping notation:
- `**text**` -> **Bold**
- `*text*` -> *Italic*
- `^text^` -> ^Superscript^
- `~text~` -> ~Subscript~
- `\ ` or `\*` -> Literal backslash-escaped characters

**Engine Highlights:**
- **Boundary Precision:** Prevents false-positive formatting in ordinary prose (e.g., `2 * 3 * 4` or `~5 to ~10 km` are preserved as raw math/symbols, not parsed as italics or subscript).
- **Whitespace Normalization:** Leading and trailing whitespace inside delimiters (`** bold **`) is trimmed from styling runs and restored to normal text.
- **Fuzz-Tested Round-Tripping:** Validated against thousands of randomized permutations ensuring that `parse_inline(serialize_runs(runs)) == runs`.

---

### 6.5. Comprehensive Quality Validator (`backend/app/validation/validator.py`)

The validator performs 30+ automated and visual quality checks against the generated `.docx` file and the active `FormattingProfile`:

| Check Category | Validation Logic |
| :--- | :--- |
| **Page Setup** | Verifies that page dimensions, margins, and column counts match the approved template. |
| **Header & Footer** | Ensures default, first-page, and even-page headers/footers were preserved and dynamic page numbering survives. |
| **Heading Hierarchy** | Detects skipped heading levels (e.g., Heading 1 directly followed by Heading 3 without a Heading 2). |
| **Heading Numbering** | Verifies that all heading numbering links to valid `numId` records in the numbering part. |
| **Typed Numbering** | Scans for duplicate typed numbering (e.g., a user manually typing "1. Introduction" inside a style already numbered by Word). |
| **Captions & SEQ** | Verifies that all table and figure captions utilize valid Word `SEQ` fields and sequential numeric ordering. |
| **Table Fit** | Calculates table geometry in twips and confirms that total table width does not overflow the column width. |
| **Figure Fit** | Confirms image aspect ratios and verifies that figures do not exceed 85% of the printable vertical page height. |
| **Complex Script QA**| Confirms that complex-script runs possess appropriate `w:cs` fonts and `w:rtl` markers, and that RTL tables have `w:bidiVisual`. |
| **XML Schema Order** | Scans raw XML across `document.xml`, `styles.xml`, and `numbering.xml` to verify strict ISO tag ordering. |
| **Direct Formatting**| Audits paragraph and run elements to guarantee no rogue inline fonts or sizes bypassed the profile rules. |
| **Manual Visual Checks** | Flags items that require human eyes (e.g., visual script font rendering, page break aesthetics). |

---

### 6.6. Security, Hardening & Attack Defense (`backend/app/core/uploads.py`, `security.py`, `ratelimit.py`)

SmartDoc enforces zero-trust handling on all incoming user inputs:

1. **Pre-Parse ZIP Bomb & Quota Checks:**
   - Word `.docx` files are ZIP packages. The upload inspector examines magic bytes (`PK\x03\x04`) and streams files through an uncompressed size budget (`MAX_UNCOMPRESSED_BYTES = 150 MB`).
   - Rejects compression ratios exceeding 200:1, files with more than 3,000 ZIP entries, and duplicate file entry names.
2. **Malicious Content & Macro Stripping:**
   - Rejects any archive containing VBA macros (`vbaProject.bin`, `vbaData.xml`), ActiveX objects (`/activeX/`), VBScript (`.vbs`), or legacy OLE storage packages.
   - Refuses dangerous Word field instructions: `DDE`, `DDEAUTO`, `INCLUDEPICTURE`, `INCLUDETEXT`, `LINK`, and `IMPORT`.
3. **XXE & Entity Expansion Defense:**
   - All XML parts are parsed using an isolated parser (`_SAFE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)`).
   - Scans raw XML bytes and decoded UTF-16 streams for `<!DOCTYPE` or `<!ENTITY` injection attacks.
4. **External Relationship Blocking:**
   - Parses `_rels/.rels` and all part relationships. Rejects any `TargetMode="External"` reference (e.g., remote attached templates or external frames) with the sole exception of standard web hyperlinks (`http://`, `https://`). This completely prevents SSRF during server-side LibreOffice rendering.
5. **Image Sanitization:**
   - Images are read via Pillow, orientation-corrected based on EXIF, stripped of all metadata, comments, and trailing payloads, and re-encoded into clean PNG or JPEG formats.
6. **Authentication & Password Hardening:**
   - Passwords hashed using **scrypt** with OWASP-recommended parameters: $N = 2^{17} (131,072)$, $r = 8$, $p = 1$.
   - Constant-time dummy hashing (`burn_time`) is performed on non-existent accounts to eliminate timing-attack user enumeration.
   - Session tokens are HMAC-SHA256 signed with embedded expiration timestamps.
7. **Sliding-Window Rate Limiting:**
   - Thread-safe, sliding-window rate limiters prevent brute-force sign-in attempts (10/min per account, 50/min per IP) and protect compute-heavy operations (60/min for template uploads, paste normalization, and document rendering).

---

### 6.7. PDF Export Engine & Sandboxing (`backend/app/document_engine/pdf.py`)

To convert `.docx` to PDF:
- Invokes LibreOffice (`soffice.exe` / `soffice`) in headless mode: `--headless --convert-to pdf --nologo --nodefault --nolockcheck`.
- **Isolated User Profiles:** Every conversion runs with an isolated, temporary throwaway user installation directory (`-env:UserInstallation=file://...`), preventing cross-request state leakage, macro persistence, or cache contamination.
- **Process Group Isolation & Timeout:** Executed within its own OS process group. If the process does not terminate within the configured timeout (e.g., 150 seconds), the entire process tree is forcefully terminated (`taskkill /T /F` on Windows; `killpg` on POSIX).
- **Environment Scrubbing:** Strips unnecessary environment variables, passing only essential OS runtime keys (`SYSTEMROOT`, `TEMP`, `TMP`).

---

### 6.8. Frontend Web Application (`frontend/src/`)

The frontend is a modern, responsive Single Page Application built with React 18, Vite, TypeScript, and Tailwind CSS.
- **State Management & Routing:**
  - Lightweight, dependency-free hash router (`#/documents`, `#/documents/:id`, `#/templates`, `#/templates/:id`).
  - Autosave architecture: Changes made to document content in `DocumentEditor.tsx` trigger a debounced (900ms) background PUT request, automatically followed by an async live preview refresh.
- **`BoxEditor.tsx` (Recursive Content Tree Editor):**
  - Renders the hierarchical tree of boxes. Sections can be nested recursively up to 20 levels deep.
  - Provides controls to re-order boxes (↑ / ↓), indent into the preceding section (⇥), outdent to the parent section (⇤), or delete.
  - Contextual action bar for inline formatting (`**Bold**`, `*Italic*`, `^Superscript^`, `~Subscript~`).
- **`PasteZone.tsx` (Smart Clipboard Ingestion):**
  - Intercepts paste events (`Ctrl+V` / `⌘V`), captures both `text/html` and `text/plain` payloads from the clipboard, and dispatches them to `/api/paste/normalize`.
  - Displays a summary of detected sections, tables, and figures, allowing users to insert parsed content at the root or within any existing section.
- **`PreviewPane.tsx` (In-Browser Live Viewer):**
  - Integrates `docx-preview` to render real generated `.docx` binary blobs directly into an HTML5 Canvas / DOM container inside the browser.
  - Renders headers, footers, pagination, and tables in real time without leaving the page.
- **`TableGrid.tsx` (Interactive Table Editor):**
  - A spreadsheet-like grid enabling users to add/delete rows and columns, edit cell values, configure header rows, and assign captions, sources, and notes.
- **`ValidationPanel.tsx` (QA Checklist UI):**
  - Renders the real-time checklist of validation results, color-coding passed, warning, failed, info, and visual check items.
- **`TemplateEditor.tsx` (Style Mapping & Approval Console):**
  - Presents a complete visual inventory of all styles discovered in the uploaded `.docx` template.
  - Allows administrators and users to map detected styles to document roles, set caption positions and labels, configure table borders/shading, inspect template health warnings, and execute formal profile approvals.

---

## 7. Data Models & Database Schemas

The database schema is defined in `backend/app/models/db.py` using SQLAlchemy 2.0:

```
+-----------------------------------------------------------------------------------+
|                                  DATABASE SCHEMA                                  |
+-----------------------------------------------------------------------------------+

       +-------------------------+
       |          User           |
       +-------------------------+
       | id: int (PK)            |
       | email: str (Unique)     |
       | name: str               |
       | password_hash: str      |
       | created_at: datetime    |
       +-------------------------+
                    | 1
                    |
                    | *
       +-------------------------+               +-------------------------+
       |        Template         | 1           * |     TemplateVersion     |
       +-------------------------+---------------+-------------------------+
       | id: int (PK)            |               | id: int (PK)            |
       | owner_id: int (FK User) |               | template_id: int (FK)   |
       | name: str               |               | version: int            |
       | created_at: datetime    |               | file_path: str          |
       +-------------------------+               | sha256: str             |
                                                 | analysis: JSON          |
                                                 | created_at: datetime    |
                                                 +-------------------------+
                                                              | 1
                                                              |
                                                              | *
       +-------------------------+               +-------------------------+
       |        Document         | *           1 |     ProfileVersion      |
       +-------------------------+---------------+-------------------------+
       | id: int (PK)            |               | id: int (PK)            |
       | owner_id: int (FK User) |               | template_version_id (FK)|
       | title: str              |               | version: int            |
       | profile_version_id (FK) |               | rules: JSON (Profile)   |
       | content: JSON (Boxes)   |               | approved: bool          |
       | created_at: datetime    |               | approved_at: datetime   |
       | updated_at: datetime    |               +-------------------------+
       +-------------------------+                            | 1
                    | 1                                       |
                    |                                         |
                    | *                                       | *
       +-------------------------+               +-------------------------+
       |      GeneratedFile      |               |    ValidationReport     |
       +-------------------------+               +-------------------------+
       | id: int (PK)            |               | id: int (PK)            |
       | document_id: int (FK)   |               | document_id: int (FK)   |
       | profile_version_id (FK) |               | profile_version_id (FK) |
       | path: str               |               | checks: JSON            |
       | warnings: JSON          |               | summary: JSON           |
       | created_at: datetime    |               | created_at: datetime    |
       +-------------------------+               +-------------------------+
```

### Profile Immutability Guarantee
When `ProfileVersion.approved` becomes `True`, the SQLAlchemy `@event.listens_for(Session, "before_flush")` hook locks the row against modifications or deletions. If any code attempts to alter `rules`, `approved`, or foreign keys on an approved profile, an `ImmutableVersionError` is thrown, guaranteeing historical document reproducibility.

---

## 8. Supported Document Features & Capabilities

- **Arbitrary Document Roles:** Full classification and mapping of Title, Subtitle, Author, Abstract, Headings (Levels 1–9), Body text, Blockquotes, Captions, Bullet Lists, Numbered Lists, Table Text, and Notes.
- **Multilevel Heading Numbering:** Automatic generation and linking of multilevel heading hierarchies (e.g., `1.`, `1.1`, `1.1.1`) conforming to Word’s native numbering schema.
- **Dynamic Captions:** Real Word `SEQ` fields for Table and Figure captions with configurable position (above or below), custom labels (e.g., *Table*, *Figure*, *চিত্র*, *جدول*), and custom separators (`: `, ` - `).
- **Table Styling:** Full control over table borders (`all`, `horizontal`, `none`, `template`), header row shading (hex color), bold headers, automatic header row repetition across page breaks (`w:tblHeader`), cell alignment, and automatic font scaling for wide tables (7+ columns).
- **Figure & Image Management:** Automatic proportional scaling, max-width/max-height constraints, caption placement, and source attribution lines.
- **Complex Scripts & Internationalization:**
  - Full support for Latin, Cyrillic, Arabic, Hebrew, Bengali, Devanagari, and CJK text.
  - Native numeral rendering in captions for Arabic-Indic and Bengali digits (`১`, `২`, `۳`).
  - Right-to-Left (RTL) paragraph direction and `bidiVisual` table column inversion.
- **Multi-Column Layout Awareness:** Automatic column count and spacing detection; table and image widths automatically conform to individual column boundaries.

---

## 9. Verification & Testing Framework

SmartDoc maintains an automated test suite comprising **385+ tests** covering all subsystems:

```text
backend/tests/
├── test_analyzer.py          # StyleResolver, inheritance, theme resolution, language detection
├── test_generator.py         # OOXML generation, sectPr preservation, SEQ captions, bidi tables
├── test_schemas_inline.py    # Strict Pydantic models, inline markup escaping and round-tripping
├── test_inline_and_paste.py  # Fuzz-tested inline parser, paste normalizer edge cases
├── test_paste_samples.py     # Real-world paste data (Word HTML, Google Docs, Excel, ChatGPT)
├── test_validator.py         # Validation checks, intentional error injection tests
├── test_security.py          # Scrypt password hashing, rate limiting, HMAC tokens
├── test_attacks.py           # Hostile upload defense (28 attack vectors: ZIP bombs, XXE, macros)
├── test_api.py               # REST API endpoints, auth lifecycle, document CRUD
├── test_api_versions.py      # Profile immutability, draft branching, version upgrades
└── test_pipeline.py          # Full integration: Paste -> Normalize -> Generate -> Validate -> PDF
```

### Visual Verification Pipeline (`backend/scripts/render.py`)
Rather than relying solely on XML inspection, SmartDoc includes a visual rendering pipeline:
1. Synthesizes documents across 6 fixture templates (`default`, `university`, `messy`, `bangla`, `twocol`, `rtl`).
2. Compiles `.docx` into `.pdf` using headless LibreOffice.
3. Rasterizes PDF pages into high-resolution PNG images via PyMuPDF (`fitz`).
4. Allows automated and human visual verification of complex script conjuncts, table borders, margin alignments, and soft line-break behaviors.

---

## 10. Operational Setup & Deployment Guide

### 10.1. Environment Variables

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `SMARTDOC_ENV` | `development` | Set to `production` in production mode |
| `SMARTDOC_SECRET` | `dev-secret-change-me` | Secret key for HMAC token signing (>= 32 chars required in prod) |
| `SMARTDOC_DATA_DIR` | `backend/storage` | Root directory for templates, media, and generated files |
| `SMARTDOC_DATABASE_URL`| `sqlite:///<DATA_DIR>/smartdoc.db`| SQLAlchemy database connection string |
| `SMARTDOC_CORS_ORIGINS`| `http://localhost:5173` | Comma-separated list of allowed CORS origin URLs |
| `SMARTDOC_ALLOW_REGISTRATION` | `1` | `1` to allow open registration, `0` to close |
| `SMARTDOC_SOFFICE` | Auto-detected | Path to the LibreOffice `soffice` executable |
| `SMARTDOC_KEEP_GENERATED_FILES` | `20` | Max generated historical files retained per document |

### 10.2. Running the Backend

```bash
cd backend
python -m venv .venv
# Activate virtual environment (Windows: .venv\Scripts\activate; POSIX: source .venv/bin/activate)
pip install -r requirements.txt
export SMARTDOC_SECRET="your-secure-random-32-character-secret-key"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 10.3. Running the Frontend

```bash
cd frontend
npm install
npm run dev      # Starts Vite dev server with proxy to http://localhost:8000
npm run build    # Produces optimized production bundle in frontend/dist
```

*Note: In production, the FastAPI backend automatically serves the compiled `frontend/dist` directory as a static SPA if present.*

---

## 11. Known Limitations & Roadmap

1. **Native Digits in LibreOffice PDF:** While native script digits (e.g., Bengali `১`, `২`, `৩`) are correctly written to the cached SEQ runs in the `.docx` XML, LibreOffice dynamically recalculates SEQ fields during PDF conversion and falls back to Arabic/Latin numerals (`1, 2, 3`). Word preserves native digits.
2. **Merged Table Cells:** Complex cell merges (rowspan/colspan) from pasted inputs are currently split into rectangular grids with empty fill cells to guarantee strict table width alignment.
3. **Advanced Publishing Elements (Planned Roadmap):**
   - Automated Table of Contents (`w:sdt` TOC fields)
   - Native MathML / OMML Equation support
   - Bibliographic reference and citation management
4. **Client-Side Preview Fidelity:** `docx-preview` in the browser provides an approximate layout preview. Exact pagination and font shaping should always be verified by downloading the final `.docx` or exported PDF.

