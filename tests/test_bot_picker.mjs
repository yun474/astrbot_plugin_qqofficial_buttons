import assert from "node:assert/strict";
import test from "node:test";
import { botDetail, botTitle, chooseBot, createBotStore } from "../pages/button-studio/bot-picker.js";

const connected = { id: "bot-a", kind: "connected", appid: "1001", name: "qq_official" };
const manual = { id: "appid:2002", kind: "manual", appid: "2002", name: "测试号" };

test("机器人名称：已连接显示平台 ID，手动添加显示备注或 AppID", () => {
  assert.equal(botTitle(connected), "bot-a");
  assert.equal(botTitle(manual), "测试号");
  assert.equal(botTitle({ ...manual, name: "" }), "AppID 2002");
  assert.equal(botDetail(connected), "已连接 · AppID 1001");
  assert.equal(botDetail(manual), "手动添加 · AppID 2002");
});

test("记住的机器人还在就继续用，否则换成第一个", () => {
  assert.equal(chooseBot([connected, manual], "appid:2002"), "appid:2002");
  assert.equal(chooseBot([connected, manual], "gone"), "bot-a");
  assert.equal(chooseBot([], "gone"), "");
});

test("切换机器人前先问各页面，拒绝时保持不变", async () => {
  const store = createBotStore({ apiGet: async () => ({ bots: [connected, manual] }) });
  const changes = [];
  store.subscribe((changed) => changes.push(changed));
  await store.ensure();
  assert.equal(store.current, "bot-a");
  let allow = false;
  store.addGuard(async () => allow);
  assert.equal(await store.canLeave(), false);
  assert.equal(await store.select("appid:2002"), false);
  assert.equal(store.current, "bot-a");
  allow = true;
  assert.equal(await store.canLeave(), true);
  assert.equal(await store.select("appid:2002"), true);
  assert.equal(store.bot, manual);
  // 当前机器人被删除后自动换成剩下的第一个。
  store.update([connected]);
  assert.equal(store.current, "bot-a");
  assert.deepEqual(changes, [true, true, true]);
});
