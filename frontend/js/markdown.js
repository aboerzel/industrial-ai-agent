import DOMPurify from "./vendor/purify.es.mjs";
import { Marked } from "./vendor/marked.esm.js";

const markdown = new Marked({
  breaks: true,
  gfm: true,
  renderer: {
    html(token) {
      return isSafeLineBreak(token.text) ? "<br>" : escapeHtml(token.text);
    },
  },
});

const SANITIZER_OPTIONS = {
  ALLOW_ARIA_ATTR: false,
  ALLOW_DATA_ATTR: false,
  ALLOWED_ATTR: ["align", "href", "title"],
  ALLOWED_TAGS: [
    "a",
    "blockquote",
    "br",
    "code",
    "del",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
  ],
};

export function renderAgentAnswer(container, source) {
  const template = document.createElement("template");
  template.innerHTML = sanitizeMarkdown(source);

  for (const link of template.content.querySelectorAll("a")) {
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
  for (const table of template.content.querySelectorAll("table")) {
    const wrapper = document.createElement("div");
    wrapper.className = "markdown-table-scroll";
    table.replaceWith(wrapper);
    wrapper.append(table);
  }

  container.replaceChildren(template.content);
}

export function sanitizeMarkdown(source) {
  const html = markdown.parse(String(source ?? ""));
  return DOMPurify.sanitize(html, SANITIZER_OPTIONS);
}

function isSafeLineBreak(value) {
  return /^<br\s*\/?\s*>$/i.test(value);
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
