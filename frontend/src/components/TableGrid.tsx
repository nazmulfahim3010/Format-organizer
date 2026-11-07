import { parseTsv } from "../ops";
import { TableBox } from "../types";

interface Props { box: TableBox; onChange: (b: TableBox) => void }

const blank = (rows: number, cols: number) => Array.from({ length: rows }, () => Array<string>(cols).fill(""));

export default function TableGrid({ box, onChange }: Props) {
  const data = box.data.length ? box.data : blank(2, 2);
  const rows = data.length, cols = data[0].length;
  const set = (data2: string[][]) => onChange({ ...box, data: data2 });

  const setCell = (r: number, c: number, v: string) =>
    set(data.map((row, ri) => (ri === r ? row.map((x, ci) => (ci === c ? v : x)) : row)));

  // Pasting tab/newline separated text (e.g. from Excel) fills the grid from the active cell.
  const paste = (e: React.ClipboardEvent<HTMLTextAreaElement>, r: number, c: number) => {
    const text = e.clipboardData.getData("text/plain");
    if (!text.includes("\t") && !text.includes("\n")) return;
    e.preventDefault();
    const lines = parseTsv(text);       // Excel quotes cells that contain tabs, line breaks or quotes
    if (!lines.length) return;
    const needRows = Math.max(rows, r + lines.length);
    const needCols = Math.max(cols, c + Math.max(...lines.map((l) => l.length)));
    const grid = blank(needRows, needCols).map((row, ri) => row.map((_, ci) => data[ri]?.[ci] ?? ""));
    lines.forEach((l, i) => l.forEach((v, j) => { grid[r + i][c + j] = v; }));
    set(grid);
  };

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="border-collapse text-sm">
          <tbody>
            {data.map((row, r) => (
              <tr key={r} className={r < box.header_rows ? "bg-slate-100" : ""}>
                {row.map((cell, c) => (
                  <td key={c} className="border border-slate-300 p-0">
                    {/* a textarea, so a line break inside a cell (Excel Alt+Enter) survives editing */}
                    <textarea rows={Math.max(1, cell.split("\n").length)} dir="auto"
                      className="block w-28 resize-none bg-transparent px-1.5 py-1 outline-none focus:bg-indigo-50" value={cell}
                      onChange={(e) => setCell(r, c, e.target.value)} onPaste={(e) => paste(e, r, c)}
                      aria-label={`row ${r + 1} column ${c + 1}`} />
                  </td>
                ))}
                <td className="pl-1">
                  <button className="btn btn-sm btn-danger" title="Delete row" disabled={rows <= 1}
                    onClick={() => set(data.filter((_, i) => i !== r))}>×</button>
                </td>
              </tr>
            ))}
            <tr>
              {data[0].map((_, c) => (
                <td key={c} className="pt-1 text-center">
                  <button className="btn btn-sm btn-danger" title="Delete column" disabled={cols <= 1}
                    onClick={() => set(data.map((row) => row.filter((_, i) => i !== c)))}>×</button>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <button className="btn btn-sm" onClick={() => set([...data, Array<string>(cols).fill("")])}>+ Row</button>
        <button className="btn btn-sm" onClick={() => set(data.map((row) => [...row, ""]))}>+ Column</button>
        <label className="ml-2 flex items-center gap-1 text-xs text-slate-600">
          Header rows
          <input type="number" min={0} max={rows} className="input !w-14" value={box.header_rows}
            onChange={(e) => onChange({ ...box, header_rows: Math.max(0, Math.min(rows, Number(e.target.value) || 0)) })} />
        </label>
        <span className="text-xs text-slate-400">Tip: paste from Excel into any cell.</span>
      </div>
    </div>
  );
}
