import { pickMediaImage } from "./media-picker.js";
import { pickUsers } from "./user-picker.js";
import { createListField } from "./list-field.js";
import { createMediaLibrary } from "./media-library.js";
import { createImageSource } from "./image-source.js";
import { commandMarkdown, imageMarkdown, renderMarkdown } from "./preview.js";

const bridge = window.AstrBotPluginPage;
const $ = (selector) => document.querySelector(selector);

// 会经过插件处理的动作，只有这些按钮插件才能拦截并回复拒绝语。
const FUNCTION_ACTIONS = ["send_text", "show_preset", "callback_text", "callback_preset", "callback_command", "callback_llm"];
const FALLBACK_DENY_REPLY = "这个按钮没给你操作权限，别乱戳啦。";

// 一行一条的内容都用列表字段编辑，弹窗标题等随权限类型变化，打开弹窗时读取。
const permissionListOptions = {
  title: "指定用户 OpenID",
  placeholder: "用户 OpenID",
  emptyText: "还没有添加，至少需要一个",
  maxItems: 100,
  onChange: (items) => {
    const button = selectedButton();
    if (!button) return;
    if (button.permission.type === 0) button.permission.user_ids = items;
    if (button.permission.type === 3) button.permission.role_ids = items;
    markDirty();
  },
};
const fields = {
  triggers: createListField($("#preset-triggers"), {
    title: "自定义指令",
    hint: "以 / 开头，只能包含中英文、数字、下划线和短横线，例如 /菜单。发送这些指令就会弹出这个按钮组。",
    placeholder: "/菜单",
    emptyText: "暂无自定义指令",
    maxItems: 20,
    maxLength: 33,
    onChange: (items) => {
      if (!state.draft) return;
      state.draft.triggers = items;
      $("#usage-command").textContent = items[0] || "请先填写自定义指令";
      markDirty();
    },
  }),
  permission: createListField($("#permission-values"), permissionListOptions),
  deny: createListField($("#deny-replies"), {
    title: "拒绝语",
    hint: "没权限的人点击时随机发一条；写 {{at}} 会艾特点击者。全部删掉则静默拒绝，不发任何消息。",
    placeholder: "{{at}} 这个按钮不是给你的哦",
    emptyText: "已清空，静默拒绝",
    maxItems: 20,
    maxLength: 500,
    onChange: (items) => {
      const button = selectedButton();
      if (!button) return;
      button.deny_replies = items;
      markDirty();
    },
  }),
};
const pickUsersButton = document.createElement("button");
pickUsersButton.type = "button";
pickUsersButton.textContent = "选择用户";
fields.permission.actions.append(pickUsersButton);

const ui = {
  list: $("#preset-list"),
  search: $("#search"),
  title: $("#page-title"),
  subtitle: $("#page-subtitle"),
  empty: $("#empty-state"),
  editor: $("#editor-layout"),
  loading: $("#loading"),
  toast: $("#toast"),
  saveState: $("#save-state"),
  inspectorEmpty: $("#inspector-empty"),
  inspectorContent: $("#inspector-content"),
  keyboard: $("#keyboard-preview"),
  messagePreview: $("#message-preview"),
  actionSelect: $("#button-action"),
};

const state = {
  presets: [],
  limits: { max_rows: 5, max_buttons_per_row: 5 },
  actions: [],
  draft: null,
  originalId: null,
  isNew: false,
  selected: null,
  dirty: false,
  busy: false,
  dragged: null,
  confirmResolve: null,
  confirmFocus: null,
};

