import assert from "node:assert/strict";
import test from "node:test";
import { commandMarkdown, renderMarkdown } from "../pages/button-studio/preview.js";

class Element {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.style = {};
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren() {
    this.children = [];
  }
}

globalThis.document = {
  createElement: (tagName) => new Element(tagName),
  createTextNode: (textContent) => ({ textContent }),
};

test("快捷指令编码中文和特殊字符并保留引用选项", () => {
  const text = '/插件菜单 参数="a&b"';
  const show = '查看更多功能 "<>&';
  const tag = commandMarkdown("input", text, show, true);
  assert.equal(decodeURIComponent(tag.match(/text="([^"]*)"/)[1]), text);
  assert.equal(decodeURIComponent(tag.match(/show="([^"]*)"/)[1]), show);
  assert.ok(tag.endsWith('reference="true" />'));
  assert.equal(commandMarkdown("input", "/help"), '<qqbot-cmd-input text="%2Fhelp" reference="false" />');
  assert.equal(commandMarkdown("enter", "/help", "忽略", true), '<qqbot-cmd-enter text="%2Fhelp" />');
});

test("快捷指令拒绝空内容和超长参数", () => {
  assert.throws(() => commandMarkdown("input", "  "), /先填写/);
  assert.throws(() => commandMarkdown("input", "a".repeat(101)), /100/);
  assert.throws(() => commandMarkdown("input", "/help", "a".repeat(101)), /100/);
});

test("用户占位符用示例显示且不修改正文", () => {
  const container = new Element("div");
  const preset = { content: "{{at}} {{unknown}}" };
  renderMarkdown(container, preset);
  assert.equal(container.children[0].children[0].textContent, "@发起用户（预览） {{unknown}}");
  assert.equal(preset.content, "{{at}} {{unknown}}");
});

test("QQ 图片语法在正文中的原位置预览", () => {
  const url = "https://resource5-1255303497.cos.ap-guangzhou.myqcloud.com/abcmouse_word_watch/markdown/building.png";
  const container = new Element("div");
  renderMarkdown(container, {
    content: `上方文字\n![text #208px #320px](${url})\n下方文字`,
    image_url: "",
  });

  assert.equal(container.children.length, 3);
  const image = container.children[1].children[0];
  assert.equal(image.tagName, "img");
  assert.equal(image.src, url);
  assert.equal(image.alt, "text");
  assert.equal(image.width, 208);
  assert.equal(image.height, 320);
  assert.equal(image.style.aspectRatio, "208 / 320");
});
