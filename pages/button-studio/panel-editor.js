// 指令面板视图：管理 QQ 官方指令面板（用户输入 / 弹出的指令列表），数据直接读写 QQ 服务器。
import { mountBotButton } from "./bot-picker.js";
import { createListField } from "./list-field.js";
import { pickUsers } from "./user-picker.js";

const $ = (selector) => document.querySelector(selector);

export const SCOPE_LABELS = { c2c: "单聊", group: "群聊", channel: "文字子频道", dm: "频道私信" };
const SCOPE_ORDER = ["group", "c2c", "channel", "dm"];
const SCOPE_ICONS = { c2c: "☺", group: "☷", channel: "#", dm: "✉" };
// 只有单聊和群聊能指定生效对象。
const TARGET_SCOPES = { c2c: "用户", group: "群" };
const DEFAULT_LIMITS = { max_panels: 20, max_items: 20, name_width: 14, desc_width: 30, remark_width: 255 };

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

// 与 QQ 一致：ASCII 字符算 1，汉字等其他字符算 2。
export function textWidth(text) {
  let width = 0;
  for (const char of String(text ?? "")) width += char.codePointAt(0) < 128 ? 1 : 2;
  return width;
}

// 返回第一处问题的说明，没有问题返回空字符串。
export function itemProblem(item, limits = DEFAULT_LIMITS) {
  const name = String(item.name ?? "").trim();
  const label = item.type === "link" ? "名称" : "指令";
  if (!name) return `${label}不能为空`;
  if (textWidth(name) > limits.name_width) return `${label}最多 ${limits.name_width / 2} 个汉字或 ${limits.name_width} 个英文字符`;
  if (textWidth(String(item.desc ?? "").trim()) > limits.desc_width) {
    return `说明最多 ${limits.desc_width / 2} 个汉字或 ${limits.desc_width} 个英文字符`;
  }
  if (item.type === "link" && !String(item.link ?? "").trim().startsWith("https://")) return "链接需要以 https:// 开头";
  return "";
}

export function panelTitle(record) {
  const remark = String(record.panel?.remark ?? "").trim();
  if (remark) return remark;
  const names = (record.panel?.items ?? []).map((item) => item.name).filter(Boolean);
  return names.length ? names.slice(0, 3).join("、") : "未命名面板";
}

export function rangeText(record) {
  if (record.target_type !== "specific") return "所有人";
  const count = (record.user_openids ?? record.group_openids)?.length;
  const noun = TARGET_SCOPES[record.scope] ?? "对象";
  return count === undefined ? `指定${noun}` : `指定 ${count} 个${noun}`;
}

function counterInput(input, limit, counter) {
  const update = () => {
    const width = textWidth(input.value);
    counter.textContent = `${width}/${limit}`;
    counter.classList.toggle("over", width > limit);
  };
  input.addEventListener("input", update);
  update();
}

