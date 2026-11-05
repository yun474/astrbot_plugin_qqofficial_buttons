// 素材库视图：管理 QQ 官方素材库图片与本机图片目录，与工作台共用同一个插件页面。

const $ = (selector) => document.querySelector(selector);

const formatDate = (seconds) =>
  seconds ? new Date(seconds * 1000).toLocaleString("zh-CN", { hour12: false }) : "-";
const formatSize = (bytes) =>
  bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;

// 按到期时间给出文字和状态：已过期标红，7 天内到期标黄。
export function expiryLine(expiresAt, now = Date.now() / 1000) {
  if (!expiresAt) return { text: "到期：未知" };
  if (expiresAt <= now) return { text: "已过期，链接不可用", level: "danger" };
  const text = `到期：${formatDate(expiresAt)}`;
  return expiresAt - now < 7 * 86400 ? { text: `${text}（即将过期）`, level: "warn" } : { text };
}

function card({ title, titleNode, lines, image, actions }) {
  const root = document.createElement("article");
  root.className = "ml-card";
  const thumb = document.createElement("div");
  thumb.className = "ml-thumb";
  if (image) {
    const img = document.createElement("img");
    img.src = image;
    img.alt = title;
    img.loading = "lazy";
    thumb.append(img);
  } else {
    thumb.textContent = "加载中…";
  }
  const body = document.createElement("div");
  body.className = "ml-card-body";
  const strong = document.createElement("strong");
  if (titleNode) strong.append(...titleNode);
  else strong.textContent = title;
  strong.title = title;
  body.append(strong);
  for (const line of lines) {
    const small = document.createElement("small");
    small.textContent = line.text;
    if (line.level) small.className = line.level;
    body.append(small);
  }
  const bar = document.createElement("div");
  bar.className = "ml-card-actions";
  for (const action of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = action.label;
    if (action.danger) button.className = "danger";
    button.addEventListener("click", () => action.run());
    bar.append(button);
  }
  root.append(thumb, body, bar);
  return root;
}

