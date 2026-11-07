import { useEffect, useState } from "react";
import { api, blobOf, del, post } from "../api";
import PreviewPane from "../components/PreviewPane";
import { DesignDocumentDetail, DesignDocumentSummary, DesignSummary } from "../types";

/** Workflow B entry point: pick a predefined visual design, then build the article with a form. */
export default function Designs() {
  const [items, setItems] = useState<DesignSummary[] | null>(null);
  const [docs, setDocs] = useState<DesignDocumentSummary[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ id: string; blob: Blob | null; busy: boolean; error: string | null } | null>(null);
  const [title, setTitle] = useState("");

  const load = async () => {
    try {
      setItems(await api<DesignSummary[]>("/api/designs"));
      setDocs(await api<DesignDocumentSummary[]>("/api/design-documents"));
    } catch (e) { setErr((e as Error).message); }
  };
  useEffect(() => { void load(); }, []);

  const showSample = async (id: string) => {
    setPreview({ id, blob: null, busy: true, error: null });
    try { setPreview({ id, blob: await blobOf(`/api/designs/${id}/sample`), busy: false, error: null }); }
    catch (e) { setPreview({ id, blob: null, busy: false, error: (e as Error).message }); }
  };

  const create = async (design_id: string) => {
    setErr(null);
    try {
      const d = await post<DesignDocumentDetail>("/api/design-documents", { design_id, title });
      location.hash = `#/articles/${d.id}`;
    } catch (e) { setErr((e as Error).message); }
  };

  const remove = async (d: DesignDocumentSummary) => {
    if (!confirm(`Delete “${d.title || "Untitled"}” and its generated files?`)) return;
    try { await del(`/api/design-documents/${d.id}`); void load(); } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="space-y-4">
        <h2 className="text-xl font-semibold">Predefined designs</h2>
        <p className="text-sm text-slate-600">
          A ready-made journal layout. Fill in a form with your article — any sections and subsections you like —
          and SmartDoc lays it out in the design. To use your own Word template instead, go to Templates.
        </p>
        {err && <p className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700">{err}</p>}
        {items === null ? <p className="text-sm text-slate-500">Loading…</p> : items.map((d) => (
          <section key={d.id} className="card space-y-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h3 className="font-semibold">{d.name}</h3>
                <p className="text-xs text-slate-500">Design version {d.version}</p>
              </div>
              <button className="btn btn-sm" onClick={() => void showSample(d.id)}>Preview design</button>
            </div>
            <p className="text-sm text-slate-600">{d.description}</p>
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[16rem] flex-1"><label className="label">Article title</label>
                <input className="input" dir="auto" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="You can change it later" /></div>
              <button className="btn btn-primary" onClick={() => void create(d.id)}>Create article</button>
            </div>
          </section>
        ))}
        {docs.length > 0 && (
          <section className="space-y-2">
            <h3 className="font-semibold">Your articles</h3>
            <ul className="space-y-2">
              {docs.map((d) => (
                <li key={d.id} className="card flex items-center justify-between">
                  <div>
                    <a href={`#/articles/${d.id}`} className="font-medium text-indigo-700 hover:underline" dir="auto">{d.title || "Untitled"}</a>
                    <div className="text-xs text-slate-500">
                      {d.design_id.toUpperCase()} design {d.design_version} · updated {new Date(d.updated_at + "Z").toLocaleString()}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <a className="btn btn-sm" href={`#/articles/${d.id}`}>Open</a>
                    <button className="btn btn-sm btn-danger" onClick={() => void remove(d)}>Delete</button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
      <div className="lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)]">
        <PreviewPane blob={preview?.blob ?? null} busy={preview?.busy} error={preview?.error}
          emptyText="Click “Preview design” to see the design with a sample article." />
      </div>
    </div>
  );
}
