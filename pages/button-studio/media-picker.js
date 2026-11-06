// 从 QQ 素材库选一张图，返回 qqbot-media:// 链接；已过期的素材不可选。

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

export function expiryText(expiresAt, now = Date.now() / 1000) {
  if (!expiresAt) return { text: "到期时间未知", level: "" };
  const date = new Date(expiresAt * 1000).toLocaleDateString("zh-CN");
  if (expiresAt <= now) return { text: "已过期", level: "expired" };
  if (expiresAt - now < 7 * 86400) return { text: `${date} 到期，即将过期`, level: "soon" };
  return { text: `${date} 到期`, level: "" };
}

export async function pickMediaImage(bridge) {
  const state = await bridge.apiGet("media/state");

  return new Promise((resolve) => {
    let bot = state.bots[0]?.id ?? "";
    let requestId = 0;
    const overlay = el("div", "confirm-overlay");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    const panel = el("div", "confirm-card media-picker");
    const head = el("div", "media-picker-head");
    head.append(el("h3", "", "选择素材库图片"));
    const botSelect = el("select", "media-picker-bot");
    botSelect.setAttribute("aria-label", "选择机器人");
    for (const item of state.bots) botSelect.append(new Option(`${item.id}（${item.name}）`, item.id));
    // 素材只对上传它的机器人有效，多机器人时需要能切换。
    botSelect.classList.toggle("hidden", state.bots.length <= 1);
    head.append(botSelect);
    const status = el("small", "media-picker-status");
    const grid = el("div", "media-picker-grid");
    // QQ 素材列表分页返回，有下一页时显示“加载更多”，与素材库页面一致。
    let cursor = "";
    const more = el("button", "media-picker-more hidden", "加载更多");
    more.type = "button";
    const actions = el("div", "confirm-actions");
    const cancel = el("button", "", "取消");
    cancel.type = "button";
    actions.append(cancel);
    panel.append(head, status, grid, more, actions);
    overlay.append(panel);

    const close = (value) => {
      requestId += 1;
      overlay.remove();
      document.removeEventListener("keydown", onKey);
      resolve(value);
    };
    const onKey = (event) => {
      if (event.key === "Escape") close(null);
    };

    function renderImages(images) {
      for (const item of images) {
        const expiry = expiryText(item.expires_at);
        const button = el("button", `media-picker-item ${expiry.level}`);
        button.type = "button";
        button.title = item.url;
        const thumb = el("span", "media-picker-thumb");
        if (item.preview_url) {
          const img = el("img");
          img.src = item.preview_url;
          img.alt = "";
          img.loading = "lazy";
          thumb.append(img);
        }
        button.append(thumb, el("strong", "", item.file_name || item.image_id), el("small", "", expiry.text));
        if (expiry.level === "expired") button.disabled = true;
        else button.addEventListener("click", () => close(item.url));
        grid.append(button);
      }
    }

    async function load(append = false) {
      const current = ++requestId;
      if (!append) {
        grid.replaceChildren();
        cursor = "";
      }
      more.classList.add("hidden");
      if (!state.bots.length) {
        status.textContent = "没有已连接的 QQ 官方机器人。";
        return;
      }
      status.textContent = "正在加载……";
      try {
        const result = await bridge.apiGet("media/list", { bot, cursor: append ? cursor : "" });
        if (current !== requestId) return;
        cursor = result.next_cursor || "";
        const empty = !append && !result.images.length;
        status.textContent = empty ? "素材库为空，可到“素材库”页面上传。" : "";
        renderImages(result.images);
        more.classList.toggle("hidden", !cursor);
      } catch (error) {
        if (current !== requestId) return;
        status.textContent = error.message;
        // 翻页失败时保留已加载的图片，可再点一次重试。
        more.classList.toggle("hidden", !append);
      }
    }

    more.addEventListener("click", () => load(true));

    botSelect.addEventListener("change", () => {
      bot = botSelect.value;
      load();
    });
    cancel.addEventListener("click", () => close(null));
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close(null);
    });
    document.addEventListener("keydown", onKey);
    document.body.append(overlay);
    cancel.focus();
    load();
  });
}
