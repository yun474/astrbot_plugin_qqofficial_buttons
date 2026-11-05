// 从素材库或本机图片目录选一张图，返回可直接填入菜单的图片地址。
export async function pickMediaImage(bridge) {
  const state = await bridge.apiGet("media/state");
  let media = { images: [] };
  let mediaError = "";
  if (state.bots.length) {
    try {
      // 默认机器人的素材；多机器人时请到素材库页面切换后复制链接。
      media = await bridge.apiGet("media/list", { bot: state.bots[0].id });
    } catch (error) {
      mediaError = error.message;
    }
  }

  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    const panel = document.createElement("div");
    panel.className = "confirm-card media-picker";
    const title = document.createElement("h3");
    title.textContent = "选择图片";
    panel.append(title);

    const close = (value) => {
      overlay.remove();
      document.removeEventListener("keydown", onKey);
      resolve(value);
    };
    const onKey = (event) => {
      if (event.key === "Escape") close(null);
    };

    const section = (label, items, empty) => {
      const heading = document.createElement("p");
      heading.className = "media-picker-heading";
      heading.textContent = label;
      const list = document.createElement("div");
      list.className = "media-picker-list";
      for (const item of items) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = item.label;
        button.title = item.url;
        button.addEventListener("click", () => close(item.url));
        list.append(button);
      }
      if (!items.length) {
        const hint = document.createElement("small");
        hint.textContent = empty;
        list.append(hint);
      }
      panel.append(heading, list);
    };

    const multiBot = state.bots.length > 1 ? `（机器人 ${state.bots[0].id}）` : "";
    section(
      `QQ 素材库${multiBot}`,
      media.images.map((item) => ({ label: item.file_name || item.image_id, url: item.url })),
      mediaError || (state.bots.length ? "素材库为空，可到“素材库”页面上传。" : "没有已连接的 QQ 官方机器人。"),
    );
    section(
      "本机图片（每次发送临时上传）",
      state.local_images.map((item) => ({ label: item.name, url: item.url })),
      "图片目录为空，可在“素材库”页面查看目录位置。",
    );

    const actions = document.createElement("div");
    actions.className = "confirm-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "取消";
    cancel.addEventListener("click", () => close(null));
    actions.append(cancel);
    panel.append(actions);

    overlay.append(panel);
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close(null);
    });
    document.addEventListener("keydown", onKey);
    document.body.append(overlay);
    cancel.focus();
  });
}
