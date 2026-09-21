import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "../../frontend/node_modules/jsdom/lib/api.js";

import {
  mountModelConfiguration,
  renderConfiguration,
} from "../../frontend/js/model-configuration.js";

const CATALOG = [
  model("local_quality", "Local Qwen 3.5 9B", "LOCAL", "RESTRICTED", ["text", "tool_calling", "structured_output"]),
  model("nvidia_quality", "NVIDIA Nemotron", "PUBLIC_CLOUD", "CONFIDENTIAL", ["text", "tool_calling", "structured_output"]),
  model("groq_benchmark", "Groq Llama", "PUBLIC_CLOUD", "CONFIDENTIAL", ["text", "tool_calling", "structured_output"], [["tool_calling", "structured_output"]]),
  model("mistral_fast", "Mistral Small", "PUBLIC_CLOUD", "CONFIDENTIAL", ["text", "tool_calling"], [], false),
  model("public_text", "Public Text", "PUBLIC_CLOUD", "CONFIDENTIAL", ["text"]),
];
const CONSUMERS = [
  {
    consumer_id: "agent", display_name: "Agent", required_capabilities: ["text", "tool_calling", "structured_output"],
    call_requirements: [
      { call_type: "tool_decision", required_capabilities: ["text", "tool_calling"] },
      { call_type: "structured_response", required_capabilities: ["text", "structured_output"] },
    ],
  },
  { consumer_id: "rca.reasoning", display_name: "Root Cause Analysis", required_capabilities: ["text", "structured_output"] },
];

test("renders display names, all classifications, dynamic specialized consumers, and persisted selection", () => {
  const { content } = render();
  assert.match(content.textContent, /Local Qwen 3.5 9B/);
  assert.match(content.textContent, /Models used by the main agent for reasoning, tool selection, and final responses/);
  assert.match(content.textContent, /Models used for dedicated root-cause analysis based on already collected evidence/);
  assert.doesNotMatch(content.textContent, /Root Cause Analysis/);
  for (const classification of ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]) assert.match(content.textContent, new RegExp(classification));
  const restricted = content.querySelector('[aria-label="Agent RESTRICTED configuration"]');
  assert.equal(restricted.value, "local_quality");
  assert.doesNotMatch(restricted.selectedOptions[0].textContent, /local_quality/);
  assert.equal(content.querySelectorAll(".model-assignment-row").length, 8);
  assert.equal(content.querySelectorAll('[data-consumer-id="rca.reasoning"]').length, 4);
  assert.equal(content.querySelectorAll(".model-assignment-grid-header").length, 2);
  assert.equal(content.querySelectorAll(".model-assignment-row button").length, 0);
});

test("keeps forbidden public models visible but disabled and shows capability warnings", () => {
  const { content } = render();
  const restricted = content.querySelector('[aria-label="Agent RESTRICTED configuration"]');
  const forbidden = [...restricted.options].find((option) => option.value === "nvidia_quality");
  assert.equal(forbidden.disabled, true);
  assert.match(forbidden.textContent, /Not allowed for RESTRICTED data/);
  const publicSelect = content.querySelector('[aria-label="Agent PUBLIC configuration"]');
  publicSelect.value = "public_text";
  publicSelect.dispatchEvent(new window.Event("change"));
  assert.match(content.textContent, /Compatibility warning: missing Tools/);
});

test("does not mislabel Groq as missing structured output when calls are separate", () => {
  const { content } = render([
    { consumer_id: "agent", data_classification: "CONFIDENTIAL", model_id: "groq_benchmark" },
  ]);

  const confidential = content.querySelector('[aria-label="Agent CONFIDENTIAL configuration"]');
  assert.equal(confidential.selectedOptions[0].textContent, "Groq Llama");
  assert.doesNotMatch(content.textContent, /missing Structured Output/);
  assert.doesNotMatch(content.textContent, /not together in the same model request/);
});

test("shows a combination warning only for a simultaneous call requirement", () => {
  const { content } = render(
    [{ consumer_id: "combined", data_classification: "CONFIDENTIAL", model_id: "groq_benchmark" }],
    [{
      consumer_id: "combined", display_name: "Combined request", required_capabilities: ["text", "tool_calling", "structured_output"],
      call_requirements: [{
        call_type: "tool_decision_structured",
        required_capabilities: ["text", "tool_calling", "structured_output"],
      }],
    }],
  );

  assert.match(content.textContent, /Compatibility warning: this model cannot combine Tools and Structured/);
});

