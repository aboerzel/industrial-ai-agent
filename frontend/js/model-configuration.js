import {
  getModelAssignments,
  getModelCatalog,
  getModelConsumers,
  saveModelConfiguration,
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
  let persistedAssignment = assignment;
  const row = document.createElement("article");
  row.className = "model-assignment-row";
  const heading = document.createElement("h4");
  heading.textContent = classification;
  const mode = selectionModeControl(
    `${consumer.display_name} ${classification} selection mode`,
    assignment?.selection_mode ?? "MANUAL",
  );
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
  const policy = document.createElement("select");
  policy.setAttribute("aria-label", `${consumer.display_name} ${classification} automatic selection policy`);
  policy.add(option("Quality first", "QUALITY_FIRST", assignment?.selection_policy !== "COST_FIRST"));
  policy.add(option("Cost first", "COST_FIRST", assignment?.selection_policy === "COST_FIRST"));
  const update = () => {
    const automatic = selectedMode(mode) === "AUTO";
    select.disabled = automatic;
    policy.hidden = !automatic;
    showModelDetails(
      meta,
      automatic ? null : catalog.find((model) => model.model_id === select.value),
      consumer.required_capabilities,
      classification,
      feedback,
      automatic ? eligibleModels(catalog, consumer.required_capabilities, classification) : null,
    );
  };
  update();
  select.addEventListener("change", update);
  mode.addEventListener("change", update);
  policy.addEventListener("change", update);
  save.addEventListener("click", async () => {
    const automatic = selectedMode(mode) === "AUTO";
    const selected = catalog.find((model) => model.model_id === select.value);
    if (!automatic && (!selected || !isAllowed(selected, classification))) return;
    save.disabled = true;
    feedback.textContent = "Saving...";
    try {
      const persisted = await saveModelConfiguration(consumer.consumer_id, classification, {
        selectionMode: selectedMode(mode),
        modelId: automatic ? null : selected.model_id,
        selectionPolicy: automatic ? policy.value : null,
      });
      persistedAssignment = persisted;
      setSelectedMode(mode, persistedAssignment.selection_mode);
      select.value = persistedAssignment.model_id ?? "";
      policy.value = persistedAssignment.selection_policy ?? "QUALITY_FIRST";
      feedback.textContent = "Saved.";
    } catch (error) {
      setSelectedMode(mode, persistedAssignment?.selection_mode ?? "MANUAL");
      select.value = persistedAssignment?.model_id ?? "";
      policy.value = persistedAssignment?.selection_policy ?? "QUALITY_FIRST";
      feedback.textContent = error?.message ?? "The assignment could not be saved.";
      update();
    } finally { save.disabled = false; }
  });
  row.append(heading, mode, select, policy, meta, save, feedback);
  return row;
}

function selectionModeControl(label, value) {
  const fieldset = document.createElement("fieldset");
  fieldset.className = "model-selection-mode";
  fieldset.setAttribute("aria-label", label);
  for (const [mode, text] of [["MANUAL", "Manual"], ["AUTO", "Automatic"]]) {
    const optionId = `${label}-${mode}`.replace(/[^a-z0-9]+/gi, "-").toLowerCase();
    const input = document.createElement("input");
    input.type = "radio";
    input.name = `${label}-mode`;
    input.id = optionId;
    input.value = mode;
    input.checked = mode === value;
    const optionLabel = document.createElement("label");
    optionLabel.htmlFor = optionId;
    optionLabel.textContent = text;
    fieldset.append(input, optionLabel);
  }
  return fieldset;
}

function selectedMode(control) {
  return control.querySelector("input:checked")?.value ?? "MANUAL";
}

function setSelectedMode(control, value) {
  const input = control.querySelector(`input[value="${value}"]`);
  if (input) input.checked = true;
}

function showModelDetails(container, model, requiredCapabilities, classification, feedback, preview = null) {
  container.replaceChildren();
  if (preview !== null) {
    const required = document.createElement("p");
    required.textContent = `Required capabilities: ${requiredCapabilities.map((item) => CAPABILITY_LABELS[item] ?? item).join(", ")}`;
    const eligible = document.createElement("p");
    eligible.textContent = preview.length
      ? `Currently eligible: ${preview.map((item) => item.display_name).join(", ")}`
      : "No currently eligible model. Execution will be denied.";
    container.append(required, eligible);
    return;
  }
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

function eligibleModels(catalog, requiredCapabilities, classification) {
  return catalog.filter((model) => isAllowed(model, classification) && requiredCapabilities.every((item) => model.capabilities.includes(item)));
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