const clone = (value) => JSON.parse(JSON.stringify(value));
const randomId = (prefix) => {
  const bytes = crypto.getRandomValues(new Uint8Array(5));
  return `${prefix}_${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
};

function toast(message, error = false) {
  ui.toast.textContent = message;
  ui.toast.classList.toggle("error", error);
  ui.toast.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ui.toast.classList.remove("show"), 2600);
}

function setBusy(busy) {
  state.busy = busy;
  $("#studio-view").inert = busy;
}

function markDirty() {
  state.dirty = true;
  ui.saveState.textContent = "有未保存更改";
  ui.saveState.classList.add("dirty");
  toggleSaveBar(true);
}

// 有未保存修改时在底部浮出保存条，编辑到页面下方也不用翻回顶部保存。
function toggleSaveBar(show) {
  $("#save-bar").classList.toggle("hidden", !show);
  document.body.classList.toggle("save-bar-open", show);
}

function markSaved() {
  state.dirty = false;
  ui.saveState.textContent = "已同步";
  ui.saveState.classList.remove("dirty");
  toggleSaveBar(false);
}

function askConfirm(message) {
  return new Promise((resolve) => {
    state.confirmResolve = resolve;
    state.confirmFocus = document.activeElement;
    $("#confirm-message").textContent = message;
    $("#confirm-overlay").classList.remove("hidden");
    $("#confirm-cancel").focus();
  });
}

function finishConfirm(accepted) {
  const resolve = state.confirmResolve;
  if (!resolve) return;
  state.confirmResolve = null;
  $("#confirm-overlay").classList.add("hidden");
  state.confirmFocus?.focus();
  state.confirmFocus = null;
  resolve(accepted);
}

async function canLeaveDraft() {
  return !state.dirty || await askConfirm("当前修改还没保存，确定丢掉吗？");
}

function findPreset(id) {
  return state.presets.find((item) => item.id === id);
}

function selectedButton() {
  if (!state.draft || !state.selected) return null;
  return state.draft.rows[state.selected.row]?.[state.selected.col] ?? null;
}

function createPreset() {
  const id = randomId("menu");
  return {
    id,
    name: "新按钮组",
    description: "",
    content: "请选择：",
    image_url: "",
    image_width: 600,
    image_height: 300,
    triggers: [],
    enabled: true,
    expose_to_llm: false,
    rows: [[createButton()]],
  };
}

function createButton() {
  return {
    id: randomId("btn"),
    label: "新按钮",
    visited_label: "已点击",
    style: 0,
    action: { type: "input", value: "在这里填写内容" },
    permission: { type: 2, user_ids: [], role_ids: [] },
  };
}

async function selectPreset(id, options = {}) {
  if (!options.force && !(await canLeaveDraft())) return;
  const preset = findPreset(id);
  if (!preset) return;
  state.draft = clone(preset);
  state.originalId = preset.id;
  state.isNew = false;
  state.selected = null;
  clearPendingImage();
  markSaved();
  renderAll();
}

async function beginNewPreset() {
  if (!(await canLeaveDraft())) return;
  clearPendingImage();
  state.draft = createPreset();
  state.originalId = null;
  state.isNew = true;
  state.selected = { row: 0, col: 0 };
  markDirty();
  renderAll();
  $("#preset-name").focus();
  $("#preset-name").select();
}

function renderAll() {
  renderList();
  const hasDraft = Boolean(state.draft);
  ui.empty.classList.toggle("hidden", hasDraft);
  ui.editor.classList.toggle("hidden", !hasDraft);
  $("#delete-preset").disabled = !hasDraft || state.isNew;
  $("#duplicate-preset").disabled = !hasDraft || state.isNew;
  $("#save-preset").disabled = !hasDraft;
  if (!hasDraft) {
    ui.title.textContent = "选择一个按钮组";
    ui.subtitle.textContent = "在左边挑一个，或者新建一份。";
    return;
  }
  ui.title.textContent = state.draft.name || "未命名按钮组";
  ui.subtitle.textContent = state.draft.description || "编辑布局、动作和点击权限。";
  fillPresetFields();
  renderKeyboard();
  renderInspector();
}

function renderList() {
  const keyword = ui.search.value.trim().toLowerCase();
  ui.list.replaceChildren();
  const items = state.presets.filter((preset) =>
    `${preset.name} ${preset.id}`.toLowerCase().includes(keyword),
  );
  if (!items.length) {
    const empty = document.createElement("p");
    empty.style.cssText = "padding:12px;color:var(--muted);font-size:12px";
    empty.textContent = keyword ? "没搜到，换个词试试。" : "还没有按钮组。";
    ui.list.append(empty);
    return;
  }
  for (const preset of items) {
    const item = document.createElement("button");
    item.className = `preset-item ${state.originalId === preset.id && !state.isNew ? "active" : ""}`;
    const icon = document.createElement("span");
    icon.className = "preset-icon";
    icon.textContent = "⌘";
    const copy = document.createElement("span");
    copy.className = "preset-copy";
    const name = document.createElement("strong");
    name.textContent = preset.name;
    const id = document.createElement("small");
    id.textContent = preset.id;
    copy.append(name, id);
    const dot = document.createElement("span");
    dot.className = `status-dot ${preset.enabled ? "on" : ""}`;
    item.append(icon, copy, dot);
    item.addEventListener("click", () => selectPreset(preset.id));
    ui.list.append(item);
  }
}

// 旧版菜单的图片单独存放、发送时追加在正文末尾；载入时转成正文里的一行，发送效果不变，之后可自由挪动。
function migrateLegacyImage(draft) {
  if (!draft.image_url) return;
  draft.content = `${draft.content || "请选择："}\n\n${imageMarkdown(draft)}`;
  draft.image_url = "";
}

function fillPresetFields() {
  migrateLegacyImage(state.draft);
  $("#preset-name").value = state.draft.name;
  $("#preset-id").value = state.draft.id;
  $("#preset-id").disabled = !state.isNew;
  $("#preset-description").value = state.draft.description;
  $("#preset-content").value = state.draft.content;
  fields.triggers.set(state.draft.triggers ?? []);
  $("#preset-enabled").checked = state.draft.enabled;
  $("#preset-llm").checked = state.draft.expose_to_llm;
  $("#limit-badge").textContent = `最多 ${state.limits.max_rows} × ${state.limits.max_buttons_per_row}`;
  $("#usage-command").textContent = state.draft.triggers?.[0] || "请先填写自定义指令";
  renderMarkdown(ui.messagePreview, state.draft);
}

function renderKeyboard() {
  ui.keyboard.replaceChildren();
  state.draft.rows.forEach((row, rowIndex) => {
    const rowEl = document.createElement("div");
    rowEl.className = "keyboard-row";
    rowEl.style.setProperty("--count", String(row.length + (row.length < state.limits.max_buttons_per_row ? 1 : 0)));
    rowEl.dataset.row = String(rowIndex);
    rowEl.addEventListener("dragover", (event) => {
      event.preventDefault();
      rowEl.classList.add("drag-over");
    });
    rowEl.addEventListener("dragleave", () => rowEl.classList.remove("drag-over"));
    rowEl.addEventListener("drop", (event) => {
      event.preventDefault();
      rowEl.classList.remove("drag-over");
      moveDraggedToRow(rowIndex);
    });
    row.forEach((button, colIndex) => {
      const buttonEl = document.createElement("button");
      buttonEl.className = `preview-button style-${button.style}`;
      if (state.selected?.row === rowIndex && state.selected?.col === colIndex) {
        buttonEl.classList.add("selected");
      }
      buttonEl.textContent = button.label;
      buttonEl.draggable = true;
      buttonEl.addEventListener("click", () => {
        state.selected = { row: rowIndex, col: colIndex };
        renderKeyboard();
        renderInspector();
      });
      buttonEl.addEventListener("dragstart", () => {
        state.dragged = { row: rowIndex, col: colIndex };
      });
      buttonEl.addEventListener("dragend", () => {
        state.dragged = null;
        document.querySelectorAll(".drag-over").forEach((el) => el.classList.remove("drag-over"));
      });
      rowEl.append(buttonEl);
    });
    if (row.length < state.limits.max_buttons_per_row) {
      const add = document.createElement("button");
      add.className = "row-add";
      add.textContent = "＋ 按钮";
      add.title = "在这一行添加按钮";
      add.addEventListener("click", () => addButton(rowIndex));
      rowEl.append(add);
    }
    ui.keyboard.append(rowEl);
  });
  const rowLimitReached = state.draft.rows.length >= state.limits.max_rows;
  $("#add-row").disabled = rowLimitReached;
  $("#add-row").textContent = rowLimitReached
    ? `已达 ${state.limits.max_rows} 行上限` : "＋ 添加一行";
}

function renderInspector() {
  const button = selectedButton();
  ui.inspectorEmpty.classList.toggle("hidden", Boolean(button));
  ui.inspectorContent.classList.toggle("hidden", !button);
  if (!button) return;

  $("#button-label").value = button.label;
  $("#button-visited").value = button.visited_label;
  $("#button-style").value = String(button.style);
  ui.actionSelect.replaceChildren();
  const actions = state.actions.filter((action) => {
    if (state.limits.enable_function_buttons !== false) return true;
    return !FUNCTION_ACTIONS.includes(action.value);
  });
  for (const action of actions) {
    const option = document.createElement("option");
    option.value = action.value;
    option.textContent = action.label;
    ui.actionSelect.append(option);
  }
  ui.actionSelect.value = button.action.type;
  $("#button-value").value = button.action.value;
  $("#llm-at-user").checked = button.action.at_user === true;
  $("#permission-type").value = String(button.permission.type);
  updateActionHelp();
  updatePermissionEditor();
}

function updateActionHelp() {
  const action = state.actions.find((item) => item.value === ui.actionSelect.value);
  $("#action-hint").textContent = action?.hint ?? "";
  const labels = {
    command: "发送的指令或文字",
    input: "填入输入框的文字",
    link: "HTTPS 链接",
    send_text: "插件回复的文字",
    show_preset: "目标按钮组 ID",
    callback_text: "回调后回复的文字",
    callback_preset: "回调后发送的菜单 ID",
    callback_command: "执行的指令及参数",
    callback_llm: "让 bot 说什么（提示词）",
  };
  $("#action-value-label").textContent = labels[ui.actionSelect.value] ?? "动作内容";
  const placeholders = {
    command: "/help",
    input: "帮我查一下今天的天气",
    link: "https://example.com/",
    send_text: "这里是插件回复的固定内容",
    show_preset: "another_menu_id",
    callback_text: "按钮点下后回复的内容",
    callback_preset: "another_menu_id",
    callback_command: "/天气 北京",
    callback_llm: "来一句每日一言，短一点，别说教",
  };
  $("#button-value").placeholder = placeholders[ui.actionSelect.value] ?? "";
  $("#llm-at-wrap").classList.toggle("hidden", ui.actionSelect.value !== "callback_llm");
}

// 与后端保存规则一致：仅触发者和指定用户可选插件拦截，AstrBot 管理员总是插件拦截。
function canIntercept(button) {
  return FUNCTION_ACTIONS.includes(button.action.type) && [0, 10].includes(button.permission.type);
}

function pluginDenies(button) {
  if (!FUNCTION_ACTIONS.includes(button.action.type)) return false;
  return button.permission.type === 11 || (canIntercept(button) && button.intercept === true);
}

// 切换动作或权限后去掉已不生效的字段，保持与后端保存结果一致。
function syncDenyFields(button) {
  if (!canIntercept(button)) delete button.intercept;
  if (!pluginDenies(button)) delete button.deny_replies;
}

function updateDenyEditor(button) {
  $("#intercept-wrap").classList.toggle("hidden", !canIntercept(button));
  $("#permission-intercept").checked = button.intercept === true;
  const denies = pluginDenies(button);
  $("#deny-wrap").classList.toggle("hidden", !denies);
  if (!denies) return;
  // 没改过的按钮展示默认拒绝语；清空后保存为空列表，表示静默拒绝。
  const replies = button.deny_replies ?? [state.limits.default_deny_reply || FALLBACK_DENY_REPLY];
  fields.deny.set(replies);
  $("#deny-hint").textContent =
    button.permission.type === 11
      ? "QQ 不认识 AstrBot 管理员，所有人都能点到，由插件拒绝。"
      : "切换拦截方式后需要重新发送菜单，QQ 里能不能点才会跟着变。";
}

function updatePermissionEditor() {
  const button = selectedButton();
  if (!button) return;
  updateDenyEditor(button);
  const type = Number($("#permission-type").value);
  const visible = type === 0 || type === 3;
  $("#permission-values-wrap").classList.toggle("hidden", !visible);
  if (!visible) return;
  const users = type === 0;
  permissionListOptions.title = users ? "指定用户 OpenID" : "频道身份组 ID";
  permissionListOptions.placeholder = users ? "用户 OpenID" : "身份组 ID";
  $("#permission-values-label").textContent = permissionListOptions.title;
  pickUsersButton.classList.toggle("hidden", !users);
  fields.permission.set(users ? button.permission.user_ids : button.permission.role_ids);
}

function addButton(rowIndex) {
  const row = state.draft.rows[rowIndex];
  if (!row || row.length >= state.limits.max_buttons_per_row) return;
  row.push(createButton());
  state.selected = { row: rowIndex, col: row.length - 1 };
  markDirty();
  renderKeyboard();
  renderInspector();
}

function addRow() {
  if (!state.draft || state.draft.rows.length >= state.limits.max_rows) return;
  state.draft.rows.push([createButton()]);
  state.selected = { row: state.draft.rows.length - 1, col: 0 };
  markDirty();
  renderKeyboard();
  renderInspector();
}

function moveDraggedToRow(targetRow) {
  if (!state.dragged) return;
  const source = state.draft.rows[state.dragged.row];
  const target = state.draft.rows[targetRow];
  if (!source || !target || target.length >= state.limits.max_buttons_per_row) return;
  const [button] = source.splice(state.dragged.col, 1);
  target.push(button);
  if (!source.length) {
    state.draft.rows.splice(state.dragged.row, 1);
    if (state.dragged.row < targetRow) targetRow -= 1;
  }
  state.selected = { row: targetRow, col: state.draft.rows[targetRow].length - 1 };
  state.dragged = null;
  markDirty();
  renderKeyboard();
  renderInspector();
}

function deleteSelectedButton() {
  if (!state.selected) return;
  const row = state.draft.rows[state.selected.row];
  row.splice(state.selected.col, 1);
  if (!row.length && state.draft.rows.length > 1) state.draft.rows.splice(state.selected.row, 1);
  if (!state.draft.rows.flat().length) state.draft.rows = [[createButton()]];
  state.selected = null;
  markDirty();
  renderKeyboard();
  renderInspector();
}

function moveSelected(direction) {
  if (!state.selected) return;
  let { row, col } = state.selected;
  const current = state.draft.rows[row];
  if (direction === "left" && col > 0) {
    [current[col - 1], current[col]] = [current[col], current[col - 1]];
    col -= 1;
  } else if (direction === "right" && col < current.length - 1) {
    [current[col + 1], current[col]] = [current[col], current[col + 1]];
    col += 1;
  } else if (["up", "down"].includes(direction)) {
    const targetRow = direction === "up" ? row - 1 : row + 1;
    if (targetRow < 0 || targetRow >= state.draft.rows.length) return;
    if (state.draft.rows[targetRow].length >= state.limits.max_buttons_per_row) {
      toast("目标行已经塞满啦", true);
      return;
    }
    const [button] = current.splice(col, 1);
    state.draft.rows[targetRow].push(button);
    if (!current.length) {
      state.draft.rows.splice(row, 1);
      row = direction === "up" ? targetRow : Math.min(row, state.draft.rows.length - 1);
    } else {
      row = targetRow;
    }
    col = state.draft.rows[row].length - 1;
  } else return;
  state.selected = { row, col };
  markDirty();
  renderKeyboard();
  renderInspector();
}

async function savePreset() {
  if (!state.draft || state.busy) return;
  if (state.isNew && state.presets.some((preset) => preset.id === state.draft.id.trim())) {
    toast("这个菜单 ID 已存在，请换一个，或选择原菜单编辑。", true);
    return;
  }
  setBusy(true);
  try {
    const result = await bridge.apiPost("preset/save", clone(state.draft));
    if (state.isNew) state.presets.push(result.preset);
    else {
      const index = state.presets.findIndex((item) => item.id === state.originalId);
      if (index >= 0) state.presets[index] = result.preset;
    }
    state.draft = clone(result.preset);
    state.originalId = result.preset.id;
    state.isNew = false;
    markSaved();
    renderAll();
    toast("保存好了喵~");
  } catch (error) {
    toast(error.message || "保存失败", true);
  } finally {
    setBusy(false);
  }
}

// Ctrl+S / ⌘+S 保存：只在工作台且没有弹窗时生效，保存后把光标放回原来的输入框，方便接着写。
async function saveByShortcut(event) {
  if ($("#studio-view").classList.contains("hidden")) return;
  event.preventDefault();
  if (document.querySelector(".confirm-overlay:not(.hidden)")) return;
  const active = document.activeElement;
  const range = typeof active?.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null;
  await savePreset();
  if (!active?.isConnected || active === document.body) return;
  active.focus();
  if (range) active.setSelectionRange(...range);
}

async function deletePreset() {
  if (state.busy || !state.originalId || !(await askConfirm(`确定删除“${state.draft.name}”吗？`))) return;
  setBusy(true);
  try {
    await bridge.apiPost("preset/delete", { id: state.originalId });
    state.presets = state.presets.filter((item) => item.id !== state.originalId);
    state.draft = null;
    state.originalId = null;
    state.selected = null;
    markSaved();
    renderAll();
    toast("按钮组已经删除。");
  } catch (error) {
    toast(error.message || "删除失败", true);
  } finally {
    setBusy(false);
  }
}

async function duplicatePreset() {
  if (state.busy || !state.originalId || !(await canLeaveDraft())) return;
  setBusy(true);
  try {
    const result = await bridge.apiPost("preset/duplicate", { id: state.originalId });
    state.presets.push(result.preset);
    selectPreset(result.preset.id, { force: true });
    toast("复制好啦，新副本已经打开。");
  } catch (error) {
    toast(error.message || "复制失败", true);
  } finally {
    setBusy(false);
  }
}

function exportPresets() {
  const data = JSON.stringify({ version: 1, presets: state.presets }, null, 2);
  const url = URL.createObjectURL(new Blob([data], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `qq-buttons-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function importPresets(file) {
  if (state.busy) return;
  try {
    const raw = JSON.parse(await file.text());
    const presets = Array.isArray(raw) ? raw : raw.presets;
    if (!Array.isArray(presets)) throw new Error("文件里没有 presets 列表");
    if (!(await askConfirm(`导入会覆盖现有 ${state.presets.length} 个按钮组，继续吗？`))) return;
    setBusy(true);
    const result = await bridge.apiPost("presets/import", { presets });
    state.presets = result.presets;
    state.draft = null;
    state.originalId = null;
    state.selected = null;
    markSaved();
    renderAll();
    toast(`成功导入 ${result.count} 个按钮组。`);
  } catch (error) {
    toast(error.message || "导入失败", true);
  } finally {
    setBusy(false);
    $("#import-file").value = "";
  }
}

// “插入图片”里选好的图片只暂存在这里，点插入按钮才写进正文光标处。
let pendingImage = "";
const imageSource = createImageSource({
  bridge,
  toast,
  onChange(url) {
    pendingImage = url;
  },
});

// 只在换到另一个按钮组或插入完成时清空；改名称、ID 等字段会重绘编辑区，但不应丢掉已选的图片。
function clearPendingImage() {
  pendingImage = "";
  imageSource.render("");
}

// 工作台和素材库共用一个插件页面，最左侧切换，侧边栏和主区域一起换；工作台的未保存修改保留在内存里。
const mediaLibrary = createMediaLibrary({
  bridge,
  toast,
  confirm: askConfirm,
  onLocalChange: () => imageSource.refreshLocal(),
});

function switchView(view) {
  for (const button of document.querySelectorAll(".nav-rail [data-view]")) {
    const active = button.dataset.view === view;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  $("#studio-view").classList.toggle("hidden", view !== "studio");
  $("#media-view").classList.toggle("hidden", view !== "media");
  if (view === "media") mediaLibrary.show();
  window.scrollTo(0, 0);
}

for (const button of document.querySelectorAll(".nav-rail [data-view]")) {
  button.addEventListener("click", () => switchView(button.dataset.view));
}

function bindPresetFields() {
  const bindings = [
    ["#preset-name", "name", "input"],
    ["#preset-id", "id", "input"],
    ["#preset-description", "description", "input"],
    ["#preset-content", "content", "input"],
    ["#preset-enabled", "enabled", "checked"],
    ["#preset-llm", "expose_to_llm", "checked"],
  ];
  for (const [selector, key, mode] of bindings) {
    $(selector).addEventListener(mode === "checked" ? "change" : "input", (event) => {
      if (!state.draft) return;
      state.draft[key] = mode === "checked" ? event.target.checked
        : mode === "number" ? Number(event.target.value) : event.target.value;
      markDirty();
      if (["name", "description", "id"].includes(key)) renderAll();
      if (["content", "image_url", "image_width", "image_height"].includes(key)) {
        renderMarkdown(ui.messagePreview, state.draft);
      }
    });
  }
}

function insertAtCursor(syntax) {
  if (!state.draft) return false;
  const content = $("#preset-content");
  const start = content.selectionStart;
  const end = content.selectionEnd;
  if (content.value.length - (end - start) + syntax.length > content.maxLength) {
    toast("正文超过 2000 字，请先删减内容。", true);
    return false;
  }
  content.setRangeText(syntax, start, end, "end");
  state.draft.content = content.value;
  markDirty();
  renderMarkdown(ui.messagePreview, state.draft);
  content.focus();
  return true;
}

function insertCommandAtCursor() {
  try {
    const syntax = commandMarkdown(
      $("#command-tag-type").value,
      $("#command-tag-text").value,
      $("#command-tag-show").value,
      $("#command-tag-reference").value === "true",
    );
    if (insertAtCursor(syntax)) toast("快捷指令已插入正文。");
  } catch (error) {
    toast(error.message, true);
  }
}

// 返回可插入正文的图片地址；素材链接与本机图片原样保留，其他地址必须是 HTTPS。
function imageAddress(value) {
  const text = (value || "").trim();
  if (/^qqbot-media:\/\/\S+$/.test(text)) return text;
  if (/^local:\/\/[^\s/\\()]+$/.test(text)) return text;
  try {
    const url = new URL(text);
    return url.protocol === "https:" && url.hostname ? url.href : "";
  } catch {
    return "";
  }
}

async function pickImage() {
  if (!state.draft) return;
  try {
    const url = await pickMediaImage(bridge);
    if (url) imageSource.setMedia(url);
  } catch (error) {
    toast(error.message, true);
  }
}

function insertImageAtCursor() {
  if (!state.draft) return;
  const url = imageAddress(pendingImage);
  if (!url) {
    toast("先填写公网 HTTPS 地址、选择素材库图片或本机图片。", true);
    return;
  }
  const width = Number($("#preset-image-width").value);
  const height = Number($("#preset-image-height").value);
  if (![width, height].every((size) => Number.isInteger(size) && size >= 1 && size <= 4096)) {
    toast("图片宽高须为 1～4096 的整数。", true);
    return;
  }

  const syntax = imageMarkdown({ image_url: url, image_width: width, image_height: height });
  if (!insertAtCursor(syntax)) return;
  clearPendingImage();
  toast("图片已插入正文，可继续调整位置。");
}

function bindButtonFields() {
  const simple = [
    ["#button-label", (button, value) => (button.label = value)],
    ["#button-visited", (button, value) => (button.visited_label = value)],
    ["#button-style", (button, value) => (button.style = Number(value))],
    ["#button-value", (button, value) => (button.action.value = value)],
  ];
  for (const [selector, apply] of simple) {
    $(selector).addEventListener(selector === "#button-style" ? "change" : "input", (event) => {
      const button = selectedButton();
      if (!button) return;
      apply(button, event.target.value);
      markDirty();
      renderKeyboard();
    });
  }
  ui.actionSelect.addEventListener("change", (event) => {
    const button = selectedButton();
    if (!button) return;
    button.action.type = event.target.value;
    // 艾特开关只属于直接调用，切到其他动作时去掉，保持与后端保存结果一致。
    if (button.action.type !== "callback_llm") delete button.action.at_user;
    $("#llm-at-user").checked = button.action.at_user === true;
    syncDenyFields(button);
    markDirty();
    updateActionHelp();
    updatePermissionEditor();
  });
  $("#llm-at-user").addEventListener("change", (event) => {
    const button = selectedButton();
    if (!button) return;
    button.action.at_user = event.target.checked;
    markDirty();
  });
  $("#permission-type").addEventListener("change", (event) => {
    const button = selectedButton();
    if (!button) return;
    button.permission.type = Number(event.target.value);
    syncDenyFields(button);
    markDirty();
    updatePermissionEditor();
  });
  $("#permission-intercept").addEventListener("change", (event) => {
    const button = selectedButton();
    if (!button) return;
    if (event.target.checked) button.intercept = true;
    else delete button.intercept;
    syncDenyFields(button);
    markDirty();
    updatePermissionEditor();
  });
  pickUsersButton.addEventListener("click", async () => {
    const button = selectedButton();
    if (!button || button.permission.type !== 0) return;
    try {
      const ids = await pickUsers(bridge, button.permission.user_ids);
      if (!ids) return;
      button.permission.user_ids = ids;
      fields.permission.set(ids);
      markDirty();
    } catch (error) {
      toast(error.message, true);
    }
  });
}

function bindEvents() {
  $("#confirm-cancel").addEventListener("click", () => finishConfirm(false));
  $("#confirm-accept").addEventListener("click", () => finishConfirm(true));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") finishConfirm(false);
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") saveByShortcut(event);
  });
  $("#save-bar-button").addEventListener("click", savePreset);
  $("#new-preset").addEventListener("click", beginNewPreset);
  $("#empty-new").addEventListener("click", beginNewPreset);
  ui.search.addEventListener("input", renderList);
  $("#save-preset").addEventListener("click", savePreset);
  $("#delete-preset").addEventListener("click", deletePreset);
  $("#duplicate-preset").addEventListener("click", duplicatePreset);
  $("#insert-image").addEventListener("click", insertImageAtCursor);
  $("#pick-image").addEventListener("click", pickImage);
  $("#insert-mention").addEventListener("click", () => {
    if (insertAtCursor("{{at}}")) toast("已插入艾特发起用户占位符。");
  });
  $("#insert-command-tag").addEventListener("click", insertCommandAtCursor);
  $("#command-tag-type").addEventListener("change", (event) => {
    const direct = event.target.value === "enter";
    $("#command-tag-show").disabled = direct;
    $("#command-tag-reference").disabled = direct;
  });
  $("#add-row").addEventListener("click", addRow);
  $("#delete-button").addEventListener("click", deleteSelectedButton);
  document.querySelectorAll("[data-move]").forEach((button) =>
    button.addEventListener("click", () => moveSelected(button.dataset.move)),
  );
  $("#export-button").addEventListener("click", exportPresets);
  $("#import-button").addEventListener("click", () => $("#import-file").click());
  $("#import-file").addEventListener("change", (event) => {
    if (event.target.files[0]) importPresets(event.target.files[0]);
  });
  $("#copy-command").addEventListener("click", async () => {
    const text = $("#usage-command").textContent;
    try {
      await navigator.clipboard.writeText(text);
      toast("指令已复制。");
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
      toast("指令已复制。");
    }
  });
  bindPresetFields();
  bindButtonFields();
  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

async function init() {
  try {
    await bridge.ready();
    const result = await bridge.apiGet("state");
    state.presets = result.presets ?? [];
    state.limits = { ...state.limits, ...(result.limits ?? {}) };
    state.actions = result.actions ?? [];
    bindEvents();
    if (state.presets.length) selectPreset(state.presets[0].id, { force: true });
    else renderAll();
  } catch (error) {
    toast(`编辑器加载失败：${error.message}`, true);
    ui.empty.classList.remove("hidden");
  } finally {
    ui.loading.classList.add("hidden");
  }
}

init();
