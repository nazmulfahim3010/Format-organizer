import { useEffect, useRef, useState } from "react";
import { blobOf, upload } from "../api";
import {
  Path, addBox, indentBox, listAt, listToText, moveBox, newSection, outdentBox, removeBox, setBox, textToList, wrapSelection,
} from "../ops";
import { Box, FigureBox, ListBox, ParagraphBox, SectionBox, TableBox } from "../types";
import TableGrid from "./TableGrid";

interface ListProps {
  body: Box[];
  path: Path;
  onBody: (b: Box[]) => void;
}

const TYPE_LABEL: Record<Box["type"], string> = {
  section: "Section", paragraph: "Paragraph", list: "List", table: "Table", figure: "Figure",
};

/** Edits the list of boxes at `path`. Sections contain another BoxList, so nesting is unlimited. */
export default function BoxList({ body, path, onBody }: ListProps) {
  const boxes = listAt(body, path);
  const depth = path.length + 1;

  const add = (box: Box) => onBody(addBox(body, path, box));

  return (
    <div className="space-y-2">
      {boxes.map((box, i) => (
        <div key={i} className={`rounded-md border p-2 ${box.type === "section" ? "border-indigo-200 bg-indigo-50/40" : "border-slate-200 bg-white"}`}>
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {TYPE_LABEL[box.type]}{box.type === "section" ? ` · level ${depth}` : ""}
            </span>
            <div className="flex gap-1">
              <button className="btn btn-sm" title="Move up" disabled={i === 0} onClick={() => onBody(moveBox(body, path, i, -1))}>↑</button>
              <button className="btn btn-sm" title="Move down" disabled={i === boxes.length - 1} onClick={() => onBody(moveBox(body, path, i, 1))}>↓</button>
              <button className="btn btn-sm" title="Move into the section above" disabled={!(i > 0 && boxes[i - 1].type === "section")}
                onClick={() => onBody(indentBox(body, path, i))}>⇥</button>
              <button className="btn btn-sm" title="Move out of this section" disabled={path.length === 0}
                onClick={() => onBody(outdentBox(body, path, i))}>⇤</button>
              <button className="btn btn-sm btn-danger" title="Delete"
                onClick={() => { if (box.type !== "section" || box.content.length === 0 || confirm("Delete this section and everything inside it?")) onBody(removeBox(body, path, i)); }}>Delete</button>
            </div>
          </div>
          <BoxBody box={box} onChange={(b) => onBody(setBox(body, path, i, b))}>
            {box.type === "section" && <BoxList body={body} path={[...path, i]} onBody={onBody} />}
          </BoxBody>
        </div>
      ))}
      <div className="flex flex-wrap gap-1.5 pt-1">
        <span className="py-1 text-xs text-slate-500">Add:</span>
        <button className="btn btn-sm" onClick={() => add({ type: "paragraph", text: "" })}>+ Paragraph</button>
        <button className="btn btn-sm" onClick={() => add(newSection(""))}>+ {depth === 1 ? "Section" : "Subsection"}</button>
        <button className="btn btn-sm" onClick={() => add({ type: "list", ordered: false, items: [{ text: "", children: [] }] })}>+ List</button>
        <button className="btn btn-sm" onClick={() => add({ type: "table", caption: "", data: [["", ""], ["", ""]], header_rows: 1, note: "", source: "" })}>+ Table</button>
        <button className="btn btn-sm" onClick={() => add({ type: "figure", asset_id: null, caption: "", source: "" })}>+ Figure</button>
      </div>
    </div>
  );
}

function BoxBody({ box, onChange, children }: { box: Box; onChange: (b: Box) => void; children?: React.ReactNode }) {
  switch (box.type) {
    case "section": return <SectionEditor box={box} onChange={onChange}>{children}</SectionEditor>;
    case "paragraph": return <ParagraphEditor box={box} onChange={onChange} />;
    case "list": return <ListEditor box={box} onChange={onChange} />;
    case "table": return <TableEditor box={box} onChange={onChange} />;
    case "figure": return <FigureEditor box={box} onChange={onChange} />;
  }
}

function SectionEditor({ box, onChange, children }: { box: SectionBox; onChange: (b: Box) => void; children?: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <input className="input font-semibold" placeholder="Section title (numbering comes from the template)" value={box.title}
        onChange={(e) => onChange({ ...box, title: e.target.value })} />
      <div className="border-l-2 border-indigo-200 pl-3">{children}</div>
    </div>
  );
}

const MARKS: { label: string; marker: string; title: string; cls?: string }[] = [
  { label: "B", marker: "**", title: "Bold", cls: "font-bold" },
  { label: "I", marker: "*", title: "Italic", cls: "italic" },
  { label: "x²", marker: "^", title: "Superscript" },
  { label: "x₂", marker: "~", title: "Subscript" },
];

