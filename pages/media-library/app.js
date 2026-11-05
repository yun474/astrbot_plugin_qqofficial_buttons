const bridge = window.AstrBotPluginPage;
const $ = (selector) => document.querySelector(selector);

const state = {
  bot: "",
  cursor: "",
  images: [],
  busy: false,
  confirmResolve: null,
};

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("error", error);
  node.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("show"), 2600);
}

async function copyText(text, label) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // 插件页面运行在 iframe 中，剪贴板接口可能被拦截，退回到选中复制。
    const area = document.createElement("textarea");
    area.value = text;
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    if (!ok) {
      toast(`复制失败，请手动复制：${text}`, true);
      return;
    }
  }
  toast(`${label}已复制`);
}

function confirmDelete(message) {
  $("#confirm-message").textContent = message;
  $("#confirm-overlay").classList.remove("hidden");
  $("#confirm-accept").focus();
  return new Promise((resolve) => (state.confirmResolve = resolve));
}

function closeConfirm(result) {
  $("#confirm-overlay").classList.add("hidden");
  state.confirmResolve?.(result);
  state.confirmResolve = null;
}

const formatDate = (seconds) =>
  seconds ? new Date(seconds * 1000).toLocaleString("zh-CN", { hour12: false }) : "-";
const formatSize = (bytes) =>
  bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;

function card({ title, lines, image, actions }) {
  const root = document.createElement("article");
  root.className = "card";
  const thumb = document.createElement("div");
  thumb.className = "thumb";
  if (image) {
    const img = document.createElement("img");
    img.src = image;
    img.alt = title;
    img.loading = "lazy";
    thumb.append(img);
  } else {
    thumb.textContent = "点“预览”查看";
  }
  const body = document.createElement("div");
  body.className = "card-body";
  const strong = document.createElement("strong");
  strong.textContent = title;
  strong.title = title;
  body.append(strong);
  for (const line of lines) {
    const small = document.createElement("small");
    small.textContent = line.text;
    if (line.warn) small.className = "warn";
    body.append(small);
  }
  const bar = document.createElement("div");
  bar.className = "card-actions";
  for (const action of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = action.label;
    if (action.danger) button.className = "danger";
    button.addEventListener("click", () => action.run(thumb, button));
    bar.append(button);
  }
  root.append(thumb, body, bar);
  return root;
}

function renderMedia(total) {
  const grid = $("#media-grid");
  grid.replaceChildren();
  const soon = Date.now() / 1000 + 7 * 86400;
  for (const item of state.images) {
    grid.append(
      card({
        title: item.file_name || item.image_id,
        image: item.preview_url,
        lines: [
          { text: `上传：${formatDate(item.created_at)}` },
          { text: `过期：${formatDate(item.expires_at)}`, warn: item.expires_at && item.expires_at < soon },
        ],
        actions: [
          { label: "复制链接", run: () => copyText(item.url, "素材链接") },
          { label: "删除", danger: true, run: () => removeImage(item) },
        ],
      }),
    );
  }
  $("#media-empty").classList.toggle("hidden", state.images.length > 0);
  $("#more").classList.toggle("hidden", !state.cursor);
  if (total !== undefined) {
    const quota = $("#quota");
    quota.textContent = `已用 ${total} / 100`;
    quota.classList.toggle("full", total >= 100);
  }
}

async function loadMedia(append = false) {
  try {
    const result = await bridge.apiGet("media/list", {
      bot: state.bot,
      cursor: append ? state.cursor : "",
    });
    state.images = append ? state.images.concat(result.images) : result.images;
    state.cursor = result.next_cursor;
    renderMedia(result.total);
  } catch (error) {
    state.images = [];
    state.cursor = "";
    renderMedia();
    toast(error.message, true);
  }
}

