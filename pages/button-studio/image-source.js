// 菜单图片的“来源三选一”：公网链接、素材库、本机图片。
// 本机图片只能从固定目录的下拉列表中选择，前缀由界面锁定，用户无法写入路径。

const $ = (selector) => document.querySelector(selector);

export function sourceOf(url) {
  const text = (url || "").trim();
  if (text.startsWith("local://")) return "local";
  if (text.startsWith("qqbot-media://")) return "media";
  return "url";
}

export function createImageSource({ bridge, onChange, toast }) {
  // 每种来源各记一份，切换来源再切回来时不会丢掉刚填的内容。
  const values = { url: "", media: "", local: "" };
  let source = "url";
  let localDir = "";
  let localImages = null;

  const hints = {
    url: () => "填写可从公网访问的 HTTPS 图片地址。填写后默认追加在正文末尾。",
    media: () => "在“素材库”页面上传后复制链接，或点“从素材库选择”。素材 90 天未使用会过期。",
    local: () =>
      `只能选择固定目录里的图片，目录不能更改：${localDir || "加载中…"}。每次发送临时上传、发完即删。`,
  };

  function renderTabs() {
    for (const button of document.querySelectorAll("#image-source-tabs [data-source]")) {
      const active = button.dataset.source === source;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    }
    for (const panel of document.querySelectorAll(".image-source [data-panel]")) {
      panel.classList.toggle("hidden", panel.dataset.panel !== source);
    }
    $("#image-source-hint").textContent = hints[source]();
  }

  function renderLocalOptions() {
    const select = $("#preset-image-local");
    select.replaceChildren();
    const current = values.local.replace(/^local:\/\//, "");
    const placeholder = new Option(localImages === null ? "正在读取目录…" : "选择一张图片…", "");
    select.append(placeholder);
    for (const item of localImages || []) select.append(new Option(item.name, item.url));
    if (current && !(localImages || []).some((item) => item.url === values.local)) {
      // 菜单里引用的图片已不在目录中时仍显示出来，提醒用户重新放回或改选。
      select.append(new Option(`${current}（目录里找不到）`, values.local));
    }
    select.value = values.local;
  }

  async function loadLocal() {
    try {
      const state = await bridge.apiGet("media/state");
      localDir = state.local_dir;
      localImages = state.local_images;
    } catch (error) {
      localImages = localImages || [];
      toast(error.message, true);
    }
    renderLocalOptions();
    renderTabs();
  }

  function emit() {
    onChange(values[source]);
  }

  function setSource(next) {
    source = next;
    renderTabs();
    if (source === "local" && localImages === null) loadLocal();
    emit();
  }

  function render(url) {
    // 载入菜单或外部改动图片时调用：按地址前缀决定当前来源。
    const text = url || "";
    source = sourceOf(text);
    values.url = source === "url" ? text : "";
    values.media = source === "media" ? text : "";
    values.local = source === "local" ? text : "";
    $("#preset-image-url").value = values.url;
    $("#preset-image-media").value = values.media;
    renderLocalOptions();
    renderTabs();
    if (source === "local" && localImages === null) loadLocal();
  }

  function setMedia(url) {
    values.media = url;
    $("#preset-image-media").value = url;
    setSource("media");
  }

  for (const button of document.querySelectorAll("#image-source-tabs [data-source]")) {
    button.addEventListener("click", () => setSource(button.dataset.source));
  }
  $("#preset-image-url").addEventListener("input", (event) => {
    values.url = event.target.value;
    emit();
  });
  $("#preset-image-media").addEventListener("input", (event) => {
    values.media = event.target.value;
    emit();
  });
  $("#preset-image-local").addEventListener("change", (event) => {
    values.local = event.target.value;
    emit();
  });
  $("#refresh-local").addEventListener("click", loadLocal);

  return { render, setMedia };
}
