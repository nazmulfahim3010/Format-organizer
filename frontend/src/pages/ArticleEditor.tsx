import { useCallback, useEffect, useRef, useState } from "react";
import { api, blobOf, post, put, saveBlob } from "../api";
import BoxList from "../components/BoxEditor";
import PreviewPane from "../components/PreviewPane";
import ValidationPanel from "../components/ValidationPanel";
import { Affiliation, ArticleAuthor, ArticleContent, ArticleMetadata, BackMatter, Box, DesignDocumentDetail, ValidationReport } from "../types";

type Status = "saved" | "unsaved" | "saving" | "error";
const STATUS_TEXT: Record<Status, string> = { saved: "All changes saved", unsaved: "Unsaved changes…", saving: "Saving…", error: "Could not save" };

const META_FIELDS: [keyof ArticleMetadata, string, string][] = [
  ["doi", "DOI", "10.xxxx/…"], ["volume", "Volume", "01"], ["issue", "Issue", "04"], ["pages", "Pages", "12-27"],
  ["year", "Year", "2026"], ["received", "Received", "12 June 2026"], ["accepted", "Accepted", "2 September 2026"],
  ["published", "Publication date", "30 October 2026"], ["corresponding_email", "Corresponding e-mail", "name@example.org"],
];
const BACK: [keyof BackMatter, string][] = [
  ["acknowledgements", "Acknowledgements"], ["competing_interests", "Declaration of competing interest"],
  ["ai_declaration", "Generative AI declaration"], ["funding", "Funding"],
];

function move<T>(list: T[], i: number, d: -1 | 1): T[] {
  const j = i + d;
  if (j < 0 || j >= list.length) return list;
  const c = [...list]; [c[i], c[j]] = [c[j], c[i]]; return c;
}

