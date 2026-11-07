import { useCallback, useEffect, useRef, useState } from "react";
import { api, blobOf, post, put, saveBlob } from "../api";
import BoxList from "../components/BoxEditor";
import PasteZone from "../components/PasteZone";
import PreviewPane from "../components/PreviewPane";
import ValidationPanel from "../components/ValidationPanel";
import { flatSections, insertBoxes, Path } from "../ops";
import { BUILTIN_FIELDS, Box, DocumentContent, DocumentDetail, TemplateSummary, ValidationReport } from "../types";
import { LANGUAGES } from "./Documents";

type Status = "saved" | "unsaved" | "saving" | "error";
const STATUS_TEXT: Record<Status, string> = { saved: "All changes saved", unsaved: "Unsaved changes…", saving: "Saving…", error: "Could not save" };

export default function DocumentEditor({ id }: { id: number }) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [content, setContent] = useState<DocumentContent | null>(null);
  const [status, setStatus] = useState<Status>("saved");
  const [blob, setBlob] = useState<Blob | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"preview" | "checks">("preview");
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [working, setWorking] = useState<string | null>(null);

  const dirty = useRef(false);
  const saveSeq = useRef(0);
  const previewSeq = useRef(0);
  const contentRef = useRef<DocumentContent | null>(null);
  contentRef.current = content;

  const refreshPreview = useCallback(async () => {
    const seq = ++previewSeq.current;
    setPreviewBusy(true);
    try {
      const b = await blobOf(`/api/documents/${id}/preview`);
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
      await put(`/api/documents/${id}`, c);
      if (seq === saveSeq.current) { dirty.current = false; setStatus("saved"); }
    } catch (e) { setStatus("error"); setMsg((e as Error).message); throw e; }
  }, [id]);

  // load
  useEffect(() => {
    api<DocumentDetail>(`/api/documents/${id}`).then((d) => { setDoc(d); setContent(d.content); void refreshPreview(); })
      .catch((e) => setMsg(e.message));
    api<TemplateSummary[]>("/api/templates").then(setTemplates).catch(() => undefined);
  }, [id, refreshPreview]);

  // autosave (debounced) then refresh the live preview
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

  const change = (next: DocumentContent) => { dirty.current = true; setStatus("unsaved"); setContent(next); };
  const patch = (p: Partial<DocumentContent>) => change({ ...content, ...p });
  const setBody = (body: Box[]) => patch({ body });

  const onInsert = (boxes: Box[], where: number | "root", title: string) => {
    const path: Path = where === "root" ? [] : flatSections(content.body)[where].path;
    patch({ body: insertBoxes(content.body, path, boxes), title: content.title || title });
  };

  const flushSave = async () => { if (dirty.current) await saveNow(); };

  const download = async () => {
    setWorking("Generating DOCX…"); setMsg(null);
    try {
      await flushSave();
      const g = await post<{ file_id: number; warnings: { message: string }[] }>(`/api/documents/${id}/generate`);
      const b = await blobOf(`/api/documents/${id}/files/${g.file_id}/download`, "GET");
      saveBlob(b, `${(content.title || "document").replace(/[^\p{L}\p{N} _-]/gu, "").slice(0, 60) || "document"}.docx`);
      setMsg(g.warnings.length ? `Downloaded. ${g.warnings.length} note(s): ${g.warnings.map((w) => w.message).slice(0, 3).join(" · ")}` : "Downloaded.");
    } catch (e) { setMsg((e as Error).message); }
    finally { setWorking(null); }
  };

  const exportPdf = async () => {
    setWorking("Creating PDF…"); setMsg(null);
    try {
      await flushSave();
      saveBlob(await blobOf(`/api/documents/${id}/pdf`), `${(content.title || "document").slice(0, 60)}.pdf`);
    } catch (e) { setMsg((e as Error).message); }
    finally { setWorking(null); }
  };

  const validate = async () => {
    setWorking("Checking…"); setMsg(null);
    try {
      await flushSave();
      setReport(await post<ValidationReport>(`/api/documents/${id}/validate`));
      setTab("checks");
    } catch (e) { setMsg((e as Error).message); }
    finally { setWorking(null); }
  };

  const switchTemplate = async (profileId: number) => {
    try {
      await flushSave();
      const d = await put<DocumentDetail>(`/api/documents/${id}/profile`, { profile_id: profileId });
      setDoc(d); setReport(null); void refreshPreview();
    } catch (e) { setMsg((e as Error).message); }
  };

  const sections = flatSections(content.body);
  // other templates' newest approved rules, plus the exact version this document is pinned to
  const usable = templates.filter((t) => t.approved_profile_id && t.id !== doc.template_id);
  const pinnedLabel = `${doc.template_name} (template v${doc.template_version}, rules v${doc.profile_version})`;
  const newer = doc.latest_profile_id && doc.latest_profile_id !== doc.profile_id ? doc.latest_profile_id : null;

  return (
    <div className="space-y-3">
      <div className="card flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <a href="#/documents" className="text-sm text-indigo-700">← Documents</a>
          <span className={`text-xs ${status === "error" ? "text-red-600" : "text-slate-500"}`}>{STATUS_TEXT[status]}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select className="input !w-auto" value={doc.profile_id} onChange={(e) => void switchTemplate(Number(e.target.value))} title="Template used for this document">
            <option value={doc.profile_id}>{pinnedLabel}</option>
            {usable.map((t) => <option key={t.id} value={t.approved_profile_id!}>{t.name}</option>)}
          </select>
          <button className="btn" disabled={!!working} onClick={() => void validate()}>Check formatting</button>
          <button className="btn" disabled={!!working} onClick={() => void exportPdf()}>Export PDF</button>
          <button className="btn btn-primary" disabled={!!working} onClick={() => void download()}>Download DOCX</button>
        </div>
      </div>
      {newer && (
        <p className="flex flex-wrap items-center gap-2 rounded border border-indigo-200 bg-indigo-50 p-2 text-sm text-indigo-900">
          A newer approved version of “{doc.template_name}” exists. This document keeps its current version until you switch.
          <button className="btn btn-sm" onClick={() => void switchTemplate(newer)}>Use the newer version</button>
        </p>
      )}
      {(working || msg) && <p className={`rounded border p-2 text-sm ${working ? "border-slate-200 bg-white text-slate-600" : "border-amber-200 bg-amber-50 text-amber-900"}`}>{working ?? msg}</p>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <section className="card space-y-3">
            <h3 className="font-semibold">Document information</h3>
            <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
              <div><label className="label">Title</label><input dir="auto" className="input" value={content.title} onChange={(e) => patch({ title: e.target.value })} /></div>
              <div><label className="label">Language</label>
                <input className="input" list="langs2" value={content.language} onChange={(e) => patch({ language: e.target.value })} />
                <datalist id="langs2">{LANGUAGES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}</datalist></div>
            </div>
            <div><label className="label">Subtitle</label><input dir="auto" className="input" value={content.subtitle} onChange={(e) => patch({ subtitle: e.target.value })} /></div>
            <div>
              <label className="label">Authors</label>
              <div className="space-y-2">
                {content.authors.map((a, i) => (
                  <div key={i} className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
                    {(["name", "affiliation", "email"] as const).map((k) => (
                      <input key={k} dir="auto" className="input" placeholder={k[0].toUpperCase() + k.slice(1)} value={a[k]}
                        onChange={(e) => patch({ authors: content.authors.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)) })} />
                    ))}
                    <button className="btn btn-sm btn-danger" onClick={() => patch({ authors: content.authors.filter((_, j) => j !== i) })}>Remove</button>
                  </div>
                ))}
                <button className="btn btn-sm" onClick={() => patch({ authors: [...content.authors, { name: "", affiliation: "", email: "" }] })}>+ Author</button>
              </div>
            </div>
            <div><label className="label">Abstract</label><textarea dir="auto" className="input min-h-[70px]" value={content.abstract} onChange={(e) => patch({ abstract: e.target.value })} /></div>
            <div><label className="label">Keywords (comma separated)</label>
              <input dir="auto" className="input" value={content.keywords.join(", ")} onChange={(e) => patch({ keywords: e.target.value.split(",").map((s) => s.trimStart()) })} /></div>
          </section>

          {doc.placeholders.length > 0 && (
            <section className="card space-y-2">
              <h3 className="font-semibold">Template fields</h3>
              <p className="text-xs text-slate-500">
                The template has placeholders such as {"{{DOI}}"}. {doc.placeholders.filter((n) => BUILTIN_FIELDS[n]).length > 0 &&
                  <>{doc.placeholders.filter((n) => BUILTIN_FIELDS[n]).map((n) => `{{${n}}}`).join(", ")} come from the document information above. </>}
                A placeholder left empty stays visible in the document.
              </p>
              <div className="grid gap-2 sm:grid-cols-2">
                {doc.placeholders.filter((n) => !BUILTIN_FIELDS[n]).map((n) => (
                  <label key={n} className="block">
                    <span className="label">{n.replace(/_/g, " ").toLowerCase()}</span>
                    <input dir="auto" className="input" value={content.fields?.[n] ?? ""} placeholder={`{{${n}}}`}
                      onChange={(e) => {
                        const fields = { ...(content.fields ?? {}) };
                        if (e.target.value) fields[n] = e.target.value; else delete fields[n];
                        patch({ fields });
                      }} />
                  </label>
                ))}
              </div>
            </section>
          )}

          <PasteZone sections={sections} onInsert={onInsert} />

          <section className="card space-y-2">
            <h3 className="font-semibold">Content</h3>
            <p className="text-xs text-slate-500">Each section has a title and content. Content can hold text, lists, tables, figures and sub-sections to any depth. Numbering and looks come from the template.</p>
            <BoxList body={content.body} path={[]} onBody={setBody} />
          </section>
        </div>

        <div className="lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)] flex flex-col gap-2">
          <div className="flex gap-1">
            <button className={`btn btn-sm ${tab === "preview" ? "btn-primary" : ""}`} onClick={() => setTab("preview")}>Live preview</button>
            <button className={`btn btn-sm ${tab === "checks" ? "btn-primary" : ""}`} onClick={() => setTab("checks")}>Formatting checks</button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {tab === "preview" ? <PreviewPane blob={blob} busy={previewBusy} error={previewErr} emptyText="The preview appears here as you write." /> : (
              <div className="card">
                {report ? <ValidationPanel report={report} /> : <p className="text-sm text-slate-500">Click “Check formatting” to verify the generated file against the template rules.</p>}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
