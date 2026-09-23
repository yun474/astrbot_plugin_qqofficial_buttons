const INLINE = /!\[([^\]]*)\]\(([^\s)]+)\)|\[([^\]]+)\]\(([^\s)]+)\)|\*\*\*([^*]+)\*\*\*|\*\*([^*]+)\*\*|__([^_]+)__|~~([^~]+)~~|`([^`]+)`|(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)/g;

function safeUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function inline(parent, source) {
  INLINE.lastIndex = 0;
  let from = 0;
  for (const match of source.matchAll(INLINE)) {
    if (match.index > from) parent.append(document.createTextNode(source.slice(from, match.index)));
    let node;
    if (match[1] !== undefined) {
      const url = safeUrl(match[2]);
      if (url) {
        node = document.createElement("img");
        node.src = url;
        node.alt = match[1].replace(/\s*#\d+px\s+#\d+px$/, "");
        const dimensions = match[1].match(/#(\d+)px\s+#(\d+)px$/);
        if (dimensions) {
          node.width = Number(dimensions[1]);
          node.height = Number(dimensions[2]);
        }
        node.loading = "lazy";
      }
    } else if (match[3] !== undefined) {
      const url = safeUrl(match[4]);
      if (url) {
        node = document.createElement("a");
        node.href = url;
        node.target = "_blank";
        node.rel = "noopener noreferrer";
        node.textContent = match[3];
      }
    } else {
      if (match[5] !== undefined || match[7] !== undefined) {
        node = document.createElement(match[5] !== undefined ? "strong" : "u");
        const inner = document.createElement(match[5] !== undefined ? "em" : "strong");
        inner.textContent = match[5] ?? match[7];
        node.append(inner);
      } else {
        const tag = match[6] !== undefined ? "strong"
          : match[8] !== undefined ? "del"
          : match[9] !== undefined ? "code" : "em";
        node = document.createElement(tag);
        node.textContent = match[6] ?? match[8] ?? match[9] ?? match[10] ?? match[11];
      }
    }
    parent.append(node ?? document.createTextNode(match[0]));
    from = match.index + match[0].length;
  }
  if (from < source.length) parent.append(document.createTextNode(source.slice(from)));
}

export function renderMarkdown(container, preset) {
  container.replaceChildren();
  let source = preset.content || "请选择：";
  if (preset.image_url) {
    source += `\n\n![菜单图片 #${preset.image_width || 600}px #${preset.image_height || 300}px](${preset.image_url})`;
  }
  let list = null;
  for (const rawLine of source.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      list = null;
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    const bullet = line.match(/^[-*]\s+(.+)$/);
    const numbered = line.match(/^\d+\.\s+(.+)$/);
    let block;
    if (heading) {
      block = document.createElement(`h${heading[1].length}`);
      inline(block, heading[2]);
      list = null;
    } else if (bullet || numbered) {
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tagName.toLowerCase() !== tag) {
        list = document.createElement(tag);
        container.append(list);
      }
      block = document.createElement("li");
      inline(block, (bullet || numbered)[1]);
      list.append(block);
      continue;
    } else if (line.startsWith("> ")) {
      block = document.createElement("blockquote");
      inline(block, line.slice(2));
      list = null;
    } else if (/^(\*{3,}|-{3,})$/.test(line)) {
      block = document.createElement("hr");
      list = null;
    } else {
      block = document.createElement("p");
      inline(block, line);
      list = null;
    }
    container.append(block);
  }
}