test("keeps statically unavailable catalog models visible but disabled", () => {
  const { content } = render();
  const publicSelect = content.querySelector('[aria-label="Agent PUBLIC configuration"]');
  const mistral = [...publicSelect.options].find((option) => option.value === "mistral_fast");

  assert.equal(mistral.disabled, true);
  assert.match(mistral.textContent, /Mistral Small/);
  assert.match(mistral.textContent, /Not configured/);
  assert.doesNotMatch(mistral.textContent, /mistral_fast/);
});

test("shows missing assignment and catalog references without choosing a fallback", () => {
  const { content } = render([{ consumer_id: "agent", data_classification: "RESTRICTED", model_id: "removed_model" }]);
  const restricted = content.querySelector('[aria-label="Agent RESTRICTED configuration"]');
  assert.equal(restricted.value, "");
  assert.match(content.textContent, /Unconfigured/);
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
  const policy = content.querySelector('[aria-label="Agent RESTRICTED configuration"]');

  assert.equal(mode.value, "AUTO");
  assert.equal(policy.value, "QUALITY_FIRST");
  assert.match(content.textContent, /AUTO · 1 eligible model/);
  assert.match(content.textContent, /Required: Text · Tools · Structured/);
  assert.doesNotMatch(content.textContent, /local_quality/);
});

test("keeps the same row grid when switching between manual and automatic modes", () => {
  const { content } = render();
  const row = content.querySelector('.model-assignment-row[data-consumer-id="agent"][data-classification="RESTRICTED"]');
  const childrenBefore = [...row.children].map((node) => node.className || node.tagName);
  const auto = row.querySelector('input[value="AUTO"]');
  auto.checked = true;
  auto.dispatchEvent(new window.Event("change", { bubbles: true }));
  assert.deepEqual([...row.children].map((node) => node.className || node.tagName), childrenBefore);
  assert.equal(row.querySelectorAll('[aria-label="Agent RESTRICTED configuration"]').length, 1);
});

test("auto-saves a manual model change with one global confirmation", async () => {
  const { content, saveStatus, bodies, restoreFetch } = renderWithSave((body) => ({
    ...body,
    model_id: "nvidia_quality",
    selection_mode: "MANUAL",
    selection_policy: null,
  }));
  try {
    const select = content.querySelector('[aria-label="Agent PUBLIC configuration"]');
    select.value = "nvidia_quality";
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
    await settle();
    assert.equal(bodies.length, 1);
    assert.equal(bodies[0].consumer_id, "agent");
    assert.equal(bodies[0].data_classification, "PUBLIC");
    assert.equal(saveStatus.textContent, "Saved");
    assert.equal(content.querySelectorAll(".model-assignment-feedback").length, 0);
    assert.equal(select.value, "nvidia_quality");
  } finally {
    restoreFetch();
  }
});

test("auto-saves an automatic policy change with one global confirmation", async () => {
  const { content, saveStatus, restoreFetch, bodies } = renderWithSave((body) => ({
    ...body, model_id: null, selection_mode: "AUTO", selection_policy: "COST_FIRST",
  }), [{
    consumer_id: "agent", data_classification: "PUBLIC", model_id: null,
    selection_mode: "AUTO", selection_policy: "QUALITY_FIRST",
  }]);
  try {
    const policy = content.querySelector('[aria-label="Agent PUBLIC configuration"]');
    policy.value = "COST_FIRST";
    policy.dispatchEvent(new window.Event("change", { bubbles: true }));
    await settle();
    assert.equal(bodies[0].selection_policy, "COST_FIRST");
    assert.equal(policy.value, "COST_FIRST");
    assert.equal(saveStatus.textContent, "Saved");
    assert.equal(content.querySelectorAll(".model-assignment-feedback").length, 0);
  } finally {
    restoreFetch();
  }
});

test("restores the confirmed assignment when auto-save fails", async () => {
  const { content, restoreFetch } = renderWithSave(() => new Error("Could not save model configuration."));
  try {
    const select = content.querySelector('[aria-label="Agent PUBLIC configuration"]');
    const previous = select.value;
    select.value = "nvidia_quality";
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
    await settle();
    assert.equal(select.value, previous);
    assert.match(content.textContent, /Could not save model configuration/);
  } finally {
    restoreFetch();
  }
});

