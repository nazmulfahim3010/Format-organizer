import { useEffect, useRef, useState } from "react";
import { del, api, upload } from "../api";
import { TemplateDetail, TemplateSummary } from "../types";

export default function Templates() {
  const [items, setItems] = useState<TemplateSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const load = () => api<TemplateSummary[]>("/api/templates").then(setItems).catch((e) => setErr(e.message));
  useEffect(() => { void load(); }, []);

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    setBusy(true); setErr(null);
    try {
      const t = await upload<TemplateDetail>("/api/templates/upload", f);
      location.hash = `#/templates/${t.id}`;
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); if (file.current) file.current.value = ""; }
  };

  const remove = async (t: TemplateSummary) => {
    if (!confirm(`Delete template “${t.name}”?`)) return;
    try { await del(`/api/templates/${t.id}`); void load(); } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Templates</h2>
        <div>
          <input ref={file} type="file" accept=".docx" className="hidden" onChange={(e) => void onFile(e.target.files?.[0])} />
          <button className="btn btn-primary" disabled={busy} onClick={() => file.current?.click()}>{busy ? "Analysing…" : "Upload .docx template"}</button>
        </div>
      </div>
      <p className="text-sm text-slate-600">
        Upload any Word template (any language). SmartDoc reads its styles, page setup, headers and footers, suggests how each part of a
        document maps to the template, and lets you review and approve that mapping before use.
      </p>
      {err && <p className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">{err}</p>}
      {items === null ? <p className="text-sm text-slate-500">Loading…</p> : items.length === 0 ? (
        <div className="card text-sm text-slate-500">No templates yet. Upload your first .docx template to begin.</div>
      ) : (
        <ul className="space-y-2">
          {items.map((t) => (
            <li key={t.id} className="card flex items-center justify-between">
              <div>
                <a href={`#/templates/${t.id}`} className="font-medium text-indigo-700 hover:underline">{t.name}</a>
                <div className="text-xs text-slate-500">
                  {t.versions} version(s) · {t.latest_profile_approved ? "approved" : "draft — needs review and approval"}
                </div>
              </div>
              <div className="flex gap-2">
                <a className="btn btn-sm" href={`#/templates/${t.id}`}>Review rules</a>
                <button className="btn btn-sm btn-danger" onClick={() => void remove(t)}>Delete</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
