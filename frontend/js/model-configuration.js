import {
  getModelAssignments,
  getModelCatalog,
  getModelConsumers,
  saveModelAssignment,
} from "./api.js";

const CLASSIFICATIONS = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"];
const CLASSIFICATION_RANK = Object.fromEntries(CLASSIFICATIONS.map((item, index) => [item, index]));
const CAPABILITY_LABELS = {
  text: "Text", tool_calling: "Tool Calling", structured_output: "Structured Output",
  vision: "Vision", embedding: "Embedding", object_detection: "Object Detection", segmentation: "Segmentation",
};

export function mountModelConfiguration({ button, dialog }) {
  const content = dialog.querySelector("#model-configuration-content");
  const close = dialog.querySelector("#model-configuration-close");
  button.addEventListener("click", async () => {
    dialog.showModal();
    await loadConfiguration(content);
  });
  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
}

export async function loadConfiguration(content) {
  content.replaceChildren(status("Loading configured models..."));
  try {
    const [catalog, consumers, assignments] = await Promise.all([
      getModelCatalog(), getModelConsumers(), getModelAssignments(),
    ]);
    renderConfiguration(content, { catalog, consumers, assignments });
  } catch (error) {
    content.replaceChildren(status(error?.message ?? "Model configuration could not be loaded.", "error"));
  }
}

export function renderConfiguration(content, { catalog, consumers, assignments }) {
  const assignmentsByKey = new Map(assignments.map((item) => [`${item.consumer_id}:${item.data_classification}`, item]));
  const agent = consumers.find((consumer) => consumer.consumer_id === "agent");
  content.replaceChildren(
    agent ? renderConsumer(agent, catalog, assignmentsByKey, "Agent Models") : status("Agent model consumer is not configured.", "error"),
    ...consumers.filter((consumer) => consumer.consumer_id !== "agent").map((consumer) => renderConsumer(consumer, catalog, assignmentsByKey, "Specialized Models")),
  );
}

function renderConsumer(consumer, catalog, assignmentsByKey, title) {
  const section = document.createElement("section");
  section.className = "model-consumer-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const label = document.createElement("p");
  label.className = "model-consumer-label";
  label.textContent = consumer.display_name;
  section.append(heading, label);
  for (const classification of CLASSIFICATIONS) {
    section.append(renderAssignmentRow(consumer, classification, catalog, assignmentsByKey.get(`${consumer.consumer_id}:${classification}`)));
  }
  return section;
}

function renderAssignmentRow(consumer, classification, catalog, assignment) {
  const row = document.createElement("article");
  row.className = "model-assignment-row";
  const heading = document.createElement("h4");
  heading.textContent = classification;
  const select = document.createElement("select");
  select.setAttribute("aria-label", `${consumer.display_name} ${classification} model`);
  const assignedModel = catalog.find((model) => model.model_id === assignment?.model_id);
  const placeholder = option("Unconfigured", "", !assignedModel);
  placeholder.disabled = true;
  select.add(placeholder);
  for (const model of catalog) {
    const allowed = isAllowed(model, classification);
    const item = option(model.display_name, model.model_id, assignment?.model_id === model.model_id);
    item.disabled = !allowed;
    if (!allowed) item.textContent = `${model.display_name} — Not allowed for ${classification} data`;
    select.add(item);
  }
  const meta = document.createElement("div");
  meta.className = "model-assignment-meta";
  const feedback = document.createElement("p");
  feedback.className = "model-assignment-feedback";
  const save = document.createElement("button");
  save.type = "button";
  save.className = "secondary-button";
  save.textContent = "Save";
  const update = () => showModelDetails(meta, catalog.find((model) => model.model_id === select.value), consumer.required_capabilities, classification, feedback);
  update();
  select.addEventListener("change", update);
  save.addEventListener("click", async () => {
    const selected = catalog.find((model) => model.model_id === select.value);
    if (!selected || !isAllowed(selected, classification)) return;
    save.disabled = true;
    feedback.textContent = "Saving...";
    try {
      const persisted = await saveModelAssignment(consumer.consumer_id, classification, selected.model_id);
      select.value = persisted.model_id;
      feedback.textContent = "Saved.";
    } catch (error) {
      select.value = assignment?.model_id ?? "";
      feedback.textContent = error?.message ?? "The assignment could not be saved.";
      update();
    } finally { save.disabled = false; }
  });
  row.append(heading, select, meta, save, feedback);
  return row;
}

function showModelDetails(container, model, requiredCapabilities, classification, feedback) {
  container.replaceChildren();
  if (!model) {
    const notice = document.createElement("p");
    notice.className = "model-unconfigured";
    notice.textContent = "Unconfigured. No model will be selected automatically.";
    container.append(notice);
    return;
  }
  const details = document.createElement("p");
  details.textContent = `${model.execution_zone === "LOCAL" ? "LOCAL" : "PUBLIC"} · Cost: ${model.cost_class} · Quality: ${model.quality_class}`;
  const capabilities = document.createElement("p");
  capabilities.textContent = `Capabilities: ${model.capabilities.map((item) => CAPABILITY_LABELS[item] ?? item).join(", ")}`;
  container.append(details, capabilities);
  const missing = requiredCapabilities.filter((item) => !model.capabilities.includes(item));
  if (missing.length) {
    const warning = document.createElement("p");
    warning.className = "model-capability-warning";
    warning.textContent = `Compatibility warning: missing ${missing.map((item) => CAPABILITY_LABELS[item] ?? item).join(", ")}. Execution will fail with CAPABILITY_MISMATCH.`;
    container.append(warning);
  }
  if (!isAllowed(model, classification)) feedback.textContent = `Not allowed for ${classification} data.`;
}

function isAllowed(model, classification) {
  return !(classification === "RESTRICTED" && model.execution_zone !== "LOCAL") && CLASSIFICATION_RANK[classification] <= CLASSIFICATION_RANK[model.max_data_classification];
}

function option(label, value, selected) {
  const item = document.createElement("option");
  item.textContent = label;
  item.value = value;
  item.selected = selected;
  return item;
}

function status(message, kind = "") {
  const element = document.createElement("p");
  element.className = `model-configuration-status ${kind}`;
  element.textContent = message;
  return element;
}