// 仿官网的“添加指令”弹窗，确定返回指令，取消返回 null。
function editItemDialog(item, { limits, count }) {
  const draft = { type: "command", name: "", desc: "", only_admin: false, link: "", ...item };
  return new Promise((resolve) => {
    const overlay = el("div", "confirm-overlay");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    const card = el("div", "confirm-card cp-dialog");
    const head = el("div", "cp-dialog-head");
    head.append(el("h3", "", item ? "编辑指令" : "添加指令"), el("p", "", "设置展示在机器人指令面板中的快捷能力。"));

    const typeLabel = el("span", "field-label", "触发方式");
    const types = el("div", "cp-type-cards");
    const typeButtons = {};
    for (const [value, title, hint, icon] of [
      ["command", "发送指令", "点击后把指令填进输入框", "💬"],
      ["link", "打开页面", "跳转到 HTTPS 服务页", "🔗"],
    ]) {
      const button = el("button", "cp-type-card");
      button.type = "button";
      const text = el("span", "cp-type-text");
      text.append(el("strong", "", title), el("small", "", hint));
      button.append(el("span", "cp-type-icon", icon), text);
      button.addEventListener("click", () => {
        draft.type = value;
        render();
      });
      typeButtons[value] = button;
      types.append(button);
    }

    const field = (labelText, control, limit) => {
      const wrap = el("label", "cp-dialog-field");
      const top = el("span", "cp-field-top");
      top.append(el("span", "", labelText));
      if (limit) {
        const counter = el("small", "cp-counter");
        top.append(counter);
        counterInput(control, limit, counter);
      }
      wrap.append(top, control);
      return wrap;
    };
    const name = el("input");
    name.value = draft.name;
    name.maxLength = 64;
    const nameField = field("指令", name, limits.name_width);
    const link = el("input");
    link.value = draft.link;
    link.maxLength = 1000;
    link.placeholder = "https://example.com";
    const linkField = field("页面链接", link);
    const desc = el("textarea");
    desc.value = draft.desc;
    desc.rows = 3;
    desc.maxLength = 64;
    desc.placeholder = "简要说明这条指令能做什么";
    const descField = field("功能说明", desc, limits.desc_width);
    const admin = el("label", "switch-line cp-admin");
    const adminBox = el("input");
    adminBox.type = "checkbox";
    adminBox.checked = Boolean(draft.only_admin);
    admin.append(adminBox, el("span", "", "仅群主、群管理员和频道管理员可点击"));
    const problem = el("small", "cp-problem");

    const foot = el("div", "cp-dialog-foot");
    const used = el("small", "", `当前已添加 ${count}/${limits.max_items} 条`);
    const actions = el("div", "confirm-actions");
    const cancel = el("button", "", "取消");
    const confirm = el("button", "primary", item ? "确定" : "添加");
    cancel.type = confirm.type = "button";
    actions.append(cancel, confirm);
    foot.append(used, actions);

    card.append(head, typeLabel, types, nameField, linkField, descField, admin, problem, foot);
    overlay.append(card);

    const collect = () => ({
      type: draft.type,
      name: name.value.trim(),
      desc: desc.value.trim(),
      only_admin: adminBox.checked,
      ...(draft.type === "link" ? { link: link.value.trim() } : {}),
    });
    function render() {
      for (const [value, button] of Object.entries(typeButtons)) button.classList.toggle("active", value === draft.type);
      const isLink = draft.type === "link";
      nameField.querySelector(".cp-field-top > span").textContent = isLink ? "名称" : "指令";
      name.placeholder = isLink ? "例如：使用帮助" : "例如：/菜单";
      linkField.classList.toggle("hidden", !isLink);
      problem.textContent = "";
    }
    const close = (value) => {
      overlay.remove();
      document.removeEventListener("keydown", onKey, true);
      resolve(value);
    };
    // 捕获阶段处理 Esc，避免同时触发工作台的确认框逻辑。
    const onKey = (event) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      close(null);
    };
    confirm.addEventListener("click", () => {
      const result = collect();
      const message = itemProblem(result, limits);
      if (message) {
        problem.textContent = message;
        return;
      }
      close(result);
    });
    cancel.addEventListener("click", () => close(null));
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close(null);
    });
    document.addEventListener("keydown", onKey, true);
    document.body.append(overlay);
    render();
    name.focus();
  });
}

