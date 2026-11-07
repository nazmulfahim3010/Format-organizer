import { useState } from "react";
import { post } from "../api";
import { Box, PasteResult } from "../types";
import { FlatSection } from "../ops";

interface Props {
  sections: FlatSection[];
  onInsert: (boxes: Box[], where: number | "root", title: string) => void;
}

/** Paste anything (Word, Google Docs, web, AI chat). The server turns it into boxes; the template does the looks. */
export default function PasteZone({ sections, onInsert }: Props) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PasteResult | null>(null);
  const [where, setWhere] = useState<"root" | number>("root");
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");

  const run = async (payload: { text?: string; html?: string }) => {
    setBusy(true); setError(null);
    try {
      setResult(await post<PasteResult>("/api/paste/normalize", payload));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const html = e.clipboardData.getData("text/html");
    const plain = e.clipboardData.getData("text/plain");
    e.preventDefault();
    setText(plain.slice(0, 2000));
    void run({ html: html || undefined, text: plain });
  };

  const insert = () => {
    if (!result) return;
    onInsert(result.boxes, where, result.title);
    setResult(null); setText("");
  };

  const count = (bs: Box[]): { sections: number; tables: number; figures: number } =>
    bs.reduce((a, b) => {
      if (b.type === "section") { const c = count(b.content); return { sections: a.sections + 1 + c.sections, tables: a.tables + c.tables, figures: a.figures + c.figures }; }
      return { ...a, tables: a.tables + (b.type === "table" ? 1 : 0), figures: a.figures + (b.type === "figure" ? 1 : 0) };
    }, { sections: 0, tables: 0, figures: 0 });

  return (
    <div className="card space-y-3">
      <div>
        <h3 className="font-semibold">Paste content</h3>
        <p className="text-xs text-slate-500">
          Click the box and press Ctrl+V (⌘V). Headings, lists, tables, images and captions are recognised;
          fonts and colours are dropped because the template decides the look.
        </p>
      </div>
      <textarea className="input h-24 border-dashed" placeholder="Paste from Word, Google Docs, a web page or an AI chat here…"
        value={text} onPaste={onPaste} onChange={(e) => setText(e.target.value)} />
      {!result && text.trim() && !busy && (
        <button className="btn btn-sm" onClick={() => void run({ text })}>Analyse typed text</button>
      )}
      {busy && <p className="text-sm text-slate-500">Analysing…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {result && (() => {
        const c = count(result.boxes);
        return (
          <div className="space-y-2 rounded border border-indigo-200 bg-indigo-50 p-3 text-sm">
            <p>
              Found <b>{c.sections}</b> section(s), <b>{c.tables}</b> table(s), <b>{c.figures}</b> figure(s)
              {result.title && <> and a title: <i>{result.title}</i></>} (read as {result.source_format}).
            </p>
            {result.warnings.length > 0 && (
              <ul className="list-disc pl-5 text-xs text-amber-800">
                {result.warnings.map((w, i) => <li key={i}>{w.message}</li>)}
              </ul>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-xs">Insert into</label>
              <select className="input !w-auto" value={String(where)}
                onChange={(e) => setWhere(e.target.value === "root" ? "root" : Number(e.target.value))}>
                <option value="root">End of document</option>
                {sections.map((s, i) => <option key={i} value={i}>{"— ".repeat(s.depth - 1)}{s.title}</option>)}
              </select>
              <button className="btn btn-primary" onClick={insert}>Insert</button>
              <button className="btn" onClick={() => setResult(null)}>Discard</button>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
