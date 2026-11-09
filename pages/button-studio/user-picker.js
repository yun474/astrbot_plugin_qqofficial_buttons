// “选择用户”弹窗：搜索已记录的用户、勾选，或直接添加输入的 OpenID。
// 交互参照 AstrBot 原生的用户选择器；旧版 AstrBot 没有用户记录时只保留手动添加。

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

export function senderTitle(sender) {
  return sender.sender_name ? `${sender.sender_name}（${sender.sender_id}）` : sender.sender_id;
}

export function senderSource(sender) {
  if (!sender) return "暂无记录，来源未知";
  const scene = sender.group ? "群聊" : "私聊";
  return `${scene} · ${sender.session_name || sender.umo}`;
}

// options 可换数据来源和文案，指令面板用它按机器人、场景挑选用户或群；不传时与原来一致。
export function pickUsers(bridge, currentIds = [], options = {}) {
  const {
    endpoint = "senders",
    params = {},
    title = "选择用户",
    noun = "用户",
    hint = "按 OpenID 或来源群名搜索在 QQ 里和机器人说过话的用户。QQ 官方机器人拿不到群成员昵称，可让对方对机器人发送 /sid 获取自己的 ID。",
    placeholder = "搜索 OpenID 或群名，也可直接输入 OpenID",
    unsupportedText = "当前 AstrBot 版本不记录用户（需要 v4.29.4 及以上），请直接输入 OpenID 添加。",
    failedText = "无法加载用户，可直接添加输入的 OpenID。",
    emptyText = "没有匹配的用户。对方在 QQ 里唤醒一次机器人后即可搜到，也可直接添加该 ID。",
  } = options;
  const draft = [...new Set(currentIds.map(String))];
  const known = {};
  const view = { search: "", page: 1, hasMore: false, results: [], loading: false, failed: false, supported: true };
  let requestId = 0;
  let timer = null;

  return new Promise((resolve) => {
    const overlay = el("div", "confirm-overlay");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    const panel = el("div", "confirm-card user-picker");
    panel.append(
      el("h3", "", title),
      el("p", "user-picker-hint", hint),
    );

    const columns = el("div", "user-picker-columns");
    const left = el("div", "user-picker-column");
    const selectedTitle = el("p", "user-picker-heading");
    const selectedList = el("div", "user-picker-list");
    left.append(selectedTitle, selectedList);

    const right = el("div", "user-picker-column");
    const searchRow = el("div", "user-picker-search");
    const input = el("input");
    input.placeholder = placeholder;
    input.maxLength = 512;
    const refresh = el("button", "", "刷新");
    refresh.type = "button";
    searchRow.append(input, refresh);
    const status = el("small", "user-picker-status");
    const resultList = el("div", "user-picker-list user-picker-results");
    const addButton = el("button", "primary user-picker-add");
    addButton.type = "button";
    const pager = el("div", "user-picker-pager");
    const prev = el("button", "", "上一页");
    const pageLabel = el("small");
    const next = el("button", "", "下一页");
    prev.type = next.type = "button";
    pager.append(prev, pageLabel, next);
    right.append(searchRow, status, resultList, addButton, pager);
    columns.append(left, right);

    const actions = el("div", "confirm-actions");
    const cancel = el("button", "", "取消");
    const confirm = el("button", "primary", "确定");
    cancel.type = confirm.type = "button";
    actions.append(cancel, confirm);
    panel.append(columns, actions);
    overlay.append(panel);

    const close = (value) => {
      clearTimeout(timer);
      requestId += 1;
      overlay.remove();
      document.removeEventListener("keydown", onKey);
      resolve(value);
    };
    const onKey = (event) => {
      if (event.key === "Escape") close(null);
    };

    const toggle = (id) => {
      const index = draft.indexOf(id);
      if (index >= 0) draft.splice(index, 1);
      else draft.push(id);
      render();
    };

    function renderSelected() {
      selectedTitle.textContent = `已选择（${draft.length}）`;
      selectedList.replaceChildren();
      if (!draft.length) {
        selectedList.append(el("small", "user-picker-empty", `还没有选择${noun}`));
        return;
      }
      for (const id of draft) {
        const row = el("div", "user-picker-item");
        const text = el("div", "user-picker-text");
        text.append(el("strong", "", known[id] ? senderTitle(known[id]) : id), el("small", "", senderSource(known[id])));
        const remove = el("button", "user-picker-remove", "×");
        remove.type = "button";
        remove.title = `移除 ${id}`;
        remove.addEventListener("click", () => toggle(id));
        row.append(text, remove);
        selectedList.append(row);
      }
    }

    function renderResults() {
      resultList.replaceChildren();
      for (const sender of view.results) {
        const row = el("label", "user-picker-item selectable");
        const box = el("input");
        box.type = "checkbox";
        box.checked = draft.includes(sender.sender_id);
        box.addEventListener("change", () => toggle(sender.sender_id));
        const text = el("div", "user-picker-text");
        text.append(el("strong", "", senderTitle(sender)), el("small", "", senderSource(sender)));
        row.title = sender.umo;
        row.append(box, text);
        resultList.append(row);
      }
      if (view.loading) status.textContent = "正在加载……";
      else if (!view.supported) status.textContent = unsupportedText;
      else if (view.failed) status.textContent = failedText;
      else if (!view.results.length) status.textContent = emptyText;
      else status.textContent = "";

      // 与原生选择器一致：首页没有结果、加载失败或旧版本时，允许把输入内容直接作为 ID 添加。
      const typed = input.value.trim();
      const canAdd =
        typed && !view.loading && !draft.includes(typed) && (view.page === 1 && !view.results.length || view.failed || !view.supported);
      addButton.classList.toggle("hidden", !canAdd);
      addButton.textContent = `添加 ID「${typed}」`;

      pager.classList.toggle("hidden", !view.supported || (view.page === 1 && !view.hasMore));
      pageLabel.textContent = `第 ${view.page} 页`;
      prev.disabled = view.loading || view.page === 1;
      next.disabled = view.loading || view.failed || !view.hasMore;
    }

    function render() {
      renderSelected();
      renderResults();
    }

    async function load() {
      const current = ++requestId;
      view.loading = true;
      view.failed = false;
      render();
      try {
        const result = await bridge.apiGet(endpoint, { ...params, search: view.search, page: view.page });
        if (current !== requestId) return;
        view.supported = result.supported !== false;
        view.results = result.senders || [];
        view.hasMore = Boolean(result.has_more);
        for (const sender of view.results) known[sender.sender_id] ??= sender;
      } catch {
        if (current !== requestId) return;
        view.failed = true;
        view.results = [];
        view.hasMore = false;
      }
      view.loading = false;
      render();
    }

    async function resolveKnown() {
      // 已保存的 ID 分批查回来源信息；查不到的 ID 照常保留。
      for (let offset = 0; offset < draft.length; offset += 100) {
        try {
          const result = await bridge.apiGet(endpoint, { ...params, ids: draft.slice(offset, offset + 100).join(",") });
          if (result.supported === false) return;
          for (const sender of result.senders || []) known[sender.sender_id] = sender;
        } catch {
          return;
        }
      }
      if (overlay.isConnected) renderSelected();
    }

    input.addEventListener("input", () => {
      view.search = input.value.trim();
      view.page = 1;
      renderResults();
      clearTimeout(timer);
      timer = setTimeout(load, 300);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !addButton.classList.contains("hidden")) addButton.click();
    });
    refresh.addEventListener("click", () => {
      view.page = 1;
      load();
    });
    prev.addEventListener("click", () => {
      view.page -= 1;
      load();
    });
    next.addEventListener("click", () => {
      view.page += 1;
      load();
    });
    addButton.addEventListener("click", () => {
      const typed = input.value.trim();
      if (!typed || draft.includes(typed)) return;
      draft.push(typed);
      render();
    });
    cancel.addEventListener("click", () => close(null));
    confirm.addEventListener("click", () => close([...draft]));
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close(null);
    });
    document.addEventListener("keydown", onKey);
    document.body.append(overlay);
    render();
    input.focus();
    load();
    resolveKnown();
  });
}
