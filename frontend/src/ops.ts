// Pure helpers for editing the box tree immutably. A "path" is the list of
// section indices leading to a list of boxes ([] = the document body).
import { Box, ListItem, SectionBox } from "./types";

export type Path = number[];

export const uid = () => "s-" + Math.random().toString(36).slice(2, 9);
export const newSection = (title = ""): SectionBox => ({ type: "section", id: uid(), title, content: [] });

export function listAt(body: Box[], path: Path): Box[] {
  let list = body;
  for (const i of path) {
    const b = list[i];
    if (!b || b.type !== "section") return [];
    list = b.content;
  }
  return list;
}

export function updateList(body: Box[], path: Path, fn: (l: Box[]) => Box[]): Box[] {
  if (path.length === 0) return fn(body);
  const [head, ...rest] = path;
  return body.map((b, i) => (i === head && b.type === "section" ? { ...b, content: updateList(b.content, rest, fn) } : b));
}

export const setBox = (body: Box[], path: Path, i: number, box: Box) =>
  updateList(body, path, (l) => l.map((b, k) => (k === i ? box : b)));
export const removeBox = (body: Box[], path: Path, i: number) =>
  updateList(body, path, (l) => l.filter((_, k) => k !== i));
export const addBox = (body: Box[], path: Path, box: Box) => updateList(body, path, (l) => [...l, box]);
export const insertBoxes = (body: Box[], path: Path, boxes: Box[]) => updateList(body, path, (l) => [...l, ...boxes]);

export function moveBox(body: Box[], path: Path, i: number, delta: -1 | 1): Box[] {
  return updateList(body, path, (l) => {
    const j = i + delta;
    if (j < 0 || j >= l.length) return l;
    const copy = [...l];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    return copy;
  });
}

/** Move box i into the previous sibling section (as its last child). */
export function indentBox(body: Box[], path: Path, i: number): Box[] {
  const list = listAt(body, path);
  const prev = list[i - 1];
  if (i === 0 || !prev || prev.type !== "section") return body;
  const box = list[i];
  return updateList(removeBox(body, path, i), [...path, i - 1], (l) => [...l, box]);
}

/** Move box i out of its section, to just after that section in the parent list. */
export function outdentBox(body: Box[], path: Path, i: number): Box[] {
  if (path.length === 0) return body;
  const box = listAt(body, path)[i];
  const parent = path.slice(0, -1);
  const at = path[path.length - 1];
  return updateList(removeBox(body, path, i), parent, (l) => [...l.slice(0, at + 1), box, ...l.slice(at + 1)]);
}

export interface FlatSection { path: Path; title: string; depth: number }
export function flatSections(body: Box[], base: Path = [], depth = 1): FlatSection[] {
  const out: FlatSection[] = [];
  body.forEach((b, i) => {
    if (b.type === "section") {
      const p = [...base, i];
      out.push({ path: p, title: b.title || "(untitled)", depth });
      out.push(...flatSections(b.content, p, depth + 1));
    }
  });
  return out;
}

// --- list <-> text (two spaces of indentation = one nesting level) -----------------
export function listToText(items: ListItem[], level = 0): string {
  return items.map((it) => "  ".repeat(level) + it.text + (it.children.length ? "\n" + listToText(it.children, level + 1) : "")).join("\n");
}
export function textToList(text: string): ListItem[] {
  const root: ListItem[] = [];
  const stack: { level: number; children: ListItem[] }[] = [{ level: -1, children: root }];
  let prev = -1;
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let level = Math.floor((line.match(/^ */)![0].length) / 2);
    level = Math.min(level, prev + 1);
    while (stack[stack.length - 1].level >= level) stack.pop();
    const item: ListItem = { text: line.trim(), children: [] };
    stack[stack.length - 1].children.push(item);
    stack.push({ level, children: item.children });
    prev = level;
  }
  return root;
}

// --- inline markup helper: wrap selected text with **, *, ^ or ~ -----------------
// Markers only format when they touch non-space text (see backend app/core/inline.py), so spaces at
// the edges of the selection stay outside the markers; ^ and ~ may not contain spaces at all.
export function wrapText(value: string, s: number, e: number, marker: string): string {
  let a = s, b = e;
  while (a < b && /\s/.test(value[a])) a++;
  while (b > a && /\s/.test(value[b - 1])) b--;
  let sel = value.slice(a, b) || "text";
  if (marker === "^" || marker === "~") sel = sel.replace(/ /g, "\\ ");
  return value.slice(0, a) + marker + sel + marker + value.slice(b);
}
export function wrapSelection(el: HTMLTextAreaElement, marker: string): string {
  return wrapText(el.value, el.selectionStart, el.selectionEnd, marker);
}

/** Tab-separated clipboard text from Excel / Sheets: cells with tabs, line breaks or quotes are
 *  quoted, and quotes inside are doubled. Returns rows of cells. */
export function parseTsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false, i = 0;
  const src = text.replace(/\r\n?/g, "\n");
  while (i < src.length) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') { cell += '"'; i += 2; continue; }
      if (ch === '"') { quoted = false; i++; continue; }
      cell += ch; i++; continue;
    }
    if (ch === '"' && cell === "") { quoted = true; i++; continue; }
    if (ch === "\t") { row.push(cell); cell = ""; i++; continue; }
    if (ch === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; i++; continue; }
    cell += ch; i++;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

export function countBoxes(body: Box[]): number {
  return body.reduce((n, b) => n + 1 + (b.type === "section" ? countBoxes(b.content) : 0), 0);
}