test("serializes rapid changes so a stale response cannot overwrite the latest selection", async () => {
  const dom = new JSDOM("<main id='content'></main><p id='save-status'></p>");
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  const originalFetch = globalThis.fetch;
  const pending = [];
  globalThis.fetch = async (_url, options) => new Promise((resolve) => {
    pending.push({ body: JSON.parse(options.body), resolve });
  });
  try {
    const content = document.querySelector("#content");
    renderConfiguration(content, { catalog: CATALOG, consumers: CONSUMERS, assignments: [] }, document.querySelector("#save-status"));
    const select = content.querySelector('[aria-label="Agent PUBLIC configuration"]');
    select.value = "nvidia_quality";
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
    select.value = "groq_benchmark";
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
    assert.equal(pending.length, 1);
    pending[0].resolve(jsonResponse({ ...pending[0].body }));
    await settle();
    assert.equal(pending.length, 2);
    pending[1].resolve(jsonResponse({ ...pending[1].body }));
    await settle();
    assert.equal(select.value, "groq_benchmark");
    assert.equal(document.querySelector("#save-status").textContent, "Saved");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("opens, loads, closes, and reopens the production model configuration dialog", async () => {
  const dom = new JSDOM(`
    <button id="model-configuration-button" type="button">Configure models</button>
    <dialog id="model-configuration-dialog">
      <header class="model-configuration-header">
        <div class="model-configuration-title-group"><svg class="settings-icon" width="18" height="18"></svg><h2 id="model-configuration-title">Model Configuration</h2></div>
        <p id="model-configuration-save-status" role="status" aria-live="polite"></p>
        <button id="model-configuration-close" type="button">Close</button>
      </header>
      <div id="model-configuration-content"></div>
    </dialog>
  `);
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  const dialog = document.querySelector("#model-configuration-dialog");
  dialog.showModal = () => { dialog.open = true; };
  dialog.close = () => { dialog.open = false; };
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    const path = new URL(String(url)).pathname;
    requests.push({ method: options.method ?? "GET", path });
    const payload = path.endsWith("/models") ? CATALOG
      : path.endsWith("/model-consumers") ? CONSUMERS
      : [{
        consumer_id: "agent",
        data_classification: "RESTRICTED",
        model_id: "local_quality",
        selection_mode: "MANUAL",
        selection_policy: null,
      }];
    return new Response(JSON.stringify(payload), { status: 200 });
  };
  try {
    mountModelConfiguration({
      button: document.querySelector("#model-configuration-button"),
      dialog,
    });

    document.querySelector("#model-configuration-button").click();
    await waitForConfiguration();
    assert.equal(dialog.open, true);
    assert.match(dialog.textContent, /Agent Models/);
    assert.match(dialog.textContent, /Specialized Models/);
    assert.equal(dialog.querySelectorAll("#model-configuration-save-status").length, 1);
    assert.deepEqual(requests.sort((left, right) => left.path.localeCompare(right.path)), [
      { method: "GET", path: "/api/v1/model-assignments" },
      { method: "GET", path: "/api/v1/model-consumers" },
      { method: "GET", path: "/api/v1/models" },
    ]);

    document.querySelector("#model-configuration-close").click();
    assert.equal(dialog.open, false);

    requests.length = 0;
    document.querySelector("#model-configuration-button").click();
    await waitForConfiguration();
    assert.equal(dialog.open, true);
    assert.equal(requests.length, 3);
    assert.ok(requests.every((request) => request.method === "GET"));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

function render(
  assignments = [{ consumer_id: "agent", data_classification: "RESTRICTED", model_id: "local_quality" }],
  consumers = CONSUMERS,
) {
  const dom = new JSDOM("<main id='content'></main><p id='save-status'></p>");
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  const content = document.querySelector("#content");
  const saveStatus = document.querySelector("#save-status");
  renderConfiguration(content, { catalog: CATALOG, consumers, assignments }, saveStatus);
  return { content, saveStatus };
}

function renderWithSave(result, assignments = []) {
  const { content, saveStatus } = render(assignments);
  const originalFetch = globalThis.fetch;
  const bodies = [];
  globalThis.fetch = async (_url, options) => {
    const body = JSON.parse(options.body);
    bodies.push(body);
    const payload = result(body);
    if (payload instanceof Error) return new Response(JSON.stringify({
      code: "save_failed", message: payload.message,
    }), { status: 500, headers: { "Content-Type": "application/json" } });
    return jsonResponse(payload);
  };
  return { content, saveStatus, bodies, restoreFetch: () => { globalThis.fetch = originalFetch; } };
}

function jsonResponse(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

async function waitForConfiguration() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function model(model_id, display_name, execution_zone, max_data_classification, capabilities, incompatible_capability_combinations = [], runtime_available = true) {
  return { model_id, display_name, provider: "test", provider_model: "test/model", execution_zone, max_data_classification, capabilities, incompatible_capability_combinations, runtime_available, quality_class: "HIGH", cost_class: "LOW" };
}
