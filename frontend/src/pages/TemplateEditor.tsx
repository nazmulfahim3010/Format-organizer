import { useEffect, useRef, useState } from "react";
import { api, blobOf, post, put, upload } from "../api";
import PreviewPane from "../components/PreviewPane";
import { FormattingProfile, ProfileHistoryItem, ROLES, StyleInfo, TemplateDetail } from "../types";

const SEV: Record<string, string> = {
  error: "bg-red-100 text-red-800", warning: "bg-amber-100 text-amber-800", info: "bg-slate-100 text-slate-700",
};
const ORIGIN: Record<string, string> = {
  template: "from template", inferred: "inferred", default: "default", user: "edited by you",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block"><span className="label">{label}</span>{children}</label>;
}

/** Hex colour box: the rule only changes on an empty value or 6 hex digits (the server refuses partial values). */
function HexInput({ value, onChange }: { value: string | null; onChange: (v: string | null) => void }) {
  const [text, setText] = useState(value ?? "");
  useEffect(() => setText(value ?? ""), [value]);
  const ok = text === "" || /^[0-9A-F]{6}$/.test(text);
  return (
    <>
      <input className={`input ${ok ? "" : "!border-amber-500"}`} maxLength={6} value={text} placeholder="e.g. D9D9D9"
        onChange={(e) => {
          const v = e.target.value.replace(/[^0-9a-fA-F]/g, "").toUpperCase();
          setText(v);
          if (v === "" || v.length === 6) onChange(v || null);
        }} />
      {!ok && <span className="text-[11px] text-amber-700">Enter 6 hex digits (or leave empty for no shading).</span>}
    </>
  );
}

function describe(s: StyleInfo): string {
  const r = s.resolved;
  const bits = [r.font, r.size_pt ? `${r.size_pt}pt` : null, r.bold ? "bold" : null, r.italic ? "italic" : null].filter(Boolean);
  return `${s.name}${bits.length ? " — " + bits.join(" ") : ""}${s.used ? ` (used ${s.used}×)` : ""}`;
}

