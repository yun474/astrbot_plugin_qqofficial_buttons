import assert from "node:assert/strict";
import test from "node:test";
import { renderMarkdown } from "../pages/button-studio/preview.js";

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
