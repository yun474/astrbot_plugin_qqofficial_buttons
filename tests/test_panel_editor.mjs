import assert from "node:assert/strict";
import test from "node:test";
import { itemProblem, panelTitle, rangeText, textWidth } from "../pages/button-studio/panel-editor.js";

test("字数按 QQ 规则计算：汉字算 2，英文算 1", () => {
  assert.equal(textWidth("/菜单"), 5);
  assert.equal(textWidth("help"), 4);
  assert.equal(textWidth(""), 0);
});

test("指令检查：空、超长、链接格式", () => {
  assert.equal(itemProblem({ type: "command", name: "/菜单", desc: "打开菜单" }), "");
  assert.match(itemProblem({ type: "command", name: " " }), /指令不能为空/);
  assert.match(itemProblem({ type: "command", name: "一二三四五六七八" }), /7 个汉字/);
  assert.match(itemProblem({ type: "command", name: "/a", desc: "字".repeat(16) }), /15 个汉字/);
  assert.match(itemProblem({ type: "link", name: "官网", link: "http://a.com" }), /https/);
  assert.equal(itemProblem({ type: "link", name: "官网", link: "https://a.com" }), "");
});

test("面板标题优先用备注，没有备注时列出前几条指令", () => {
  assert.equal(panelTitle({ panel: { remark: "主群", items: [] } }), "主群");
  assert.equal(panelTitle({ panel: { remark: "", items: [{ name: "/a" }, { name: "/b" }] } }), "/a、/b");
  assert.equal(panelTitle({ panel: {} }), "未命名面板");
});

test("生效范围文字：所有人、指定对象及数量", () => {
  assert.equal(rangeText({ target_type: "all", scope: "group" }), "所有人");
  assert.equal(rangeText({ target_type: "specific", scope: "group" }), "指定群");
  assert.equal(rangeText({ target_type: "specific", scope: "c2c", user_openids: ["u1", "u2"] }), "指定 2 个用户");
});
