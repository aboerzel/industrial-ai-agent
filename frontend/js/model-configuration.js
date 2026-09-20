import {
  getModelAssignments,
  getModelCatalog,
  getModelConsumers,
  saveModelConfiguration,
} from "./api.js";

const CLASSIFICATIONS = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"];
const CLASSIFICATION_RANK = Object.fromEntries(CLASSIFICATIONS.map((item, index) => [item, index]));
const CAPABILITY_LABELS = {
  text: "Text", tool_calling: "Tools", structured_output: "Structured",
  vision: "Vision", embedding: "Embedding", object_detection: "Object detection", segmentation: "Segmentation",
};

export function mountModelConfiguration({ button, dialog }) {
  const content = dialog.querySelector("#model-configuration-content");
  const close = dialog.querySelector("#model-configuration-close");
  const saveStatus = dialog.querySelector("#model-configuration-save-status");
  button.addEventListener("click", async () => {
    dialog.showModal();
    await loadConfiguration(content, saveStatus);
  });
  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
}

export async function loadConfiguration(content, saveStatus = null) {
  content.replaceChildren(status("Loading configured models..."));
  setSaveStatus(saveStatus, "");
  try {
    const [catalog, consumers, assignments] = await Promise.all([
      getModelCatalog(), getModelConsumers(), getModelAssignments(),
    ]);
    renderConfiguration(content, { catalog, consumers, assignments }, saveStatus);
  } catch (error) {
    content.replaceChildren(status(error?.message ?? "Model configuration could not be loaded.", "error"));
  }
}

export function renderConfiguration(content, { catalog, consumers, assignments }, saveStatus = null) {
  const assignmentsByKey = new Map(assignments.map((item) => [`${item.consumer_id}:${item.data_classification}`, item]));
  const agent = consumers.find((consumer) => consumer.consumer_id === "agent");
  content.replaceChildren(
    agent ? renderConsumer(agent, catalog, assignmentsByKey, "Agent Models", saveStatus) : status("Agent model consumer is not configured.", "error"),
    ...consumers.filter((consumer) => consumer.consumer_id !== "agent").map((consumer) => renderConsumer(consumer, catalog, assignmentsByKey, "Specialized Models", saveStatus)),
  );
}

function renderConsumer(consumer, catalog, assignmentsByKey, title, saveStatus) {
  const section = document.createElement("section");
  section.className = "model-consumer-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const description = document.createElement("p");
  description.className = "model-consumer-description";
  description.textContent = consumer.consumer_id === "agent"
    ? "Models used by the main agent for reasoning, tool selection, and final responses."
    : "Models used for dedicated root-cause analysis based on already collected evidence, outside the main agent reasoning path.";
  section.append(heading, description);
  section.append(gridHeader());
  for (const classification of CLASSIFICATIONS) {
    section.append(renderAssignmentRow(consumer, classification, catalog, assignmentsByKey.get(`${consumer.consumer_id}:${classification}`), saveStatus));
  }
  return section;
}

function gridHeader() {
  const header = document.createElement("div");
  header.className = "model-assignment-grid-header";
  for (const label of ["Classification", "Mode", "Configuration", "Model details"]) {
    const cell = document.createElement("span");
    cell.textContent = label;
    header.append(cell);
  }
  return header;
}