/** Workflow B: an article form; the look comes from the predefined design. */
export default function ArticleEditor({ id }: { id: number }) {
  const [doc, setDoc] = useState<DesignDocumentDetail | null>(null);
  const [content, setContent] = useState<ArticleContent | null>(null);
  const [status, setStatus] = useState<Status>("saved");
  const [blob, setBlob] = useState<Blob | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"preview" | "checks">("preview");
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [working, setWorking] = useState<string | null>(null);
  const [bulk, setBulk] = useState("");
  const dirty = useRef(false);
  const saveSeq = useRef(0);
  const previewSeq = useRef(0);
  const contentRef = useRef<ArticleContent | null>(null);
  contentRef.current = content;

  const refreshPreview = useCallback(async () => {
    const seq = ++previewSeq.current;
    setPreviewBusy(true);
    try {
      const b = await blobOf(`/api/design-documents/${id}/preview`);
      if (seq === previewSeq.current) { setBlob(b); setPreviewErr(null); }
    } catch (e) { if (seq === previewSeq.current) setPreviewErr((e as Error).message); }
    finally { if (seq === previewSeq.current) setPreviewBusy(false); }
  }, [id]);

  const saveNow = useCallback(async () => {
    const c = contentRef.current;
    if (!c) return;
    const seq = ++saveSeq.current;
    setStatus("saving");
    try {
      const d = await put<DesignDocumentDetail>(`/api/design-documents/${id}`, c);
      if (seq === saveSeq.current) { dirty.current = false; setStatus("saved"); setDoc(d); }
    } catch (e) { setStatus("error"); setMsg((e as Error).message); throw e; }
  }, [id]);

  useEffect(() => {
    api<DesignDocumentDetail>(`/api/design-documents/${id}`).then((d) => { setDoc(d); setContent(d.content); void refreshPreview(); })
      .catch((e) => setMsg(e.message));
  }, [id, refreshPreview]);

  useEffect(() => {
    if (!content || !dirty.current) return;
    const t = setTimeout(() => { saveNow().then(refreshPreview).catch(() => undefined); }, 900);
    return () => clearTimeout(t);
  }, [content, saveNow, refreshPreview]);

  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (dirty.current) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, []);

  if (!doc || !content) return <p className="text-sm text-slate-500">{msg ?? "Loading…"}</p>;

  const change = (next: ArticleContent) => { dirty.current = true; setStatus("unsaved"); setMsg(null); setContent(next); };
  const meta = (p: Partial<ArticleMetadata>) => change({ ...content, metadata: { ...content.metadata, ...p } });
  const m = content.metadata;
  const setAuthor = (i: number, p: Partial<ArticleAuthor>) =>
    meta({ authors: m.authors.map((a, j) => (j === i ? { ...a, ...p } : p.corresponding ? { ...a, corresponding: false } : a)) });
  const setAff = (i: number, p: Partial<Affiliation>) => meta({ affiliations: m.affiliations.map((a, j) => (j === i ? { ...a, ...p } : a)) });
  const nextAffId = () => String(Math.max(0, ...m.affiliations.map((a) => Number(a.id) || 0)) + 1);
  const removeAff = (i: number) => {
    const gone = m.affiliations[i].id;
    meta({ affiliations: m.affiliations.filter((_, j) => j !== i), authors: m.authors.map((a) => ({ ...a, affiliations: a.affiliations.filter((x) => x !== gone) })) });
  };
  const refs = content.references;
  const setRefs = (references: string[]) => change({ ...content, references });

  const flushSave = async () => { if (dirty.current) await saveNow(); };
  const safeName = () => (m.title || "article").replace(/[^\p{L}\p{N} _-]/gu, "").slice(0, 60) || "article";
  const run = async (label: string, fn: () => Promise<void>) => {
    setWorking(label); setMsg(null);
    try { await flushSave(); await fn(); } catch (e) { setMsg((e as Error).message); } finally { setWorking(null); }
  };
  const download = () => run("Generating DOCX…", async () => {
    const g = await post<{ file_id: number; warnings: { message: string }[] }>(`/api/design-documents/${id}/generate`);
    saveBlob(await blobOf(`/api/design-documents/${id}/files/${g.file_id}/download`, "GET"), `${safeName()}.docx`);
    setMsg(g.warnings.length ? `Downloaded. ${g.warnings.length} note(s): ${g.warnings.map((w) => w.message).slice(0, 3).join(" · ")}` : "Downloaded.");
  });
  const exportPdf = () => run("Creating PDF…", async () => saveBlob(await blobOf(`/api/design-documents/${id}/pdf`), `${safeName()}.pdf`));
  const validate = () => run("Checking…", async () => { setReport(await post<ValidationReport>(`/api/design-documents/${id}/validate`)); setTab("checks"); });
  const upgrade = () => run("Updating design…", async () => { setDoc(await post<DesignDocumentDetail>(`/api/design-documents/${id}/upgrade`)); void refreshPreview(); });

  return (
    <div className="space-y-3">
      <div className="card flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <a href="#/designs" className="text-sm text-indigo-700">← Designs</a>
          <span className="text-sm">{doc.design_id.toUpperCase()} design {doc.design_version}</span>
          <span className={`text-xs ${status === "error" ? "text-red-600" : "text-slate-500"}`}>{STATUS_TEXT[status]}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn" disabled={!!working} onClick={() => void validate()}>Check formatting</button>
          <button className="btn" disabled={!!working} onClick={() => void exportPdf()}>Export PDF</button>
          <button className="btn btn-primary" disabled={!!working} onClick={() => void download()}>Download DOCX</button>
        </div>
      </div>
      {doc.latest_version !== doc.design_version && (
        <p className="flex flex-wrap items-center gap-2 rounded border border-indigo-200 bg-indigo-50 p-2 text-sm text-indigo-900">
          Design version {doc.latest_version} is available. This article keeps version {doc.design_version} until you switch.
          <button className="btn btn-sm" onClick={() => void upgrade()}>Use version {doc.latest_version}</button>
        </p>
      )}
      {(working || msg) && <p className={`rounded border p-2 text-sm ${working ? "border-slate-200 bg-white text-slate-600" : "border-amber-200 bg-amber-50 text-amber-900"}`}>{working ?? msg}</p>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <section className="card space-y-3">
            <h3 className="font-semibold">Article information</h3>
            <div><label className="label">Title</label>
              <textarea dir="auto" className="input min-h-[50px]" value={m.title} onChange={(e) => meta({ title: e.target.value })} /></div>
            <div className="grid gap-2 sm:grid-cols-3">
              {META_FIELDS.map(([k, label, ph]) => (
                <div key={k}><label className="label">{label}</label>
                  <input className="input" dir="auto" placeholder={ph} value={m[k] as string} onChange={(e) => meta({ [k]: e.target.value } as Partial<ArticleMetadata>)} /></div>
              ))}
            </div>
          </section>

          <section className="card space-y-2">
            <h3 className="font-semibold">Affiliations</h3>
            {m.affiliations.map((a, i) => (
              <div key={i} className="grid gap-2 sm:grid-cols-[3rem_1fr_1fr_1fr_1fr_auto]">
                <input className="input" title="Marker shown after author names" value={a.id} onChange={(e) => setAff(i, { id: e.target.value.slice(0, 10) })} />
                <input className="input" placeholder="Department" value={a.department} onChange={(e) => setAff(i, { department: e.target.value })} />
                <input className="input" placeholder="Institution" value={a.institution} onChange={(e) => setAff(i, { institution: e.target.value })} />
                <input className="input" placeholder="City" value={a.city} onChange={(e) => setAff(i, { city: e.target.value })} />
                <input className="input" placeholder="Country" value={a.country} onChange={(e) => setAff(i, { country: e.target.value })} />
                <button className="btn btn-sm btn-danger" onClick={() => removeAff(i)}>Remove</button>
              </div>
            ))}
            <button className="btn btn-sm" onClick={() => meta({ affiliations: [...m.affiliations, { id: nextAffId(), department: "", institution: "", city: "", country: "" }] })}>+ Affiliation</button>
          </section>

          <section className="card space-y-2">
            <h3 className="font-semibold">Authors</h3>
            {m.authors.map((a, i) => (
              <div key={i} className="space-y-1 rounded border border-slate-200 p-2">
                <div className="grid gap-2 sm:grid-cols-[1fr_12rem_auto]">
                  <input className="input" dir="auto" placeholder="Full name" value={a.name} onChange={(e) => setAuthor(i, { name: e.target.value })} />
                  <input className="input" placeholder="ORCID (optional)" value={a.orcid ?? ""} onChange={(e) => setAuthor(i, { orcid: e.target.value || null })} />
                  <div className="flex gap-1">
                    <button className="btn btn-sm" disabled={i === 0} onClick={() => meta({ authors: move(m.authors, i, -1) })}>↑</button>
                    <button className="btn btn-sm" disabled={i === m.authors.length - 1} onClick={() => meta({ authors: move(m.authors, i, 1) })}>↓</button>
                    <button className="btn btn-sm btn-danger" onClick={() => meta({ authors: m.authors.filter((_, j) => j !== i) })}>Remove</button>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
                  <label className="flex items-center gap-1"><input type="radio" checked={a.corresponding} onChange={() => setAuthor(i, { corresponding: true })} /> Corresponding author</label>
                  {m.affiliations.length === 0 ? <span>Add affiliations above to link them.</span> : m.affiliations.map((af) => (
                    <label key={af.id} className="flex items-center gap-1">
                      <input type="checkbox" checked={a.affiliations.includes(af.id)}
                        onChange={(e) => setAuthor(i, { affiliations: e.target.checked ? [...a.affiliations, af.id] : a.affiliations.filter((x) => x !== af.id) })} />
                      {af.id} {af.institution || af.department}
                    </label>
                  ))}
                </div>
              </div>
            ))}
            <button className="btn btn-sm" onClick={() => meta({ authors: [...m.authors, { name: "", affiliations: [], corresponding: m.authors.length === 0, orcid: null }] })}>+ Author</button>
          </section>

          <section className="card space-y-2">
            <h3 className="font-semibold">Abstract and keywords</h3>
            <textarea dir="auto" className="input min-h-[120px]" placeholder="Abstract (an empty line starts a new paragraph)"
              value={content.abstract} onChange={(e) => change({ ...content, abstract: e.target.value })} />
            <div><label className="label">Keywords (comma separated)</label>
              <input dir="auto" className="input" value={content.keywords.join(", ")}
                onChange={(e) => change({ ...content, keywords: e.target.value.split(",").map((s) => s.trimStart()) })} /></div>
          </section>

          <section className="card space-y-2">
            <h3 className="font-semibold">Main content</h3>
            <p className="text-xs text-slate-500">Your own sections and subsections, in any order and depth. Numbers (1, 1.1, 1.1.1) are added automatically.</p>
            <BoxList body={content.body} path={[]} onBody={(body: Box[]) => change({ ...content, body })} />
          </section>

          <section className="card space-y-2">
            <h3 className="font-semibold">Declarations (optional)</h3>
            <p className="text-xs text-slate-500">Leave a box empty to leave that statement out.</p>
            {BACK.map(([k, label]) => (
              <div key={k}><label className="label">{label}</label>
                <textarea dir="auto" className="input min-h-[50px]" value={content.back_matter[k]}
                  onChange={(e) => change({ ...content, back_matter: { ...content.back_matter, [k]: e.target.value } })} /></div>
            ))}
          </section>

          <section className="card space-y-2">
            <h3 className="font-semibold">References</h3>
            {refs.map((r, i) => (
              <div key={i} className="flex gap-1">
                <textarea dir="auto" className="input min-h-[40px]" value={r} onChange={(e) => setRefs(refs.map((x, j) => (j === i ? e.target.value : x)))} />
                <div className="flex flex-col gap-1">
                  <button className="btn btn-sm" disabled={i === 0} onClick={() => setRefs(move(refs, i, -1))}>↑</button>
                  <button className="btn btn-sm" disabled={i === refs.length - 1} onClick={() => setRefs(move(refs, i, 1))}>↓</button>
                  <button className="btn btn-sm btn-danger" onClick={() => setRefs(refs.filter((_, j) => j !== i))}>×</button>
                </div>
              </div>
            ))}
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-sm" onClick={() => setRefs([...refs, ""])}>+ Reference</button>
            </div>
            <textarea className="input min-h-[50px] border-dashed" placeholder="Or paste a reference list here, one reference per line, then click Add all"
              value={bulk} onChange={(e) => setBulk(e.target.value)} />
            {bulk.trim() && <button className="btn btn-sm" onClick={() => { setRefs([...refs, ...bulk.split("\n").map((s) => s.trim()).filter(Boolean)]); setBulk(""); }}>Add all</button>}
          </section>
        </div>

        <div className="lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)] flex flex-col gap-2">
          <div className="flex gap-1">
            <button className={`btn btn-sm ${tab === "preview" ? "btn-primary" : ""}`} onClick={() => setTab("preview")}>Live preview</button>
            <button className={`btn btn-sm ${tab === "checks" ? "btn-primary" : ""}`} onClick={() => setTab("checks")}>Formatting checks</button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {tab === "preview" ? <PreviewPane blob={blob} busy={previewBusy} error={previewErr} emptyText="The preview appears here as you write." /> : (
              <div className="card">{report ? <ValidationPanel report={report} /> : <p className="text-sm text-slate-500">Click “Check formatting” to verify the generated file.</p>}</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
