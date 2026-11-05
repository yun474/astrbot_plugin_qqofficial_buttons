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