export function createPanelEditor({ bridge, toast, confirm, bots }) {
  const state = {
    // 列表对应的机器人；在素材库切换机器人后，回到这里时据此重新加载。
    bot: null,
    limits: { ...DEFAULT_LIMITS },
    scopes: {},
    selected: "",
    draft: null,
    original: "",
    loaded: false,
    loading: true,
    busy: false,
  };

  const targetsField = createListField($("#cp-targets"), {
    title: "指定对象",
    placeholder: "OpenID",
    emptyText: "还没有添加，至少需要一个",
    maxItems: 1000,
    maxLength: 128,
    onChange: (items) => {
      if (!state.draft) return;
      state.draft.targets = items;
      renderEditor();
    },
  });
  const pickTargets = el("button", "", "选择");
  pickTargets.type = "button";
  targetsField.actions.append(pickTargets);

  const records = () => SCOPE_ORDER.flatMap((scope) => state.scopes[scope]?.records ?? []);
  const isDirty = () => Boolean(state.draft) && JSON.stringify(state.draft) !== state.original;

  function setBusy(busy) {
    state.busy = busy;
    // 请求期间暂停编辑，避免保存响应覆盖刚输入的修改。
    $("#cp-editor").inert = busy;
    // 读取和保存期间也不能切换机器人，避免结果落到另一个机器人下面。
    for (const id of ["#cp-save", "#cp-save-bar-button", "#cp-delete", "#cp-new", "#cp-refresh", "#cp-bot"]) $(id).disabled = busy;
  }

  async function canLeave() {
    return !state.busy && (!isDirty() || (await confirm("当前面板有未保存到 QQ 的修改，确定放弃吗？")));
  }

  function draftFrom(record) {
    const scope = record.scope;
    return {
      panel_id: record.panel_id,
      scope,
      target_type: record.target_type === "specific" ? "specific" : "all",
      targets: [...(scope === "c2c" ? record.user_openids ?? [] : record.group_openids ?? [])],
      remark: record.panel?.remark ?? "",
      items: (record.panel?.items ?? []).map((item) => ({
        type: item.type === "link" ? "link" : "command",
        name: item.name ?? "",
        desc: item.desc ?? "",
        only_admin: Boolean(item.only_admin),
        ...(item.type === "link" ? { link: item.link ?? "" } : {}),
      })),
    };
  }

  function setDraft(draft) {
    state.draft = draft;
    state.original = draft ? JSON.stringify(draft) : "";
    renderAll();
  }

  function renderList() {
    const list = $("#cp-list");
    list.replaceChildren();
    if (state.draft && !state.draft.panel_id) {
      const item = el("button", "preset-item active");
      item.type = "button";
      const copy = el("span", "preset-copy");
      copy.append(el("strong", "", "新面板（未保存）"), el("small", "", `${SCOPE_LABELS[state.draft.scope]} · 保存后创建`));
      item.append(el("span", "preset-icon", "＋"), copy);
      list.append(item);
    }
    for (const scope of SCOPE_ORDER) {
      const info = state.scopes[scope];
      if (!info) continue;
      if (!info.records.length && !info.error) continue;
      list.append(el("p", "cp-group-title", SCOPE_LABELS[scope]));
      if (info.error) list.append(el("p", "cp-group-error", info.error));
      for (const record of info.records) {
        const item = el("button", "preset-item");
        item.type = "button";
        item.classList.toggle("active", record.panel_id === state.selected);
        const copy = el("span", "preset-copy");
        const count = record.panel?.items?.length ?? 0;
        copy.append(el("strong", "", panelTitle(record)), el("small", "", `${rangeText(record)} · ${count} 条指令`));
        item.append(el("span", "preset-icon", SCOPE_ICONS[scope]), copy);
        item.title = `面板 ID：${record.panel_id}`;
        item.addEventListener("click", () => selectPanel(record.panel_id));
        list.append(item);
      }
    }
    if (!list.children.length) {
      const text = state.loading
        ? "正在读取……"
        : state.bot
          ? "这个机器人还没有指令面板。"
          : "还没有可用的机器人。在 AstrBot 里连接 QQ 官方机器人，或点上方“选择机器人”手动添加。";
      list.append(el("p", "cp-group-error muted", text));
    }
    const total = records().length;
    const partial = SCOPE_ORDER.some((scope) => state.scopes[scope]?.error);
    $("#cp-side-hint").textContent =
      `用户在 QQ 里输入“/”会弹出指令面板。面板保存在 QQ 服务器上，当前 ${total}${partial ? "+" : ""} / ${state.limits.max_panels} 个。`;
    $("#cp-new").disabled = state.busy || !state.bot || total >= state.limits.max_panels;
  }

  function renderItems() {
    const box = $("#cp-items");
    box.replaceChildren();
    const items = state.draft.items;
    $("#cp-count").textContent = `${items.length} / ${state.limits.max_items}`;
    $("#cp-add-item").disabled = items.length >= state.limits.max_items;
    if (!items.length) {
      const empty = el("button", "cp-items-empty");
      empty.type = "button";
      empty.append(el("span", "cp-empty-plus", "＋"), el("strong", "", "添加第一条指令"), el("small", "", "支持发送预设指令或打开 HTTPS 网页服务页面"));
      empty.addEventListener("click", addItem);
      box.append(empty);
      return;
    }
    items.forEach((item, index) => {
      const row = el("div", "cp-item");
      const text = el("div", "cp-item-text");
      const title = el("strong", "", item.name);
      if (item.only_admin) title.append(el("span", "cp-tag", "仅管理员"));
      if (item.type === "link") title.append(el("span", "cp-tag link", "打开页面"));
      text.append(title, el("small", "", item.type === "link" ? `${item.desc || "无说明"} · ${item.link}` : item.desc || "无说明"));
      const tools = el("div", "cp-item-tools");
      for (const [label, action, disabled] of [
        ["↑", () => moveItem(index, -1), index === 0],
        ["↓", () => moveItem(index, 1), index === items.length - 1],
        ["编辑", () => editItem(index), false],
        ["删除", () => removeItem(index), false],
      ]) {
        const button = el("button", label === "删除" ? "danger" : "", label);
        button.type = "button";
        button.disabled = disabled;
        button.addEventListener("click", action);
        tools.append(button);
      }
      row.append(el("span", "cp-item-icon", item.type === "link" ? "🔗" : "💬"), text, tools);
      box.append(row);
    });
  }

  function renderEditor() {
    const draft = state.draft;
    const has = Boolean(draft);
    $("#cp-empty").classList.toggle("hidden", has);
    $("#cp-editor").classList.toggle("hidden", !has);
    $("#cp-save").classList.toggle("hidden", !has);
    $("#cp-delete").classList.toggle("hidden", !draft?.panel_id);
    const dirty = isDirty();
    $("#cp-save-bar").classList.toggle("hidden", !dirty);
    $("#cp-save-state").textContent = has ? (dirty ? "未保存" : "已同步") : "";
    $("#cp-save-state").classList.toggle("dirty", dirty);
    if (!has) {
      $("#cp-title").textContent = "指令面板";
      $("#cp-subtitle").textContent = "在左边选一个面板，或者新建一个。";
      return;
    }
    const existing = Boolean(draft.panel_id);
    $("#cp-title").textContent = existing ? panelTitle({ panel: draft }) : "新建指令面板";
    $("#cp-subtitle").textContent = existing ? `面板 ID：${draft.panel_id}` : "填好后点“保存到 QQ”创建。";
    const scope = $("#cp-scope");
    const targetType = $("#cp-target-type");
    scope.value = draft.scope;
    targetType.value = draft.target_type;
    // 场景和生效范围创建后不能修改；频道和频道私信只能对所有人生效。
    scope.disabled = existing;
    targetType.disabled = existing || !TARGET_SCOPES[draft.scope];
    $("#cp-scope-hint").textContent = existing
      ? "场景和生效范围创建后不能修改，想换的话请新建一个面板。指定对象可以随时增删。"
      : "选择面板在哪种会话里出现、对谁出现。创建后场景和范围不能再改。";
    const specific = draft.target_type === "specific";
    $("#cp-targets-wrap").classList.toggle("hidden", !specific);
    if (specific) {
      const noun = TARGET_SCOPES[draft.scope];
      $("#cp-targets-label").textContent = `指定${noun}（${draft.targets.length} 个）`;
      $("#cp-targets-hint").textContent =
        draft.scope === "group"
          ? "填群的 OpenID，可点“选择”从这个机器人待过的群里挑。"
          : "填用户的 OpenID，可点“选择”从和这个机器人私聊过的用户里挑。群聊里的用户 ID 和私聊的不一样，不能混用。";
      pickTargets.textContent = `选择${noun}`;
      targetsField.set(draft.targets);
    }
    const remark = $("#cp-remark");
    if (remark.value !== draft.remark) remark.value = draft.remark;
    renderItems();
  }

  function renderAll() {
    renderList();
    renderEditor();
  }

  async function addItem() {
    if (!state.draft || state.draft.items.length >= state.limits.max_items) return;
    const item = await editItemDialog(null, { limits: state.limits, count: state.draft.items.length });
    if (!item) return;
    if (state.draft.items.some((other) => other.name === item.name)) {
      toast(`指令“${item.name}”已经在列表里了`, true);
      return;
    }
    state.draft.items.push(item);
    renderEditor();
  }

  async function editItem(index) {
    const item = await editItemDialog(state.draft.items[index], { limits: state.limits, count: state.draft.items.length });
    if (!item) return;
    if (state.draft.items.some((other, i) => i !== index && other.name === item.name)) {
      toast(`指令“${item.name}”已经在列表里了`, true);
      return;
    }
    state.draft.items[index] = item;
    renderEditor();
  }

  function moveItem(index, offset) {
    const items = state.draft.items;
    const target = index + offset;
    if (target < 0 || target >= items.length) return;
    [items[index], items[target]] = [items[target], items[index]];
    renderEditor();
  }

  async function removeItem(index) {
    const item = state.draft.items[index];
    if (!(await confirm(`确定删除指令“${item.name}”吗？保存到 QQ 后生效。`))) return;
    state.draft.items.splice(index, 1);
    renderEditor();
  }

  async function loadList() {
    state.loading = true;
    state.bot = bots.current;
    if (!state.bot) {
      state.scopes = {};
      state.loading = false;
      renderAll();
      return;
    }
    const bot = state.bot;
    setBusy(true);
    try {
      const result = await bridge.apiGet("panels/list", { bot });
      // 加载期间又切换了机器人，丢掉旧机器人的结果。
      if (bot !== state.bot) return;
      state.scopes = result.scopes ?? {};
    } catch (error) {
      if (bot !== state.bot) return;
      state.scopes = {};
      toast(`读取指令面板失败：${error.message}`, true);
    } finally {
      if (bot === state.bot) {
        state.loading = false;
        setBusy(false);
      }
    }
    renderAll();
  }

  async function selectPanel(panelId) {
    if (state.busy || panelId === state.selected || !(await canLeave())) return;
    const bot = state.bot;
    setBusy(true);
    try {
      const result = await bridge.apiGet("panels/detail", { bot, id: panelId });
      if (bot !== state.bot || bot !== bots.current) return;
      state.selected = panelId;
      setDraft(draftFrom(result.panel));
    } catch (error) {
      if (bot !== state.bot || bot !== bots.current) return;
      toast(`读取面板失败：${error.message}`, true);
    } finally {
      if (bot === state.bot) {
        setBusy(false);
        renderList();
      }
    }
  }

  async function newPanel() {
    if (state.busy || !(await canLeave())) return;
    state.selected = "";
    setDraft({ panel_id: "", scope: "group", target_type: "all", targets: [], remark: "", items: [] });
  }

  async function save() {
    const draft = state.draft;
    if (!draft || state.busy) return;
    if (!draft.items.length) {
      toast("面板里至少要有一条指令", true);
      return;
    }
    if (draft.target_type === "specific" && !draft.targets.length) {
      toast("指定对象至少添加一个", true);
      return;
    }
    const problem = draft.items.map((item) => itemProblem(item, state.limits)).find(Boolean);
    if (problem) {
      toast(problem, true);
      return;
    }
    setBusy(true);
    let saved = "";
    try {
      const result = await bridge.apiPost("panels/save", { bot: state.bot, ...draft });
      saved = result.panel_id;
      if (result.warning) toast(result.warning, true);
      else toast("已保存到 QQ，客户端可能要过一会儿才显示。");
    } catch (error) {
      toast(`保存失败：${error.message}`, true);
    } finally {
      setBusy(false);
    }
    if (!saved) return;
    state.selected = "";
    state.draft = null;
    await loadList();
    await selectPanel(saved);
  }

  async function remove() {
    const draft = state.draft;
    if (!draft?.panel_id || state.busy) return;
    if (!(await confirm("确定删除这个指令面板吗？删除后立即对所有用户失效，无法恢复。"))) return;
    setBusy(true);
    try {
      await bridge.apiPost("panels/delete", { bot: state.bot, panel_id: draft.panel_id });
      toast("面板已删除");
      state.selected = "";
      state.draft = null;
      state.original = "";
    } catch (error) {
      toast(`删除失败：${error.message}`, true);
    } finally {
      setBusy(false);
    }
    await loadList();
  }

  async function reload() {
    if (state.busy || !(await canLeave())) return;
    state.loading = true;
    state.selected = "";
    state.bot = null;
    setDraft(null);
    try {
      const [result] = await Promise.all([bridge.apiGet("panels/state"), bots.refresh()]);
      state.limits = { ...DEFAULT_LIMITS, ...(result.limits ?? {}) };
    } catch (error) {
      toast(`读取机器人列表失败：${error.message}`, true);
    }
    await loadList();
  }

  // 切到别的机器人前先确认未保存的修改，素材库那边切换时也会问。
  bots.addGuard(canLeave);
  bots.subscribe(() => {
    if (!state.loaded || state.bot === null || state.bot === bots.current) return;
    if ($("#panels-view").classList.contains("hidden")) return;
    state.selected = "";
    setDraft(null);
    loadList();
  });
  mountBotButton($("#cp-bot"), { bridge, store: bots, toast, confirm });
  $("#cp-new").addEventListener("click", newPanel);
  $("#cp-refresh").addEventListener("click", reload);
  $("#cp-save").addEventListener("click", save);
  $("#cp-save-bar-button").addEventListener("click", save);
  $("#cp-delete").addEventListener("click", remove);
  $("#cp-add-item").addEventListener("click", addItem);
  $("#cp-scope").addEventListener("change", (event) => {
    if (!state.draft || state.draft.panel_id) return;
    state.draft.scope = event.target.value;
    if (!TARGET_SCOPES[state.draft.scope]) state.draft.target_type = "all";
    state.draft.targets = [];
    renderAll();
  });
  $("#cp-target-type").addEventListener("change", (event) => {
    if (!state.draft || state.draft.panel_id) return;
    state.draft.target_type = event.target.value;
    if (state.draft.target_type === "all") state.draft.targets = [];
    renderEditor();
  });
  $("#cp-remark").addEventListener("input", (event) => {
    if (!state.draft) return;
    state.draft.remark = event.target.value;
    renderEditor();
  });
  pickTargets.addEventListener("click", async () => {
    const draft = state.draft;
    if (!draft) return;
    const noun = TARGET_SCOPES[draft.scope];
    const ids = await pickUsers(bridge, draft.targets, {
      endpoint: "panels/targets",
      params: { bot: state.bot, scope: draft.scope },
      title: `选择${noun}`,
      noun,
      hint:
        draft.scope === "group"
          ? "列出这个机器人待过、有人说过话的群。QQ 官方机器人拿不到群名，群里发送 /sid 可以查看群 ID。"
          : "列出和这个机器人私聊过的用户。QQ 给每个机器人的用户 ID 都不一样，私聊和群聊的 ID 也不一样。",
      placeholder: `搜索${noun} ID 或来源名称，也可直接输入 ID`,
      unsupportedText: state.bot.startsWith("appid:")
        ? `手动添加的机器人不收消息，没有会话记录，请直接输入${noun} ID 添加。`
        : `当前 AstrBot 版本不记录${noun}（需要 v4.29.4 及以上），请直接输入${noun} ID 添加。`,
      failedText: `无法加载${noun}，可直接添加输入的 ID。`,
      emptyText: `没有匹配的${noun}。在 QQ 里唤醒一次机器人后即可搜到，也可直接添加该 ID。`,
    });
    if (!ids || state.draft !== draft) return;
    draft.targets = ids;
    renderEditor();
  });
  window.addEventListener("beforeunload", (event) => {
    if (!isDirty()) return;
    event.preventDefault();
    event.returnValue = "";
  });

  return {
    async show() {
      if (!state.loaded) {
        state.loaded = true;
        await reload();
      } else if (state.bot !== null && state.bot !== bots.current) {
        state.selected = "";
        setDraft(null);
        await loadList();
      }
    },
    save,
  };
}
