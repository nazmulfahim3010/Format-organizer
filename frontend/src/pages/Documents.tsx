import { useEffect, useState } from "react";
import { api, del, post } from "../api";
import { DocumentDetail, DocumentSummary, TemplateSummary } from "../types";

export const LANGUAGES: [string, string][] = [
  ["en", "English"], ["bn", "Bangla (বাংলা)"], ["ar", "Arabic (العربية)"], ["he", "Hebrew"], ["fa", "Persian"],
  ["ur", "Urdu"], ["hi", "Hindi"], ["zh", "Chinese"], ["ja", "Japanese"], ["ko", "Korean"], ["es", "Spanish"],
  ["fr", "French"], ["de", "German"], ["ru", "Russian"], ["pt", "Portuguese"], ["tr", "Turkish"], ["ta", "Tamil"],
];

export default function Documents() {
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null);
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [profileId, setProfileId] = useState<number | "">("");
  const [title, setTitle] = useState("");
  const [lang, setLang] = useState("en");

  const load = async () => {
    try {
      setDocs(await api<DocumentSummary[]>("/api/documents"));
      const t = await api<TemplateSummary[]>("/api/templates");
      setTemplates(t);
      const first = t.find((x) => x.approved_profile_id);
      if (first && profileId === "") setProfileId(first.approved_profile_id!);
    } catch (e) { setErr((e as Error).message); }
  };
  useEffect(() => { void load(); }, []);

  const usable = templates.filter((t) => t.approved_profile_id);

  const create = async () => {
    if (profileId === "") return;
    setErr(null);
    try {
      const d = await post<DocumentDetail>("/api/documents", { title, profile_id: profileId, language: lang });
      location.hash = `#/documents/${d.id}`;
    } catch (e) { setErr((e as Error).message); }
  };

  const remove = async (d: DocumentSummary) => {
    if (!confirm(`Delete “${d.title || "Untitled"}” and its generated files?`)) return;
    try { await del(`/api/documents/${d.id}`); void load(); } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Documents</h2>
      {err && <p className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">{err}</p>}

      <section className="card space-y-3">
        <h3 className="font-semibold">New document</h3>
        {usable.length === 0 ? (
          <p className="text-sm text-slate-600">You need an approved template first. <a className="text-indigo-700 underline" href="#/templates">Upload and approve one</a>.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-[1fr_1fr_12rem_auto]">
            <div><label className="label">Template</label>
              <select className="input" value={profileId} onChange={(e) => setProfileId(Number(e.target.value))}>
                {usable.map((t) => <option key={t.id} value={t.approved_profile_id!}>{t.name}</option>)}</select></div>
            <div><label className="label">Title</label><input className="input" dir="auto" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
            <div><label className="label">Language</label>
              <input className="input" list="langs" value={lang} onChange={(e) => setLang(e.target.value)} />
              <datalist id="langs">{LANGUAGES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}</datalist></div>
            <div className="flex items-end"><button className="btn btn-primary" onClick={() => void create()}>Create</button></div>
          </div>
        )}
      </section>

      {docs === null ? <p className="text-sm text-slate-500">Loading…</p> : docs.length === 0 ? null : (
        <ul className="space-y-2">
          {docs.map((d) => (
            <li key={d.id} className="card flex items-center justify-between">
              <div>
                <a href={`#/documents/${d.id}`} className="font-medium text-indigo-700 hover:underline" dir="auto">{d.title || "Untitled"}</a>
                <div className="text-xs text-slate-500">Updated {new Date(d.updated_at + "Z").toLocaleString()}</div>
              </div>
              <div className="flex gap-2">
                <a className="btn btn-sm" href={`#/documents/${d.id}`}>Open</a>
                <button className="btn btn-sm btn-danger" onClick={() => void remove(d)}>Delete</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
