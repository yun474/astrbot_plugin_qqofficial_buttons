// “选择机器人”：素材库和指令面板共用一个当前机器人。
// 可选 AstrBot 里已连接的机器人，也可以手动填写 AppID 和密钥添加，交互参照“选择用户”弹窗。

const STORAGE_KEY = "qqbtn-current-bot";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

export function botTitle(bot) {
  if (!bot) return "未选择机器人";
  return bot.kind === "manual" ? bot.name || `AppID ${bot.appid}` : bot.id;
}

export function botDetail(bot) {
  if (!bot) return "";
  const kind = bot.kind === "manual" ? "手动添加" : "已连接";
  return bot.appid ? `${kind} · AppID ${bot.appid}` : kind;
}

// 记住的机器人还在列表里就继续用，否则换成第一个。
export function chooseBot(bots, preferred) {
  return bots.some((bot) => bot.id === preferred) ? preferred : (bots[0]?.id ?? "");
}

function readSaved() {
  try {
    return localStorage.getItem(STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function writeSaved(id) {
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // 浏览器禁用存储时只是下次打开不记得选择，不影响使用。
  }
}

export function createBotStore(bridge) {
  const listeners = new Set();
  const guards = new Set();
  const store = {
    bots: [],
    current: readSaved(),
    loaded: false,
    get bot() {
      return store.bots.find((bot) => bot.id === store.current) ?? null;
    },
    async refresh() {
      const result = await bridge.apiGet("bots/list");
      store.update(result.bots ?? []);
    },
    async ensure() {
      if (!store.loaded) await store.refresh();
    },
    update(bots) {
      store.bots = bots;
      store.loaded = true;
      const next = chooseBot(bots, store.current);
      const changed = next !== store.current;
      store.current = next;
      if (next) writeSaved(next);
      for (const listener of listeners) listener(changed);
    },
    // 切换前先问各页面能不能离开（比如指令面板有没保存的修改），返回是否切换成功。
    async select(id) {
      if (id === store.current) return true;
      for (const guard of guards) if (!(await guard())) return false;
      store.current = id;
      writeSaved(id);
      for (const listener of listeners) listener(true);
      return true;
    },
    subscribe(listener) {
      listeners.add(listener);
    },
    addGuard(guard) {
      guards.add(guard);
    },
  };
  return store;
}

// 把页面上的按钮变成“当前机器人”切换按钮，点开弹窗选择或添加。
export function mountBotButton(button, { bridge, store, toast, confirm }) {
  const render = () => {
    const bot = store.bot;
    button.replaceChildren(
      el("span", "bot-switch-icon", "🤖"),
      el("span", "bot-switch-name", bot ? botTitle(bot) : "选择机器人"),
      el("span", "bot-switch-arrow", "▾"),
    );
    button.title = bot ? `${botDetail(bot)}，点击切换机器人` : "还没有可用的机器人，点击手动添加";
  };
  store.subscribe(render);
  render();
  button.addEventListener("click", async () => {
    try {
      await store.ensure();
    } catch (error) {
      toast(`读取机器人列表失败：${error.message}`, true);
    }
    const id = await pickBot({ bridge, store, toast, confirm });
    if (id) await store.select(id);
  });
}

export function pickBot({ bridge, store, toast, confirm }) {
  let chosen = store.current;
  let busy = false;

  return new Promise((resolve) => {
    const overlay = el("div", "confirm-overlay");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    const panel = el("div", "confirm-card user-picker bot-picker");
    panel.append(
      el("h3", "", "选择机器人"),
      el("p", "user-picker-hint", "素材库和指令面板会操作这里选中的机器人。没有接入这个 AstrBot 的机器人，也可以填 AppID 和密钥手动添加。"),
    );

    const list = el("div", "user-picker-list bot-picker-list");

    const form = el("div", "bot-picker-form");
    const fields = {};
    for (const [key, label, type, placeholder, maxLength] of [
      ["appid", "AppID", "text", "机器人的 AppID（一串数字）", 32],
      ["secret", "AppSecret", "password", "机器人密钥", 128],
      ["remark", "备注", "text", "选填，比如“测试号”", 30],
    ]) {
      const wrap = el("label", "bot-picker-field");
      const input = el("input");
      input.type = type;
      input.placeholder = placeholder;
      input.maxLength = maxLength;
      input.autocomplete = type === "password" ? "new-password" : "off";
      wrap.append(el("span", "", label), input);
      fields[key] = input;
      form.append(wrap);
    }
    const addButton = el("button", "primary", "验证并添加");
    addButton.type = "button";
    form.append(addButton);

    const actions = el("div", "confirm-actions");
    const cancel = el("button", "", "取消");
    const ok = el("button", "primary", "确定");
    cancel.type = ok.type = "button";
    actions.append(cancel, ok);

    panel.append(
      el("p", "user-picker-heading", "机器人列表"),
      list,
      el("p", "user-picker-heading bot-picker-add-title", "手动添加机器人"),
      el(
        "p",
        "user-picker-hint",
        "填 QQ 开放平台“开发设置”里的 AppID 和 AppSecret，添加前会先向 QQ 验证。密钥只保存在 AstrBot 所在的机器上，页面不会再显示。手动添加的机器人只用来管理素材库和指令面板，不会收发消息。",
      ),
      form,
      actions,
    );
    overlay.append(panel);

    const close = (value) => {
      overlay.remove();
      document.removeEventListener("keydown", onKey);
      resolve(value);
    };
    const onKey = (event) => {
      if (event.key === "Escape" && !busy) close(null);
    };

    function render() {
      list.replaceChildren();
      if (!store.bots.length) {
        list.append(el("small", "user-picker-empty", "还没有可用的机器人。在 AstrBot 里连接 QQ 官方机器人，或在下面手动添加。"));
      }
      for (const bot of store.bots) {
        const row = el("label", "user-picker-item selectable");
        const radio = el("input");
        radio.type = "radio";
        radio.name = "bot-picker";
        radio.checked = bot.id === chosen;
        radio.addEventListener("change", () => {
          chosen = bot.id;
        });
        const text = el("div", "user-picker-text");
        text.append(el("strong", "", botTitle(bot)), el("small", "", botDetail(bot)));
        row.append(radio, text, el("span", `bot-picker-badge ${bot.kind}`, bot.kind === "manual" ? "手动" : "已连接"));
        if (bot.kind === "manual") {
          const remove = el("button", "user-picker-remove", "删除");
          remove.type = "button";
          remove.title = `删除 ${botTitle(bot)}`;
          remove.addEventListener("click", (event) => {
            event.preventDefault();
            removeBot(bot);
          });
          row.append(remove);
        }
        list.append(row);
      }
      ok.disabled = busy || !chosen;
      addButton.disabled = busy;
    }

    async function addBot() {
      const appid = fields.appid.value.trim();
      const secret = fields.secret.value.trim();
      if (!/^\d+$/.test(appid)) {
        toast("AppID 是一串数字，可以在 QQ 开放平台的开发设置里找到", true);
        fields.appid.focus();
        return;
      }
      if (!secret) {
        toast("请填写 AppSecret", true);
        fields.secret.focus();
        return;
      }
      busy = true;
      addButton.textContent = "验证中…";
      render();
      try {
        const result = await bridge.apiPost("bots/add", { appid, secret, remark: fields.remark.value.trim() });
        store.update(result.bots ?? []);
        chosen = result.bot?.id ?? chosen;
        for (const input of Object.values(fields)) input.value = "";
        toast("验证通过，机器人已添加");
      } catch (error) {
        toast(error.message, true);
      } finally {
        busy = false;
        addButton.textContent = "验证并添加";
        render();
      }
    }

    async function removeBot(bot) {
      if (busy) return;
      // 确认框打开期间也算忙，避免按 Esc 把选择弹窗一起关掉。
      busy = true;
      const accepted = await confirm(`确定删除机器人“${botTitle(bot)}”吗？只删除这里保存的 AppID 和密钥，QQ 上的数据不受影响。`);
      if (!accepted) {
        busy = false;
        return;
      }
      render();
      try {
        const result = await bridge.apiPost("bots/delete", { id: bot.id });
        store.update(result.bots ?? []);
        if (chosen === bot.id) chosen = store.current;
        toast("已删除");
      } catch (error) {
        toast(error.message, true);
      } finally {
        busy = false;
        render();
      }
    }

    addButton.addEventListener("click", addBot);
    for (const input of Object.values(fields)) {
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !busy) addBot();
      });
    }
    cancel.addEventListener("click", () => !busy && close(null));
    ok.addEventListener("click", () => chosen && close(chosen));
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay && !busy) close(null);
    });
    document.addEventListener("keydown", onKey);
    document.body.append(overlay);
    render();
  });
}
