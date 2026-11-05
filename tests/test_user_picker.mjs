import assert from "node:assert/strict";
import test from "node:test";
import { senderSource, senderTitle } from "../pages/button-studio/user-picker.js";

test("用户标题有昵称时附带 ID，没有昵称时只显示 ID", () => {
  assert.equal(senderTitle({ sender_id: "u1", sender_name: "小明" }), "小明（u1）");
  assert.equal(senderTitle({ sender_id: "u1", sender_name: "" }), "u1");
});

test("来源优先显示群名，没有记录时提示来源未知", () => {
  assert.equal(senderSource({ group: true, session_name: "测试群", umo: "qq:GroupMessage:g" }), "群聊 · 测试群");
  assert.equal(senderSource({ group: false, session_name: "", umo: "qq:FriendMessage:u" }), "私聊 · qq:FriendMessage:u");
  assert.equal(senderSource(undefined), "暂无记录，来源未知");
});

test("图片地址按前缀归到对应来源", async () => {
  globalThis.document ??= { querySelector: () => null, querySelectorAll: () => [] };
  const { sourceOf } = await import("../pages/button-studio/image-source.js");
  assert.equal(sourceOf("local://a.png"), "local");
  assert.equal(sourceOf("qqbot-media://image/v1/t"), "media");
  assert.equal(sourceOf("https://example.com/a.png"), "url");
  assert.equal(sourceOf(""), "url");
});

test("素材到期状态：已过期、即将过期和正常", async () => {
  const { expiryText } = await import("../pages/button-studio/media-picker.js");
  const now = 1_800_000_000;
  assert.deepEqual(expiryText(now - 1, now), { text: "已过期", level: "expired" });
  assert.equal(expiryText(now + 3600, now).level, "soon");
  assert.equal(expiryText(now + 30 * 86400, now).level, "");
  assert.equal(expiryText(0, now).text, "到期时间未知");
});
