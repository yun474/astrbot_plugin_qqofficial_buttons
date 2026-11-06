// 列表字段：页面上用标签预览，点“修改”在弹窗里逐条增删改，交互参照 AstrBot 的列表配置项。

const PREVIEW_LIMIT = 6;
const PREVIEW_LENGTH = 20;

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const button = (text, className = "") => {
  const node = el("button", className, text);
  node.type = "button";
  return node;
};

export function splitLines(text) {
  return String(text).split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

// 追加条目：去掉空白和重复，超出上限的部分丢弃并返回丢弃数量。
export function mergeItems(items, incoming, maxItems = Infinity) {
  const result = [...items];
  let skipped = 0;
  for (const raw of incoming) {
    const value = String(raw).trim();
    if (!value || result.includes(value)) continue;
    if (result.length >= maxItems) skipped += 1;
    else result.push(value);
  }
  return { items: result, skipped };
}

export function previewItems(items, limit = PREVIEW_LIMIT) {
  const shown = items.slice(0, limit).map((item) =>
    item.length > PREVIEW_LENGTH ? `${item.slice(0, PREVIEW_LENGTH)}…` : item,
  );
  return { shown, more: Math.max(0, items.length - limit) };
}

function openListDialog(options, initial) {
  const { title, hint, placeholder, emptyText, maxLength, maxItems } = options;
  let items = [...initial];
  let editing = -1;

  return new Promise((resolve) => {
    const overlay = el("div", "confirm-overlay");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    const panel = el("div", "confirm-card list-dialog");
    panel.append(el("h3", "", title));
    if (hint) panel.append(el("p", "list-dialog-hint", hint));

    const addRow = el("div", "list-dialog-add");
    const input = el("input");
    input.placeholder = placeholder || "输入后按回车添加";
    if (maxLength) input.maxLength = maxLength;
    const add = button("添加", "primary");
    const batchToggle = button("批量导入");
    addRow.append(input, add, batchToggle);

    const batch = el("div", "list-dialog-batch hidden");
    const batchText = el("textarea");
    batchText.rows = 4;
    batchText.placeholder = "一行一条，粘贴后点导入";
    const batchActions = el("div", "list-dialog-batch-actions");
    const batchCancel = button("取消");
    const batchApply = button("导入", "primary");
    batchActions.append(batchCancel, batchApply);
    batch.append(batchText, batchActions);

    const status = el("small", "list-dialog-status");
    const list = el("div", "list-dialog-items");
    const actions = el("div", "confirm-actions");
    const cancel = button("取消");
    const confirm = button("确定", "primary");
    actions.append(cancel, confirm);
    panel.append(addRow, batch, status, list, actions);
    overlay.append(panel);

    const setStatus = (message = "") => {
      const count = maxItems ? `${items.length} / ${maxItems} 条` : `${items.length} 条`;
      status.textContent = message ? `${count} · ${message}` : count;
    };

    const append = (values) => {
      const result = mergeItems(items, values, maxItems);
      items = result.items;
      render(result.skipped ? `已达上限，${result.skipped} 条未添加` : "");
    };

    function startEdit(index) {
      editing = index;
      render();
    }

    function finishEdit(index, value) {
      editing = -1;
      const text = value.trim();
      // 改成空就当作删除；与其他条目重复时保留原值。
      if (!text) {
        items.splice(index, 1);
        render();
        return;
      }
      const duplicate = items.some((item, i) => i !== index && item === text);
      if (!duplicate) items[index] = text;
      render(duplicate ? "与已有条目重复，未修改" : "");
    }

    function render(message = "") {
      list.replaceChildren();
      add.disabled = !input.value.trim() || items.length >= (maxItems || Infinity);
      if (!items.length) list.append(el("div", "list-dialog-empty", emptyText || "暂无条目"));
      items.forEach((item, index) => {
        const row = el("div", "list-dialog-item");
        if (index === editing) {
          const edit = el("input");
          edit.value = item;
          if (maxLength) edit.maxLength = maxLength;
          const save = button("✓", "list-dialog-icon");
          save.title = "保存";
          const discard = button("×", "list-dialog-icon");
          discard.title = "取消修改";
          let done = false;
          const commit = () => {
            if (done) return;
            done = true;
            finishEdit(index, edit.value);
          };
          edit.addEventListener("keydown", (event) => {
            if (event.key === "Enter") commit();
            if (event.key === "Escape") {
              // 只退出编辑，不关闭弹窗。
              event.stopPropagation();
              done = true;
              editing = -1;
              render();
            }
          });
          save.addEventListener("mousedown", (event) => event.preventDefault());
          save.addEventListener("click", commit);
          discard.addEventListener("mousedown", (event) => event.preventDefault());
          discard.addEventListener("click", () => {
            done = true;
            editing = -1;
            render();
          });
          edit.addEventListener("blur", commit);
          row.append(edit, save, discard);
          list.append(row);
          queueMicrotask(() => edit.focus());
          return;
        }
        const text = button(item, "list-dialog-text");
        text.title = "点击修改";
        text.addEventListener("click", () => startEdit(index));
        const remove = button("×", "list-dialog-icon");
        remove.title = "删除";
        remove.addEventListener("click", () => {
          items.splice(index, 1);
          editing = -1;
          render();
        });
        row.append(text, remove);
        list.append(row);
      });
      setStatus(message);
    }

    const close = (value) => {
      overlay.remove();
      document.removeEventListener("keydown", onKey);
      resolve(value);
    };
    const onKey = (event) => {
      if (event.key === "Escape") close(null);
    };

    input.addEventListener("input", () => render());
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || add.disabled) return;
      event.preventDefault();
      add.click();
    });
    add.addEventListener("click", () => {
      append([input.value]);
      input.value = "";
      render();
      input.focus();
    });
    batchToggle.addEventListener("click", () => {
      batch.classList.toggle("hidden");
      if (!batch.classList.contains("hidden")) batchText.focus();
    });
    batchCancel.addEventListener("click", () => {
      batchText.value = "";
      batch.classList.add("hidden");
    });
    batchApply.addEventListener("click", () => {
      const lines = splitLines(batchText.value).map((line) =>
        maxLength ? line.slice(0, maxLength) : line,
      );
      batchText.value = "";
      batch.classList.add("hidden");
      append(lines);
    });
    cancel.addEventListener("click", () => close(null));
    confirm.addEventListener("click", () => close(items));
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close(null);
    });
    document.addEventListener("keydown", onKey);
    document.body.append(overlay);
    render();
    input.focus();
  });
}

/**
 * 在 root 里渲染列表字段。options.onChange(items) 在弹窗点“确定”后调用；
 * options.emptyText 为没有条目时页面和弹窗里显示的文字。
 */
export function createListField(root, options) {
  let items = [];
  root.classList.add("list-field");
  const preview = el("div", "list-field-preview");
  const actions = el("div", "list-field-actions");
  const edit = button(options.buttonText || "修改");
  actions.append(edit);
  root.replaceChildren(preview, actions);

  function render() {
    preview.replaceChildren();
    if (!items.length) {
      preview.append(el("span", "list-field-empty", options.emptyText || "暂无条目"));
      return;
    }
    const { shown, more } = previewItems(items);
    for (const item of shown) preview.append(el("span", "list-chip", item));
    if (more) preview.append(el("span", "list-chip more", `+${more}`));
  }

  edit.addEventListener("click", async () => {
    const result = await openListDialog(options, items);
    if (!result) return;
    items = result;
    render();
    options.onChange?.([...items]);
  });

  return {
    actions,
    set(value) {
      items = [...(value ?? [])];
      render();
    },
  };
}
