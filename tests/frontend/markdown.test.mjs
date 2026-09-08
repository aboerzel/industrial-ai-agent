import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";

const dom = new JSDOM("<!doctype html><html><body></body></html>");
Object.assign(globalThis, {
  document: dom.window.document,
  window: dom.window,
});

const { renderAgentAnswer } = await import("../../frontend/js/markdown.js");

function render(source, options) {
  const container = document.createElement("div");
  renderAgentAnswer(container, source, options);
  return container;
}

test("renders bold and italic Markdown", () => {
  const answer = render("This is **important** and *emphasized*.");

  assert.equal(answer.querySelector("strong")?.textContent, "important");
  assert.equal(answer.querySelector("em")?.textContent, "emphasized");
});

test("renders GFM tables inside a horizontally scrollable wrapper", () => {
  const answer = render("| Step | Observation |\n| --- | --- |\n| 1 | Rejected | ");

  assert.equal(answer.querySelector(".markdown-table-scroll table")?.tagName, "TABLE");
  assert.equal(answer.querySelectorAll("th").length, 2);
  assert.equal(answer.querySelectorAll("tbody td").length, 2);
});

test("preserves br-separated findings inside one Markdown table row", () => {
  const answer = render(
    "| Step | Findings |\n| --- | --- |\n| 1 | First finding<br>Second finding |",
  );

  assert.equal(answer.querySelectorAll("tbody tr").length, 1);
  assert.equal(answer.querySelectorAll("tbody br").length, 1);
  assert.equal(answer.querySelector("tbody td:last-child")?.textContent, "First findingSecond finding");
});

test("renders ordered and unordered lists", () => {
  const answer = render("- First\n- Second\n\n1. Inspect\n2. Repair");

  assert.deepEqual(
    [...answer.querySelectorAll("ul li")].map((item) => item.textContent),
    ["First", "Second"],
  );
  assert.deepEqual(
    [...answer.querySelectorAll("ol li")].map((item) => item.textContent),
    ["Inspect", "Repair"],
  );
});

test("does not infer actions from Markdown lists", () => {
  const answer = render(
    "### Recommended Investigation Actions\n\n1. Station S04\n   - Inspect quality sensors\n\n### Next Steps\n\n- Search documentation",
  );

  assert.equal(answer.querySelectorAll("li").length, 3);
  assert.equal(answer.querySelectorAll(".next-step-action").length, 0);
});

test("renders inline and fenced code", () => {
  const answer = render("Use `station_id`.\n\n```text\nS04\n```");

  assert.equal(answer.querySelector("p code")?.textContent, "station_id");
  assert.equal(answer.querySelector("pre code")?.textContent, "S04\n");
});

test("treats model-provided HTML as inert text", () => {
  globalThis.agentAnswerXssExecuted = false;
  const answer = render(
    '<script>globalThis.agentAnswerXssExecuted = true</script><img src=x onerror="globalThis.agentAnswerXssExecuted = true">',
  );

  assert.equal(globalThis.agentAnswerXssExecuted, false);
  assert.equal(answer.querySelector("script"), null);
  assert.equal(answer.querySelector("img"), null);
  assert.match(answer.textContent, /<script>/);
});

test("removes unsafe Markdown link destinations", () => {
  const answer = render("[Unsafe link](javascript:alert(1))");

  assert.equal(answer.querySelector("a")?.hasAttribute("href"), false);
});

test("renders plain-text answers and legacy br tags", () => {
  const answer = render("Product P4711 failed at S04.<br>Inspect the sensor.");

  assert.equal(answer.querySelector("p")?.textContent, "Product P4711 failed at S04.Inspect the sensor.");
  assert.equal(answer.querySelectorAll("br").length, 1);
});
