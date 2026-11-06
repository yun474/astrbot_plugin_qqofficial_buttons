import assert from "node:assert/strict";
import test from "node:test";
import { mergeItems, previewItems, splitLines } from "../pages/button-studio/list-field.js";

test("批量导入按行拆分并去掉空行和首尾空白", () => {
  assert.deepEqual(splitLines(" /a \r\n\n/b\n"), ["/a", "/b"]);
});

test("追加条目去重，超出上限的部分不加入并计数", () => {
  assert.deepEqual(mergeItems(["a"], ["a", " b ", "", "c", "d"], 3), { items: ["a", "b", "c"], skipped: 1 });
});

test("预览最多显示 6 个标签，过长条目截断，其余合并为 +N", () => {
  const items = ["x".repeat(25), "2", "3", "4", "5", "6", "7", "8"];
  const { shown, more } = previewItems(items);
  assert.equal(shown.length, 6);
  assert.equal(shown[0], `${"x".repeat(20)}…`);
  assert.equal(more, 2);
});