function renderAssignmentRow(consumer, classification, catalog, assignment, saveStatus) {
  let confirmedAssignment = assignment ?? { selection_mode: "MANUAL", model_id: null, selection_policy: null };
  let queuedConfiguration = null;
  let saving = false;
  let changeGeneration = 0;
  let draftManualModelId = confirmedAssignment.model_id;
  const requirements = consumer.call_requirements ?? [{ call_type: "workflow", required_capabilities: consumer.required_capabilities }];
  const row = document.createElement("article");
  row.className = "model-assignment-row";
  row.dataset.consumerId = consumer.consumer_id;
  row.dataset.classification = classification;

  const heading = document.createElement("h4");
  heading.textContent = classification;
  const mode = selectionModeControl(`${consumer.display_name} ${classification} selection mode`, confirmedAssignment.selection_mode);
  const configuration = document.createElement("select");
  configuration.className = "model-selection-input";
  configuration.setAttribute("aria-label", `${consumer.display_name} ${classification} configuration`);
  const details = document.createElement("div");
  details.className = "model-assignment-meta";
  const feedback = document.createElement("p");
  feedback.className = "model-assignment-feedback";
  feedback.setAttribute("role", "status");
  feedback.setAttribute("aria-live", "polite");

  const automatic = () => selectedMode(mode) === "AUTO";
  const currentConfiguration = () => ({
    selectionMode: automatic() ? "AUTO" : "MANUAL",
    modelId: automatic() ? null : configuration.value || null,
    selectionPolicy: automatic() ? configuration.value : null,
  });
  const renderDetails = () => {
    showModelDetails(
      details,
      automatic() ? null : catalog.find((model) => model.model_id === configuration.value),
      requirements,
      classification,
      feedback,
      automatic() ? eligibleModels(catalog, requirements, classification) : null,
    );
  };
  const update = () => {
    populateConfiguration(
      configuration,
      catalog,
      classification,
      automatic() ? null : draftManualModelId,
      confirmedAssignment.selection_policy,
      automatic(),
    );
    renderDetails();
  };
  const restoreConfirmed = () => {
    setSelectedMode(mode, confirmedAssignment.selection_mode ?? "MANUAL");
    draftManualModelId = confirmedAssignment.model_id;
    update();
  };
  const queueSave = () => {
    const next = currentConfiguration();
    const selected = catalog.find((model) => model.model_id === next.modelId);
    if (next.selectionMode === "MANUAL" && (!selected || !isAllowed(selected, classification) || selected.runtime_available === false)) {
      restoreConfirmed();
      return;
    }
    queuedConfiguration = { configuration: next, generation: ++changeGeneration };
    setSaveStatus(saveStatus, "Saving...");
    void saveNext();
  };
  const saveNext = async () => {
    if (saving || !queuedConfiguration) return;
    saving = true;
    const request = queuedConfiguration;
    queuedConfiguration = null;
    try {
      const persisted = await saveModelConfiguration(consumer.consumer_id, classification, request.configuration);
      confirmedAssignment = persisted;
      if (request.generation === changeGeneration) {
        feedback.textContent = "";
        restoreConfirmed();
        setSaveStatus(saveStatus, "Saved");
      }
    } catch {
      if (request.generation === changeGeneration && !queuedConfiguration) {
        feedback.textContent = "";
        restoreConfirmed();
        feedback.textContent = "Could not save model configuration.";
        feedback.classList.add("error");
        details.append(feedback);
        setSaveStatus(saveStatus, "Could not save model configuration.", "error");
      }
    } finally {
      saving = false;
      if (queuedConfiguration) {
        feedback.classList.remove("error");
        feedback.textContent = "";
        setSaveStatus(saveStatus, "Saving...");
        void saveNext();
      }
    }
  };

  update();
  configuration.addEventListener("change", () => {
    if (!automatic()) draftManualModelId = configuration.value || null;
    renderDetails();
    queueSave();
  });
  mode.addEventListener("change", () => {
    update();
    if (!automatic() && !configuration.value) {
      feedback.textContent = "Select a model to use manual mode.";
      details.append(feedback);
      return;
    }
    queueSave();
  });
  row.append(heading, mode, configuration, details);
  return row;
}