function renderLocal(result) {
  $("#local-dir").textContent = result.local_dir;
  const grid = $("#local-grid");
  grid.replaceChildren();
  for (const item of result.local_images) {
    grid.append(
      card({
        title: item.name,
        lines: [{ text: `${formatSize(item.size)} · ${formatDate(item.modified_at)}` }],
        actions: [
          { label: "预览", run: (thumb, button) => previewLocal(item, thumb, button) },
          { label: "复制地址", run: () => copyText(item.url, "本机图片地址") },
        ],
      }),
    );
  }
  $("#local-empty").classList.toggle("hidden", result.local_images.length > 0);
}

async function previewLocal(item, thumb, button) {
  button.disabled = true;
  try {
    const result = await bridge.apiGet("media/local/preview", { name: item.name });
    const img = document.createElement("img");
    img.src = result.data_url;
    img.alt = item.name;
    thumb.replaceChildren(img);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function removeImage(item) {
  const ok = await confirmDelete(
    `删除后链接立即失效，引用它的菜单将无法显示图片（已发出的消息不受影响）。确定删除“${item.file_name || item.image_id}”吗？`,
  );
  if (!ok) return;
  try {
    await bridge.apiPost("media/delete", { bot: state.bot, image_id: item.image_id });
    toast("已删除");
    await loadMedia();
  } catch (error) {
    toast(error.message, true);
  }
}

async function upload(file, maxBytes) {
  if (file.size > maxBytes) {
    toast("图片不能超过 10MB。", true);
    return;
  }
  const button = $("#upload");
  button.disabled = true;
  button.textContent = "上传中…";
  try {
    // 页面桥会对路径逐段编码，这里不能再编码一次。
    const result = await bridge.upload(`media/upload/${state.bot || "_"}`, file);
    await copyText(result.image.url, "上传成功，素材链接");
    await loadMedia();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "＋ 上传图片";
  }
}

async function loadAll() {
  const result = await bridge.apiGet("media/state");
  const select = $("#bot-select");
  select.replaceChildren();
  for (const bot of result.bots) {
    const option = document.createElement("option");
    option.value = bot.id;
    option.textContent = `${bot.id}（${bot.name}）`;
    select.append(option);
  }
  // 只有一个机器人时隐藏选择框，用户无需关心素材归属。
  select.classList.toggle("hidden", result.bots.length <= 1);
  if (!result.bots.some((bot) => bot.id === state.bot)) state.bot = result.bots[0]?.id ?? "";
  select.value = state.bot;
  $("#upload").disabled = result.bots.length === 0;
  renderLocal(result);
  $("#media-empty").textContent = result.bots.length
    ? "素材库还没有图片，点右上角上传一张吧。"
    : "没有已连接的 QQ 官方机器人，连接后再来管理素材。";
  if (result.bots.length === 0) {
    state.images = [];
    state.cursor = "";
    renderMedia();
    return result;
  }
  await loadMedia();
  return result;
}

async function init() {
  await bridge.ready();
  let limits = { max_bytes: 10 * 1024 * 1024 };
  try {
    limits = await loadAll();
  } catch (error) {
    toast(error.message, true);
  }
  $("#refresh").addEventListener("click", () => loadAll().catch((error) => toast(error.message, true)));
  $("#bot-select").addEventListener("change", (event) => {
    state.bot = event.target.value;
    loadMedia();
  });
  $("#more").addEventListener("click", () => loadMedia(true));
  $("#upload").addEventListener("click", () => $("#upload-input").click());
  $("#upload-input").addEventListener("change", (event) => {
    const [file] = event.target.files;
    event.target.value = "";
    if (file) upload(file, limits.max_bytes);
  });
  $("#copy-dir").addEventListener("click", () => copyText($("#local-dir").textContent, "文件夹路径"));
  $("#confirm-cancel").addEventListener("click", () => closeConfirm(false));
  $("#confirm-accept").addEventListener("click", () => closeConfirm(true));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.confirmResolve) closeConfirm(false);
  });
}

init();