function ParagraphEditor({ box, onChange }: { box: ParagraphBox; onChange: (b: Box) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const wrap = (marker: string) => {
    if (!ref.current) return;
    onChange({ ...box, text: wrapSelection(ref.current, marker) });
  };
  return (
    <div className="space-y-1">
      <div className="flex gap-1">
        {MARKS.map((m) => (
          <button key={m.marker} className={`btn btn-sm ${m.cls || ""}`} title={m.title} onClick={() => wrap(m.marker)}>{m.label}</button>
        ))}
        <span className="py-0.5 text-[11px] text-slate-400">Fonts and sizes come from the template.</span>
      </div>
      <textarea ref={ref} dir="auto" className="input min-h-[80px]" placeholder="Write or paste text…" value={box.text}
        onChange={(e) => onChange({ ...box, text: e.target.value })} />
    </div>
  );
}

function ListEditor({ box, onChange }: { box: ListBox; onChange: (b: Box) => void }) {
  // Edited as text: one item per line, two spaces = one level deeper. Keep the raw text while typing.
  const [raw, setRaw] = useState(() => listToText(box.items));
  useEffect(() => {
    if (JSON.stringify(textToList(raw)) !== JSON.stringify(box.items)) setRaw(listToText(box.items));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [box.items]);
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-3 text-sm">
        <label className="flex items-center gap-1"><input type="radio" checked={!box.ordered} onChange={() => onChange({ ...box, ordered: false })} /> Bullets</label>
        <label className="flex items-center gap-1"><input type="radio" checked={box.ordered} onChange={() => onChange({ ...box, ordered: true })} /> Numbers</label>
        <span className="text-[11px] text-slate-400">One item per line · indent 2 spaces for a sub-point</span>
      </div>
      <textarea dir="auto" className="input min-h-[90px] font-mono" value={raw}
        onChange={(e) => { setRaw(e.target.value); onChange({ ...box, items: textToList(e.target.value) }); }} />
    </div>
  );
}

function TableEditor({ box, onChange }: { box: TableBox; onChange: (b: Box) => void }) {
  return (
    <div className="space-y-2">
      <input className="input" placeholder="Caption (the number “Table 1” is added automatically)" value={box.caption}
        onChange={(e) => onChange({ ...box, caption: e.target.value })} />
      <TableGrid box={box} onChange={onChange} />
      <div className="grid gap-2 sm:grid-cols-2">
        <input className="input" placeholder="Source (optional)" value={box.source} onChange={(e) => onChange({ ...box, source: e.target.value })} />
        <input className="input" placeholder="Note (optional)" value={box.note} onChange={(e) => onChange({ ...box, note: e.target.value })} />
      </div>
      <p className="text-[11px] text-slate-400">Borders, shading, widths and caption position are locked by the template's table rule.</p>
    </div>
  );
}

function AuthImage({ assetId }: { assetId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let revoked = false, made: string | null = null;
    blobOf(`/api/media/${assetId}`, "GET").then((b) => {
      if (revoked) return;
      made = URL.createObjectURL(b); setUrl(made);
    }).catch(() => setUrl(null));
    return () => { revoked = true; if (made) URL.revokeObjectURL(made); };
  }, [assetId]);
  return url ? <img src={url} alt="" className="max-h-40 rounded border border-slate-200" /> : <div className="h-20 w-32 rounded bg-slate-100" />;
}

function FigureEditor({ box, onChange }: { box: FigureBox; onChange: (b: Box) => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pick = async (f: File | undefined) => {
    if (!f) return;
    setBusy(true); setErr(null);
    try {
      const r = await upload<{ asset_id: string }>("/api/media/upload", f);
      onChange({ ...box, asset_id: r.asset_id, src: null });
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <div className="space-y-2">
      <div className="flex items-start gap-3">
        {box.asset_id ? <AuthImage assetId={box.asset_id} /> : (
          <div className="flex h-20 w-32 items-center justify-center rounded border border-dashed border-slate-300 text-xs text-slate-400">No image</div>
        )}
        <div className="space-y-1">
          <input type="file" accept="image/png,image/jpeg,image/gif,image/webp,image/bmp,image/tiff" disabled={busy}
            onChange={(e) => void pick(e.target.files?.[0])} className="text-sm" />
          {err && <p className="text-xs text-red-600">{err}</p>}
          <p className="text-[11px] text-slate-400">Size, alignment and caption position are locked by the template's figure rule.</p>
        </div>
      </div>
      <input className="input" placeholder="Caption (the number “Figure 1” is added automatically)" value={box.caption}
        onChange={(e) => onChange({ ...box, caption: e.target.value })} />
      <input className="input" placeholder="Source (optional)" value={box.source} onChange={(e) => onChange({ ...box, source: e.target.value })} />
    </div>
  );
}
