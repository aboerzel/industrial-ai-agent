import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";

import { renderConfiguration } from "../../frontend/js/model-configuration.js";

const CATALOG = [
  model("local_quality", "Local Qwen 3.5 9B", "LOCAL", "RESTRICTED", ["text", "tool_calling", "structured_output"]),
  model("nvidia_quality", "NVIDIA Nemotron", "PUBLIC_CLOUD", "CONFIDENTIAL", ["text", "tool_calling", "structured_output"]),
  model("public_text", "Public Text", "PUBLIC_CLOUD", "CONFIDENTIAL", ["text"]),
];
const CONSUMERS = [
  { consumer_id: "agent", display_name: "Agent", required_capabilities: ["text", "tool_calling", "structured_output"] },
  { consumer_id: "rca.reasoning", display_name: "Root Cause Analysis", required_capabilities: ["text", "structured_output"] },
];

test("renders display names, all classifications, dynamic specialized consumers, and persisted selection", () => {
  const { content } = render();
  assert.match(content.textContent, /Local Qwen 3.5 9B/);
  assert.match(content.textContent, /Root Cause Analysis/);
  for (const classification of ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]) assert.match(content.textContent, new RegExp(classification));
  const restricted = content.querySelector('[aria-label="Agent RESTRICTED model"]');
  assert.equal(restricted.value, "local_quality");
  assert.doesNotMatch(restricted.selectedOptions[0].textContent, /local_quality/);
});

test("keeps forbidden public models visible but disabled and shows capability warnings", () => {
  const { content } = render();
  const restricted = content.querySelector('[aria-label="Agent RESTRICTED model"]');
  const forbidden = [...restricted.options].find((option) => option.value === "nvidia_quality");
  assert.equal(forbidden.disabled, true);
  assert.match(forbidden.textContent, /Not allowed for RESTRICTED data/);
  const publicSelect = content.querySelector('[aria-label="Agent PUBLIC model"]');
  publicSelect.value = "public_text";
  publicSelect.dispatchEvent(new window.Event("change"));
  assert.match(content.textContent, /Compatibility warning: missing Tool Calling, Structured Output/);
});

test("shows missing assignment and catalog references without choosing a fallback", () => {
  const { content } = render([{ consumer_id: "agent", data_classification: "RESTRICTED", model_id: "removed_model" }]);
  const restricted = content.querySelector('[aria-label="Agent RESTRICTED model"]');
  assert.equal(restricted.value, "");
  assert.match(content.textContent, /Unconfigured. No model will be selected automatically/);
});

test("renders automatic mode, policy, required capabilities, and eligible display names", () => {
  const { content } = render([{
    consumer_id: "agent",
    data_classification: "RESTRICTED",
    model_id: null,
    selection_mode: "AUTO",
    selection_policy: "QUALITY_FIRST",
  }]);
  const mode = content.querySelector('[aria-label="Agent RESTRICTED selection mode"] input:checked');
  const policy = content.querySelector('[aria-label="Agent RESTRICTED automatic selection policy"]');
  const model = content.querySelector('[aria-label="Agent RESTRICTED model"]');

  assert.equal(mode.value, "AUTO");
  assert.equal(policy.value, "QUALITY_FIRST");
  assert.equal(model.disabled, true);
  assert.match(content.textContent, /Required capabilities: Text, Tool Calling, Structured Output/);
  assert.match(content.textContent, /Currently eligible: Local Qwen 3.5 9B/);
  assert.doesNotMatch(content.textContent, /local_quality/);
});

function render(assignments = [{ consumer_id: "agent", data_classification: "RESTRICTED", model_id: "local_quality" }]) {
  const dom = new JSDOM("<main id='content'></main>");
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  const content = document.querySelector("#content");
  renderConfiguration(content, { catalog: CATALOG, consumers: CONSUMERS, assignments });
  return { content };
}

function model(model_id, display_name, execution_zone, max_data_classification, capabilities) {
  return { model_id, display_name, provider: "test", provider_model: "test/model", execution_zone, max_data_classification, capabilities, quality_class: "HIGH", cost_class: "LOW" };
}