export function createMediaLibrary({ bridge, toast, confirm, onLocalChange }) {
  const state = { bot: "", cursor: "", images: [], botCount: 0, maxBytes: 10 * 1024 * 1024 };
  let loaded = false;
  let thumbObserver = null;

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

  function renderMedia(total) {
    const grid = $("#ml-media-grid");
    grid.replaceChildren();
    for (const item of state.images) {
      grid.append(
        card({
          title: item.file_name || item.image_id,
          image: item.preview_url,
          lines: [{ text: `上传：${formatDate(item.created_at)}` }, expiryLine(item.expires_at)],
          actions: [
            { label: "复制链接", run: () => copyText(item.url, "素材链接") },
            { label: "删除", danger: true, run: () => removeImage(item) },
          ],
        }),
      );
    }
    $("#ml-media-empty").classList.toggle("hidden", state.images.length > 0);
    $("#ml-more").classList.toggle("hidden", !state.cursor);
    if (total !== undefined) {
      const quota = $("#ml-quota");
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

  async function previewLocal(name, thumb) {
    try {
      const result = await bridge.apiGet("media/local/preview", { name });
      const img = document.createElement("img");
      img.src = result.data_url;
      img.alt = name;
      thumb.replaceChildren(img);
    } catch {
      thumb.textContent = "无法预览";
    }
  }

  function renderLocal(result) {
    $("#ml-local-dir").textContent = result.local_dir;
    $("#ml-local-count").textContent = `${result.local_images.length} 张`;
    const grid = $("#ml-local-grid");
    grid.replaceChildren();
    thumbObserver?.disconnect();
    thumbObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        thumbObserver.unobserve(entry.target);
        previewLocal(entry.target.dataset.name, entry.target.querySelector(".ml-thumb"));
      }
    });
    for (const item of result.local_images) {
      const prefix = document.createElement("span");
      prefix.className = "ml-fixed-prefix";
      prefix.textContent = "local://";
      const node = card({
        title: item.url,
        titleNode: [prefix, item.name],
        lines: [{ text: `${formatSize(item.size)} · ${formatDate(item.modified_at)}` }],
        actions: [{ label: "复制地址", run: () => copyText(item.url, "本机图片地址") }],
      });
      node.dataset.name = item.name;
      grid.append(node);
      // 卡片滚动到可见区域时才读取图片，目录里图片很多时也不会一次全部加载。
      thumbObserver.observe(node);
    }
    $("#ml-local-empty").classList.toggle("hidden", result.local_images.length > 0);
  }

  async function removeImage(item) {
    const ok = await confirm(
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

  // 两种上传各有按钮：QQ 素材库存在云端，本机目录存在 AstrBot 所在机器。
  async function upload(file, { button, endpoint, label, done, enabled }) {
    if (file.size > state.maxBytes) {
      toast("图片不能超过 10MB。", true);
      return;
    }
    const text = button.textContent;
    button.disabled = true;
    button.textContent = "上传中…";
    try {
      const result = await bridge.upload(endpoint, file);
      await copyText(result.image.url, label);
      await done();
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = !enabled();
      button.textContent = text;
    }
  }

  async function loadLocal() {
    renderLocal(await bridge.apiGet("media/state"));
    onLocalChange?.();
  }

  async function loadAll() {
    const result = await bridge.apiGet("media/state");
    state.maxBytes = result.max_bytes || state.maxBytes;
    const select = $("#ml-bot-select");
    select.replaceChildren();
    for (const bot of result.bots) select.append(new Option(`${bot.id}（${bot.name}）`, bot.id));
    // 只有一个机器人时隐藏选择框；多个时素材按所选机器人查看和上传。
    select.classList.toggle("hidden", result.bots.length <= 1);
    if (!result.bots.some((bot) => bot.id === state.bot)) state.bot = result.bots[0]?.id ?? "";
    select.value = state.bot;
    state.botCount = result.bots.length;
    $("#ml-upload").disabled = result.bots.length === 0;
    renderLocal(result);
    $("#ml-media-empty").textContent = result.bots.length
      ? "素材库还没有图片，点右上角上传一张吧。"
      : "没有已连接的 QQ 官方机器人，连接后再来管理素材。";
    if (result.bots.length === 0) {
      state.images = [];
      state.cursor = "";
      renderMedia(0);
      return;
    }
    await loadMedia();
  }

  const reload = () => loadAll().catch((error) => toast(error.message, true));

  $("#ml-refresh").addEventListener("click", reload);
  $("#ml-bot-select").addEventListener("change", (event) => {
    state.bot = event.target.value;
    loadMedia();
  });
  $("#ml-more").addEventListener("click", () => loadMedia(true));
  const targets = {
    "ml-upload": () => ({
      // 页面桥会对路径逐段编码，这里不能再编码一次。
      endpoint: `media/upload/${state.bot || "_"}`,
      label: "上传成功，素材链接",
      done: () => loadMedia(),
      enabled: () => state.botCount > 0,
    }),
    "ml-local-upload": () => ({
      endpoint: "media/local/upload",
      label: "上传成功，本机图片地址",
      done: () => loadLocal(),
      enabled: () => true,
    }),
  };
  for (const [id, target] of Object.entries(targets)) {
    const button = $(`#${id}`);
    const input = $(`#${id}-input`);
    button.addEventListener("click", () => input.click());
    input.addEventListener("change", (event) => {
      const [file] = event.target.files;
      event.target.value = "";
      if (file) upload(file, { button, ...target() });
    });
  }
  $("#ml-copy-dir").addEventListener("click", () => copyText($("#ml-local-dir").textContent, "文件夹路径"));
  for (const item of document.querySelectorAll(".ml-nav [data-target]")) {
    item.addEventListener("click", () =>
      document.getElementById(item.dataset.target).scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  }

  return {
    // 第一次切到素材库时才加载，打开工作台不会多发请求。
    show() {
      if (loaded) return;
      loaded = true;
      reload();
    },
  };
}