export default function TemplateEditor({ id }: { id: number }) {
  const [t, setT] = useState<TemplateDetail | null>(null);
  const [rules, setRules] = useState<FormattingProfile | null>(null);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [busy, setBusy] = useState(false);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const newVer = useRef<HTMLInputElement>(null);

  const [history, setHistory] = useState<ProfileHistoryItem[]>([]);
  const loadHistory = () => api<ProfileHistoryItem[]>(`/api/templates/${id}/profiles`).then(setHistory).catch(() => undefined);
  const load = async () => {
    const d = await api<TemplateDetail>(`/api/templates/${id}`);
    setT(d); setRules(d.profile.rules); setDirty(false);
    void loadHistory();
  };
  useEffect(() => { load().catch((e) => setMsg({ kind: "err", text: e.message })); }, [id]);
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  if (!t || !rules) return <p className="text-sm text-slate-500">{msg ? msg.text : "Loading…"}</p>;

  const edit = (fn: (r: FormattingProfile) => void, origin?: string) => {
    const next: FormattingProfile = JSON.parse(JSON.stringify(rules));
    fn(next);
    if (origin) next.origins[origin] = "user";
    setRules(next); setDirty(true); setMsg(null);
  };

  const save = async () => {
    const r = await put<{ id: number; version: number; approved: boolean; rules: FormattingProfile }>(`/api/templates/${id}/rules`, rules);
    setT({ ...t, profile: r });
    setRules(r.rules);           // the server decides origins ("edited by you")
    setDirty(false);
    void loadHistory();
  };

  const preview = async () => {
    setBusy(true); setPreviewErr(null);
    try { await save(); setBlob(await blobOf(`/api/templates/${id}/sample`)); }
    catch (e) { setPreviewErr((e as Error).message); }
    finally { setBusy(false); }
  };

  const approve = async () => {
    setMsg(null);
    try {
      await save();
      const r = await post<{ version: number }>(`/api/templates/${id}/approve`);
      setMsg({ kind: "ok", text: `Approved as version ${r.version}. You can now create documents with this template.` });
      await load();
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  };

  const newVersion = async (f: File | undefined) => {
    if (!f) return;
    try {
      const d = await upload<TemplateDetail>(`/api/templates/${id}/versions`, f);
      setT(d); setRules(d.profile.rules); setDirty(false); void loadHistory();
      setMsg({ kind: "ok", text: `Template version ${d.version} uploaded. Your rules were carried over as a draft; review and approve them.` });
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
    if (newVer.current) newVer.current.value = "";
  };

  const paraStyles = t.analysis.styles.filter((s) => s.type === "paragraph" && !s.id.startsWith("TOC"));
  const tableStyles = t.analysis.styles.filter((s) => s.type === "table");
  const a = t.analysis;
  const approvedHere = t.profile.approved && !dirty;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="space-y-4">
        <div className="card flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-xl font-semibold">{t.name}</h2>
            <p className="text-xs text-slate-500">
              Template version {t.version} · rules v{t.profile.version} ·{" "}
              <span className={approvedHere ? "text-green-700" : "text-amber-700"}>{approvedHere ? "approved" : "draft (not approved)"}</span>
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <input ref={newVer} type="file" accept=".docx" className="hidden" onChange={(e) => void newVersion(e.target.files?.[0])} />
            <button className="btn" onClick={() => newVer.current?.click()}>Upload new version</button>
            <button className="btn" onClick={() => void preview()} disabled={busy}>Preview sample</button>
            <button className="btn" onClick={() => void save().then(() => setMsg({ kind: "ok", text: "Draft saved." })).catch((e) => setMsg({ kind: "err", text: e.message }))} disabled={!dirty}>Save draft</button>
            <button className="btn btn-primary" onClick={() => void approve()}>Approve rules</button>
          </div>
        </div>
        {msg && <p className={`rounded border p-2 text-sm ${msg.kind === "ok" ? "border-green-200 bg-green-50 text-green-800" : "border-red-200 bg-red-50 text-red-700"}`}>{msg.text}</p>}

        <section className="card space-y-2">
          <h3 className="font-semibold">What SmartDoc found</h3>
          <p className="text-sm text-slate-600">
            Page {a.page.width_cm}×{a.page.height_cm} cm ({a.page.orientation}), {a.page.columns} column(s); margins
            T{a.page.margins_cm.top} B{a.page.margins_cm.bottom} L{a.page.margins_cm.left} R{a.page.margins_cm.right} cm.
            {a.header_footer.header_text && <> Header: “{a.header_footer.header_text}”.</>}
            {a.header_footer.footer_has_page_number && <> Footer has page numbers.</>}
          </p>
          {a.health.length === 0 ? <p className="text-sm text-green-700">No problems found in this template.</p> : (
            <ul className="space-y-1.5">
              {a.health.map((h) => (
                <li key={h.code} className="flex gap-2 text-sm">
                  <span className={`h-fit shrink-0 rounded px-1.5 py-0.5 text-xs ${SEV[h.severity]}`}>{h.severity}</span>
                  <span>{h.message}{h.hint && <span className="text-slate-500"> {h.hint}</span>}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-slate-400">Page setup, headers, footers, logos and numbering are taken from the template file itself and cannot be changed here.</p>
        </section>

        {history.length > 0 && (
          <section className="card space-y-1">
            <h3 className="font-semibold">Versions</h3>
            <p className="text-xs text-slate-500">Approved rules never change; editing them starts a new draft. Each document keeps the version it was made with.</p>
            <ul className="text-sm">
              {history.map((h) => (
                <li key={h.id} className="flex justify-between border-b border-slate-100 py-1">
                  <span>Template v{h.template_version} · rules v{h.version}</span>
                  <span className={h.approved ? "text-green-700" : "text-amber-700"}>
                    {h.approved ? `approved ${h.approved_at ? new Date(h.approved_at + "Z").toLocaleDateString() : ""}` : "draft"}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="card space-y-2">
          <h3 className="font-semibold">Which template style is used for what</h3>
          <p className="text-xs text-slate-500">Content is written with the template's own styles. If nothing is chosen for a role, SmartDoc creates a plain fallback style.</p>
          <div className="divide-y divide-slate-100">
            {ROLES.map((r) => (
              <div key={r.id} className="grid grid-cols-[9rem_1fr_6rem] items-center gap-2 py-1.5">
                <span className="text-sm">{r.label}</span>
                <select className="input" value={rules.roles[r.id] ?? ""}
                  onChange={(e) => edit((x) => { if (e.target.value) x.roles[r.id] = e.target.value; else delete x.roles[r.id]; }, `roles.${r.id}`)}>
                  <option value="">(none — create fallback)</option>
                  {paraStyles.map((s) => <option key={s.id} value={s.id}>{describe(s)}</option>)}
                </select>
                <span className="text-[11px] text-slate-400">{rules.roles[r.id] ? ORIGIN[rules.origins[`roles.${r.id}`] || "template"] : ""}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="card grid gap-3 sm:grid-cols-2">
          <h3 className="font-semibold sm:col-span-2">Numbering and lists</h3>
          <Field label="Heading numbering">
            <select className="input" value={rules.heading_numbering} onChange={(e) => edit((x) => { x.heading_numbering = e.target.value as FormattingProfile["heading_numbering"]; })}>
              <option value="template">As the template does it{a.heading_numbering_in_template ? " (numbered)" : " (not numbered)"}</option>
              <option value="auto">Number headings 1, 1.1, 1.1.1</option>
              <option value="none">No heading numbers</option>
            </select>
          </Field>
          <label className="flex items-start gap-2 text-sm sm:col-span-2">
            <input type="checkbox" className="mt-1" checked={rules.keep_template_layout}
              onChange={(e) => edit((x) => { x.keep_template_layout = e.target.checked; }, "keep_template_layout")} />
            <span>Keep the template's first-page layout (everything before its first heading: banners, boxes, logos) and
              fill its {"{{placeholders}}"}. When off, the whole body is replaced by the document's content.</span>
          </label>
          <Field label="Lists">
            <select className="input" value={rules.list_mode} onChange={(e) => edit((x) => { x.list_mode = e.target.value as FormattingProfile["list_mode"]; })}>
              <option value="template">Use the template's list styles when available</option>
              <option value="generated">Always generate bullets/numbers</option>
            </select>
          </Field>
        </section>

        <section className="card grid gap-3 sm:grid-cols-2">
          <h3 className="font-semibold sm:col-span-2">Table rule (locked for users)</h3>
          <Field label="Caption label"><input className="input" value={rules.table.label} onChange={(e) => edit((x) => { x.table.label = e.target.value; }, "table.label")} /></Field>
          <Field label="Caption position">
            <select className="input" value={rules.table.caption_position} onChange={(e) => edit((x) => { x.table.caption_position = e.target.value as "above" | "below"; }, "table.caption_position")}>
              <option value="above">Above the table</option><option value="below">Below the table</option></select></Field>
          <Field label="Alignment">
            <select className="input" value={rules.table.alignment} onChange={(e) => edit((x) => { x.table.alignment = e.target.value as "left"; }, "table.alignment")}>
              <option value="left">Left</option><option value="center">Center</option><option value="right">Right</option></select></Field>
          <Field label="Width (% of text width)"><input type="number" min={10} max={100} className="input" value={rules.table.width_percent}
            onChange={(e) => edit((x) => { x.table.width_percent = Math.max(10, Math.min(100, Number(e.target.value) || 100)); })} /></Field>
          <Field label="Borders">
            <select className="input" value={rules.table.borders} onChange={(e) => edit((x) => {
              x.table.borders = e.target.value as FormattingProfile["table"]["borders"];
              if (x.table.borders === "template" && !x.table.template_style_id && tableStyles.length) x.table.template_style_id = tableStyles[0].id;
            }, "table.borders")}>
              <option value="all">All borders</option><option value="horizontal">Horizontal lines only</option>
              <option value="none">None</option><option value="template" disabled={tableStyles.length === 0}>Use a template table style</option></select></Field>
          {rules.table.borders === "template" && (
            <Field label="Template table style">
              <select className="input" value={rules.table.template_style_id ?? ""} onChange={(e) => edit((x) => { x.table.template_style_id = e.target.value || null; })}>
                {tableStyles.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
          )}
          <Field label="Header row shading (hex, empty = none)">
            <HexInput value={rules.table.header_shading} onChange={(v) => edit((x) => { x.table.header_shading = v; }, "table.header_shading")} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={rules.table.header_bold} onChange={(e) => edit((x) => { x.table.header_bold = e.target.checked; })} /> Bold header row</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={rules.table.repeat_header} onChange={(e) => edit((x) => { x.table.repeat_header = e.target.checked; })} /> Repeat header on each page</label>
        </section>

        <section className="card grid gap-3 sm:grid-cols-2">
          <h3 className="font-semibold sm:col-span-2">Figure rule (locked for users)</h3>
          <Field label="Caption label"><input className="input" value={rules.figure.label} onChange={(e) => edit((x) => { x.figure.label = e.target.value; }, "figure.label")} /></Field>
          <Field label="Caption position">
            <select className="input" value={rules.figure.caption_position} onChange={(e) => edit((x) => { x.figure.caption_position = e.target.value as "above" | "below"; }, "figure.caption_position")}>
              <option value="below">Below the figure</option><option value="above">Above the figure</option></select></Field>
          <Field label="Alignment">
            <select className="input" value={rules.figure.alignment} onChange={(e) => edit((x) => { x.figure.alignment = e.target.value as "left"; }, "figure.alignment")}>
              <option value="left">Left</option><option value="center">Center</option><option value="right">Right</option></select></Field>
          <Field label="Maximum width (% of text width)"><input type="number" min={10} max={100} className="input" value={rules.figure.max_width_percent}
            onChange={(e) => edit((x) => { x.figure.max_width_percent = Math.max(10, Math.min(100, Number(e.target.value) || 100)); })} /></Field>
        </section>

        <section className="card grid gap-3 sm:grid-cols-2">
          <h3 className="font-semibold sm:col-span-2">Language and labels</h3>
          <Field label="Default language code (e.g. en, bn, ar-SA)"><input className="input" value={rules.language.code} onChange={(e) => edit((x) => { x.language.code = e.target.value; })} /></Field>
          <div className="space-y-1 pt-5">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={rules.language.rtl} onChange={(e) => edit((x) => { x.language.rtl = e.target.checked; })} /> Right-to-left text</label>
            <label className="flex items-center gap-2 text-sm" title="Table and figure numbers like ১, ٢. LibreOffice/PDF export shows 1, 2, 3 anyway.">
              <input type="checkbox" checked={rules.language.native_digits} onChange={(e) => edit((x) => { x.language.native_digits = e.target.checked; })} /> Caption numbers in the language's own digits</label>
          </div>
          <Field label="Complex-script font (Bangla, Arabic, Hindi…)"><input className="input" value={rules.language.complex_script_font ?? ""} placeholder="e.g. Kalpurush"
            onChange={(e) => edit((x) => { x.language.complex_script_font = e.target.value || null; })} /></Field>
          <Field label="East-Asian font (Chinese, Japanese, Korean)"><input className="input" value={rules.language.east_asian_font ?? ""} placeholder="e.g. SimSun"
            onChange={(e) => edit((x) => { x.language.east_asian_font = e.target.value || null; })} /></Field>
          <Field label="Abstract label"><input className="input" value={rules.labels.abstract} onChange={(e) => edit((x) => { x.labels.abstract = e.target.value; })} /></Field>
          <Field label="Keywords label"><input className="input" value={rules.labels.keywords} onChange={(e) => edit((x) => { x.labels.keywords = e.target.value; })} /></Field>
          <Field label="Source label"><input className="input" value={rules.labels.source} onChange={(e) => edit((x) => { x.labels.source = e.target.value; })} /></Field>
          <Field label="Note label"><input className="input" value={rules.labels.note} onChange={(e) => edit((x) => { x.labels.note = e.target.value; })} /></Field>
          <div className="sm:col-span-2"><Field label="Required top-level sections (comma separated, optional)">
            <input className="input" value={rules.required_sections.join(", ")} placeholder="Introduction, Conclusion"
              onChange={(e) => edit((x) => { x.required_sections = e.target.value.split(",").map((s) => s.trim()).filter(Boolean); })} /></Field></div>
        </section>
      </div>

      <div className="lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)]">
        <PreviewPane blob={blob} busy={busy} error={previewErr}
          emptyText="Click “Preview sample” to see a sample document built with these rules and your template." />
      </div>
    </div>
  );
}
