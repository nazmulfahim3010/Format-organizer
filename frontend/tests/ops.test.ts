// Unit tests for the pure editing helpers. Run: npm test (bundled with esbuild, run by node:test).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  indentBox, listToText, moveBox, newSection, outdentBox, parseTsv, removeBox, textToList, wrapText,
} from "../src/ops";
import { Box } from "../src/types";

test("wrapText keeps edge spaces outside the markers", () => {
  assert.equal(wrapText("a word here", 1, 7, "**"), "a **word** here");
  assert.equal(wrapText("abc", 1, 1, "*"), "a*text*bc");                       // empty selection
  assert.equal(wrapText("x  ", 0, 3, "*"), "*x*  ");
});

test("wrapText escapes spaces inside sup/sub", () => {
  assert.equal(wrapText("1st place", 0, 9, "^"), "^1st\\ place^");
});

test("parseTsv handles Excel quoting, CRLF, empty cells and doubled quotes", () => {
  const text = 'Item\tQty\tNotes\r\nPens\t12\t"blue and\r\nblack"\r\nPaper\t500\t\r\nInk\t\t"out of ""stock"""\r\n';
  assert.deepEqual(parseTsv(text), [
    ["Item", "Qty", "Notes"], ["Pens", "12", "blue and\nblack"], ["Paper", "500", ""], ["Ink", "", 'out of "stock"'],
  ]);
  assert.deepEqual(parseTsv("\tQ1\nNorth\t5"), [["", "Q1"], ["North", "5"]]);
  assert.deepEqual(parseTsv('say "hi"\tx'), [['say "hi"', "x"]]);            // quotes mid-cell are literal
});

test("list text round trip with nesting", () => {
  const items = textToList("a\n  a1\n    a1x\nb");
  assert.equal(listToText(items), "a\n  a1\n    a1x\nb");
  assert.deepEqual(textToList("a\n      jump"), [{ text: "a", children: [{ text: "jump", children: [] }] }]);
});

test("indent and outdent move a box into and out of the section above", () => {
  const s = newSection("S");
  const body: Box[] = [s, { type: "paragraph", text: "p" }];
  const indented = indentBox(body, [], 1);
  assert.equal(indented.length, 1);
  assert.equal((indented[0] as typeof s).content[0].type, "paragraph");
  const back = outdentBox(indented, [0], 0);
  assert.deepEqual(back.map((b) => b.type), ["section", "paragraph"]);
});

test("move and remove do not mutate the input", () => {
  const body: Box[] = [{ type: "paragraph", text: "1" }, { type: "paragraph", text: "2" }];
  const moved = moveBox(body, [], 0, 1);
  assert.deepEqual(moved.map((b) => (b as { text: string }).text), ["2", "1"]);
  assert.deepEqual(body.map((b) => (b as { text: string }).text), ["1", "2"]);
  assert.equal(removeBox(body, [], 0).length, 1);
});
