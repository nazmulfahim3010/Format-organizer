// Mirrors backend/app/schemas/*.py

export interface ListItem { text: string; children: ListItem[] }
export interface ParagraphBox { type: "paragraph"; text: string }
export interface ListBox { type: "list"; ordered: boolean; items: ListItem[] }
export interface TableBox {
  type: "table"; caption: string; data: string[][]; header_rows: number; note: string; source: string;
}
export interface FigureBox {
  type: "figure"; asset_id: string | null; caption: string; source: string; src?: string | null;
}
export interface SectionBox { type: "section"; id: string; title: string; content: Box[] }
export type Box = SectionBox | ParagraphBox | ListBox | TableBox | FigureBox;

export interface Author { name: string; affiliation: string; email: string }
export interface DocumentContent {
  schema_version: number; language: string; title: string; subtitle: string;
  authors: Author[]; abstract: string; keywords: string[]; body: Box[];
  fields: Record<string, string>;   // values for the template's {{PLACEHOLDERS}}
}

export interface TableRule {
  label: string; caption_position: "above" | "below"; alignment: "left" | "center" | "right";
  width_percent: number; borders: "all" | "horizontal" | "none" | "template";
  template_style_id: string | null; header_bold: boolean; header_shading: string | null;
  repeat_header: boolean; cell_alignment: "left" | "center" | "right" | "auto";
  wide_table_columns: number; wide_table_font_pt: number; cell_font_pt: number | null;
  note_position: "below"; allow_override: boolean;
}
export interface FigureRule {
  label: string; caption_position: "above" | "below"; alignment: "left" | "center" | "right";
  max_width_percent: number; max_height_cm: number; allow_override: boolean;
}
export interface LanguageSettings {
  code: string; rtl: boolean; complex_script_font: string | null; east_asian_font: string | null;
  set_default_language: boolean; native_digits: boolean;
}
export interface Labels { abstract: string; keywords: string; caption_separator: string; source: string; note: string }
export interface FormattingProfile {
  schema_version: number; name: string; roles: Record<string, string>;
  heading_numbering: "template" | "auto" | "none"; list_mode: "template" | "generated"; keep_template_layout: boolean;
  table: TableRule; figure: FigureRule; language: LanguageSettings; labels: Labels;
  required_sections: string[]; origins: Record<string, string>;
}

export const ROLES: { id: string; label: string }[] = [
  { id: "title", label: "Document title" }, { id: "subtitle", label: "Subtitle" },
  { id: "author", label: "Author block" }, { id: "abstract", label: "Abstract / keywords" },
  { id: "body", label: "Body text" },
  { id: "body_first", label: "First paragraph after a heading" },
  ...Array.from({ length: 9 }, (_, i) => ({ id: `heading_${i + 1}`, label: `Heading level ${i + 1}` })),
  { id: "list_bullet", label: "Bullet list" }, { id: "list_number", label: "Numbered list" },
  { id: "caption", label: "Caption" }, { id: "note", label: "Table/figure note" },
  { id: "table_text", label: "Table cell text" }, { id: "figure", label: "Figure paragraph" },
  { id: "quote", label: "Quote" },
];

export interface StyleInfo {
  id: string; name: string; type: string; used: number; outline_level: number | null;
  resolved: Record<string, string | number | boolean | null>;
}
export interface HealthIssue { code: string; severity: "error" | "warning" | "info"; message: string; hint: string }
export interface Analysis {
  page: { width_cm: number; height_cm: number; orientation: string; columns: number;
          margins_cm: { top: number; bottom: number; left: number; right: number } };
  styles: StyleInfo[];
  suggested_roles: Record<string, string>;
  health: HealthIssue[];
  header_footer: { header_text: string; footer_text: string; footer_has_page_number: boolean };
  language: { text_script: string; default_lang: string | null };
  heading_numbering_in_template: boolean;
  stats: { paragraphs: number; tables: number; sections: number };
}
export interface ProfileOut { id: number; version: number; approved: boolean; rules: FormattingProfile }
export interface TemplateSummary {
  id: number; name: string; versions: number; latest_profile_approved: boolean;
  approved_profile_id: number | null; created_at: string;
}
export interface TemplateDetail {
  id: number; name: string; version: number; template_version_id: number; analysis: Analysis;
  profile: ProfileOut; approved_profile_id: number | null;
}
export interface DocumentSummary {
  id: number; title: string; profile_id: number; updated_at: string;
  template_id: number; template_name: string; template_version: number; profile_version: number;
  latest_profile_id: number | null;
}
export interface ProfileHistoryItem {
  id: number; template_version: number; version: number; approved: boolean; approved_at: string | null;
  created_at: string; rules: FormattingProfile;
}
export interface DocumentDetail extends DocumentSummary { content: DocumentContent; placeholders: string[] }
/** Placeholders SmartDoc fills from the document itself. */
export const BUILTIN_FIELDS: Record<string, string> = {
  TITLE: "Title", SUBTITLE: "Subtitle", AUTHORS: "Authors", ABSTRACT: "Abstract", KEYWORDS: "Keywords",
};
export interface PasteResult {
  boxes: Box[]; title: string; warnings: { code: string; message: string }[]; source_format: string;
}
export interface ValidationCheck {
  id: string; title: string; status: "passed" | "warning" | "failed" | "info" | "manual";
  kind: "auto" | "visual"; details: string[];
}
export interface ValidationReport {
  checks: ValidationCheck[]; summary: Record<string, number>;
  generation_warnings: { code: string; message: string }[];
}

// --- predefined designs (Workflow B) -------------------------------------------------------
export interface Affiliation { id: string; department: string; institution: string; city: string; country: string }
export interface ArticleAuthor { name: string; affiliations: string[]; corresponding: boolean; orcid: string | null }
export interface ArticleMetadata {
  title: string; authors: ArticleAuthor[]; affiliations: Affiliation[]; corresponding_email: string;
  doi: string; volume: string; issue: string; pages: string; year: string;
  received: string; accepted: string; published: string;
}
export interface BackMatter { acknowledgements: string; competing_interests: string; ai_declaration: string; funding: string }
export interface ArticleContent {
  schema_version: number; language: string; metadata: ArticleMetadata; abstract: string; keywords: string[];
  body: Box[]; back_matter: BackMatter; references: string[];
}
export interface DesignSummary { id: string; version: string; name: string; description: string; versions: string[] }
export interface DesignDocumentSummary {
  id: number; title: string; design_id: string; design_version: string; latest_version: string; updated_at: string;
}
export interface DesignDocumentDetail extends DesignDocumentSummary { content: ArticleContent }