function populateConfiguration(select, catalog, classification, manualModelId, selectionPolicy, automatic) {
  select.replaceChildren();
  if (automatic) {
    select.add(option("Quality first", "QUALITY_FIRST", selectionPolicy !== "COST_FIRST"));
    select.add(option("Cost first", "COST_FIRST", selectionPolicy === "COST_FIRST"));
    return;
  }
  const assignedModel = catalog.find((model) => model.model_id === manualModelId);
  const placeholder = option("Unconfigured", "", !assignedModel);
  placeholder.disabled = true;
  select.add(placeholder);
  for (const model of catalog) {
    const allowed = isAllowed(model, classification);
    const available = model.runtime_available !== false;
    const item = option(model.display_name, model.model_id, manualModelId === model.model_id);
    item.disabled = !allowed || !available;
    if (!allowed) item.textContent = `${model.display_name} - Not allowed for ${classification} data`;
    else if (!available) item.textContent = `${model.display_name} - Not configured`;
    select.add(item);
  }
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

function selectedMode(control) { return control.querySelector("input:checked")?.value ?? "MANUAL"; }
function setSelectedMode(control, value) { const input = control.querySelector(`input[value="${value}"]`); if (input) input.checked = true; }

function showModelDetails(container, model, callRequirements, classification, feedback, eligible = null) {
  container.replaceChildren();
  if (eligible !== null) {
    container.append(detail(`AUTO · ${eligible.length} eligible model${eligible.length === 1 ? "" : "s"}`));
    container.append(detail(`Required: ${workflowCapabilities(callRequirements).map(labelCapability).join(" · ")}`));
  } else if (!model) {
    container.append(detail("Unconfigured"));
  } else {
    container.append(detail(`${model.execution_zone === "LOCAL" ? "LOCAL" : "PUBLIC"} · Cost ${model.cost_class} · Quality ${model.quality_class} · ${model.runtime_available === false ? "Unavailable" : "Available"}`));
    container.append(detail(model.capabilities.map(labelCapability).join(" · ")));
    const compatibility = compatibilityForCallRequirements(model, callRequirements);
    if (compatibility.missing.length) container.append(warning(`Compatibility warning: missing ${compatibility.missing.map(labelCapability).join(", ")}.`));
    if (compatibility.incompatibleCombination) container.append(warning(`Compatibility warning: this model cannot combine ${compatibility.incompatibleCombination.map(labelCapability).join(" and ")}.`));
    if (!isAllowed(model, classification)) feedback.textContent = `Not allowed for ${classification} data.`;
  }
  if (feedback.textContent) container.append(feedback);
}

function detail(value) { const item = document.createElement("span"); item.className = "model-detail"; item.textContent = value; return item; }
function warning(message) { const item = document.createElement("p"); item.className = "model-capability-warning"; item.textContent = message; return item; }
function labelCapability(item) { return CAPABILITY_LABELS[item] ?? item; }
function eligibleModels(catalog, callRequirements, classification) { return catalog.filter((model) => isAllowed(model, classification) && model.runtime_available !== false && compatibilityForCallRequirements(model, callRequirements).compatible); }
function workflowCapabilities(callRequirements) { return [...new Set(callRequirements.flatMap((requirement) => requirement.required_capabilities))]; }

function compatibilityForCallRequirements(model, callRequirements) {
  for (const requirement of callRequirements) {
    const missing = requirement.required_capabilities.filter((item) => !model.capabilities.includes(item));
    if (missing.length) return { compatible: false, missing, incompatibleCombination: null };
    const incompatibleCombination = (model.incompatible_capability_combinations ?? []).find((combination) => combination.every((item) => requirement.required_capabilities.includes(item)));
    if (incompatibleCombination) return { compatible: false, missing: [], incompatibleCombination };
  }
  return { compatible: true, missing: [], incompatibleCombination: null };
}

function isAllowed(model, classification) { return !(classification === "RESTRICTED" && model.execution_zone !== "LOCAL") && CLASSIFICATION_RANK[classification] <= CLASSIFICATION_RANK[model.max_data_classification]; }
function option(label, value, selected) { const item = document.createElement("option"); item.textContent = label; item.value = value; item.selected = selected; return item; }
function status(message, kind = "") { const element = document.createElement("p"); element.className = `model-configuration-status ${kind}`; element.textContent = message; return element; }
function setSaveStatus(element, message, kind = "") { if (element) { element.textContent = message; element.classList.toggle("error", kind === "error"); } }
