import {
  ApiClientError,
  createRun,
  downloadDocument,
  downloadInvestigationPdf,
  getInvestigation,
  openDocument,
  resumeRun,
} from "./api.js";
import { renderAgentAnswer } from "./markdown.js";

const composerForm = document.querySelector("#composer-form");
const composerMessage = document.querySelector("#composer-message");
const composerButton = document.querySelector("#composer-button");
const userClearance = document.querySelector("#user-clearance");
const responseLanguage = document.querySelector("#response-language");
const newInvestigationButton = document.querySelector("#new-investigation-button");
const history = document.querySelector("#conversation-history");
const runStatus = document.querySelector("#run-status");
const resultTitle = document.querySelector("#result-title");
const exportPdfButton = document.querySelector("#export-pdf-button");
const errorMessage = document.querySelector("#error-message");
const ACTIVE_INVESTIGATION_STORAGE_KEY = "industrial-ai-agent.active-investigation";

let currentInvestigationId = null;
let isSubmitting = false;
let pendingAgentTurn = null;

composerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitRequest(composerMessage.value.trim());
});

composerMessage.addEventListener("keydown", (event) => {
  if (
    event.key !== "Enter" ||
    event.shiftKey ||
    event.isComposing ||
    isSubmitting ||
    !composerMessage.value.trim()
  ) {
    return;
  }
  event.preventDefault();
  composerForm.requestSubmit();
});

userClearance.addEventListener("change", persistUiState);
responseLanguage.addEventListener("change", persistUiState);

newInvestigationButton.addEventListener("click", () => {
  if (isSubmitting) return;
  renderEmptyInvestigation();
  composerMessage.focus();
});

exportPdfButton.addEventListener("click", () => {
  if (currentInvestigationId) {
    downloadInvestigationPdf(currentInvestigationId, userClearance.value);
  }
});

void restoreActiveInvestigation();

async function restoreActiveInvestigation() {
  const activeInvestigation = readActiveInvestigation();
  if (!activeInvestigation) {
    renderEmptyInvestigation();
    return;
  }

  currentInvestigationId = activeInvestigation.investigationId;
  userClearance.value = activeInvestigation.userClearance;
  responseLanguage.value = activeInvestigation.responseLanguage;
  if (!activeInvestigation.investigationId) {
    renderEmptyInvestigation();
    return;
  }
  try {
    await reloadInvestigation();
  } catch {
    clearActiveInvestigation();
    renderEmptyInvestigation();
  }
}

async function submitRequest(message) {
  if (!message) {
    showError("Enter a troubleshooting request before starting an investigation.");
    composerMessage.focus();
    return;
  }
  if (isSubmitting) return;

  const isNewInvestigation = currentInvestigationId === null;
  renderPendingConversation(message, { replace: isNewInvestigation });
  setSubmitting();
  try {
    const result = await createRun(
      message,
      userClearance.value,
      responseLanguage.value,
      currentInvestigationId,
    );
    currentInvestigationId = result.investigation_id;
    composerMessage.value = "";
    await reloadInvestigation();
  } catch (error) {
    renderPendingFailure(error, responseLanguage.value);
  } finally {
    isSubmitting = false;
    syncControls();
  }
}

async function reloadInvestigation() {
  if (!currentInvestigationId) return;
  renderInvestigation(
    await getInvestigation(currentInvestigationId, userClearance.value),
  );
}

function renderEmptyInvestigation() {
  currentInvestigationId = null;
  pendingAgentTurn = null;
  clearActiveInvestigation();
  resultTitle.textContent = "Investigation";
  hideStatus();
  history.classList.add("empty-state");
  history.replaceChildren(createEmptyState());
  hideError();
  syncControls();
}

function renderInvestigation(investigation) {
  hideError();
  pendingAgentTurn = null;
  currentInvestigationId = investigation.investigation_id;
  persistActiveInvestigation(currentInvestigationId);
  resultTitle.textContent = "Investigation";
  setStatus(investigation.status);
  history.classList.remove("empty-state");
  history.replaceChildren(
    ...investigation.turns.flatMap((turn) => [
      renderUserTurn(turn),
      renderAgentTurn(turn),
    ]),
  );
  scrollHistoryToLatest();
  syncControls();
}

function persistActiveInvestigation(investigationId) {
  window.sessionStorage.setItem(
    ACTIVE_INVESTIGATION_STORAGE_KEY,
    JSON.stringify({
      investigationId,
      userClearance: userClearance.value,
      responseLanguage: responseLanguage.value,
    }),
  );
}

function clearActiveInvestigation() {
  persistActiveInvestigation(null);
}

function persistUiState() {
  persistActiveInvestigation(currentInvestigationId);
}

function readActiveInvestigation() {
  try {
    const stored = JSON.parse(
      window.sessionStorage.getItem(ACTIVE_INVESTIGATION_STORAGE_KEY) ?? "null",
    );
    if (
      !stored ||
      (stored.investigationId !== null && typeof stored.investigationId !== "string") ||
      !["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"].includes(
        stored.userClearance,
      ) ||
      !["DE", "EN"].includes(stored.responseLanguage ?? "EN")
    ) {
      return null;
    }
    return { ...stored, responseLanguage: stored.responseLanguage ?? "EN" };
  } catch {
    return null;
  }
}

function renderPendingConversation(message, { replace }) {
  hideError();
  resultTitle.textContent = "Investigation";
  if (replace) {
    history.replaceChildren();
  }
  history.classList.remove("empty-state");
  const turn = { request: message, status: "running" };
  pendingAgentTurn = renderAgentTurn(turn);
  history.append(renderUserTurn(turn), pendingAgentTurn);
  setStatus("running");
  scrollHistoryToLatest();
}

function renderPendingFailure(error, selectedLanguage) {
  const providerLimited = isProviderLimitError(error?.code);
  const message = publicError(error, "The agent run could not be completed.");
  if (pendingAgentTurn) {
    pendingAgentTurn.classList.remove("is-pending");
    pendingAgentTurn.classList.add(providerLimited ? "is-limit" : "is-error");
    pendingAgentTurn.replaceChildren(
      createTurnLabel("Agent"),
      createTurnError(error?.code, message, selectedLanguage),
    );
  } else {
    showError(message);
  }
  pendingAgentTurn = null;
  setStatus(providerLimited ? "limit_reached" : "failed", selectedLanguage);
  scrollHistoryToLatest();
}

function createEmptyState() {
  const emptyState = document.createElement("div");
  emptyState.className = "empty-investigation";
  const title = document.createElement("h3");
  title.textContent = "Start a new chat";
  const detail = document.createElement("p");
  detail.textContent =
    "Ask about a production issue, station, product, maintenance ticket, or available documentation.";
  emptyState.append(title, detail);
  return emptyState;
}

function renderUserTurn(turn) {
  const article = document.createElement("article");
  article.className = "conversation-message user-turn";
  article.append(createTurnLabel("You"));
  const request = document.createElement("p");
  request.className = "user-request";
  request.textContent = turn.request;
  article.append(request);
  return article;
}

function renderAgentTurn(turn) {
  const article = document.createElement("article");
  article.className = "conversation-message agent-turn";
  article.append(createTurnLabel("Agent"));

  if (turn.status === "running") {
    article.classList.add("is-pending");
    const pending = document.createElement("p");
    pending.className = "turn-pending";
    pending.textContent = "Investigating...";
    article.append(pending);
    return article;
  }

  if (turn.status === "failed") {
    const providerLimited = isProviderLimitError(turn.error?.code);
    article.classList.add(providerLimited ? "is-limit" : "is-error");
    article.append(
      createTurnError(
        turn.error?.code,
        turn.error?.message ?? "The agent run could not be completed.",
        turn.response_language,
      ),
    );
    return article;
  }

  const answer = document.createElement("div");
  answer.className = "agent-answer";
  renderAgentAnswer(answer, turn.answer ?? "No final answer recorded.");
  linkStructuredReferences(answer, turn.identifiers ?? [], responseLanguage.value);
  article.append(answer);
  const investigationSteps = renderInvestigationSteps(
    turn.investigation_steps ?? [],
    turn.response_language,
  );
  if (investigationSteps) article.append(investigationSteps);
  const nextSteps = renderNextSteps(turn.next_steps ?? [], turn.response_language);
  if (nextSteps) article.append(nextSteps);
  const references = renderIdentifierReferences(turn.identifiers ?? [], responseLanguage.value);
  if (references) article.append(references);
  const documents = renderDocuments(turn.documents ?? [], responseLanguage.value);
  if (documents) article.append(documents);
  article.append(renderTools(turn.tool_calls));

  const metadata = document.createElement("p");
  metadata.className = "turn-metadata";
  metadata.textContent = [turn.data_classification, turnStatusLabel(turn)]
    .filter(Boolean)
    .join(" / ");
  article.append(metadata);
  if (turn.approval_request) article.append(renderApproval(turn));
  return article;
}

function renderInvestigationSteps(steps, responseLanguage) {
  if (!steps.length) return null;

  const section = document.createElement("section");
  section.className = "investigation-summary";
  const title = document.createElement("h4");
  title.textContent =
    responseLanguage === "DE" ? "Untersuchungsübersicht" : "Investigation Summary";
  const scroll = document.createElement("div");
  scroll.className = "investigation-summary-scroll";
  const table = document.createElement("table");
  const header = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const label of investigationSummaryLabels(responseLanguage)) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    headerRow.append(cell);
  }
  header.append(headerRow);
  const body = document.createElement("tbody");
  for (const step of steps) {
    const row = document.createElement("tr");
    const number = document.createElement("td");
    number.textContent = String(step.step);
    const action = document.createElement("td");
    const actionName = document.createElement("code");
    actionName.textContent = step.action;
    action.append(actionName);
    const finding = document.createElement("td");
    finding.textContent = step.finding;
    row.append(number, action, finding);
    body.append(row);
  }
  table.append(header, body);
  scroll.append(table);
  section.append(title, scroll);
  return section;
}

function investigationSummaryLabels(responseLanguage) {
  return responseLanguage === "DE"
    ? ["Schritt", "Aktion", "Erkenntnisse / Hinweise"]
    : ["Step", "Action", "Findings / Notes"];
}

function renderNextSteps(nextSteps, responseLanguage) {
  if (!nextSteps.length) return null;

  const section = document.createElement("section");
  section.className = "next-step-section";
  const title = document.createElement("h4");
  title.textContent =
    responseLanguage === "DE"
      ? "Empfohlene Untersuchungsschritte"
      : "Recommended Investigation Actions";
  const list = document.createElement("ul");
  list.className = "next-step-list";
  const label = nextStepActionLabel(responseLanguage);
  for (const nextStep of nextSteps) {
    const item = document.createElement("li");
    const action = document.createElement("button");
    action.type = "button";
    action.className = "next-step-action";
    action.append(createIcon("arrow-right"));
    action.setAttribute("aria-label", label);
    action.title = label;
    action.addEventListener("click", () => useAsFollowUp(nextStep));
    const text = document.createElement("span");
    text.className = "next-step-text";
    text.textContent = nextStep;
    item.append(action, text);
    list.append(item);
  }
  section.append(title, list);
  return section;
}

function linkStructuredReferences(answer, identifiers, selectedLanguage) {
  const references = identifiers.map((reference) => ({ ...reference, kind: "identifier" })).filter((reference) => reference.value);
  if (!references.length) return;

  const matcher = new RegExp(
    references
      .map((reference) => escapeRegExp(reference.value))
      .sort((left, right) => right.length - left.length)
      .join("|"),
    "g",
  );
  const lookup = new Map(references.map((reference) => [reference.value, reference]));
  const walker = document.createTreeWalker(answer, window.NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.parentElement?.closest("a, button, .structured-reference")) textNodes.push(node);
  }
  for (const node of textNodes) {
    const source = node.textContent ?? "";
    matcher.lastIndex = 0;
    if (!matcher.test(source)) continue;
    matcher.lastIndex = 0;
    const fragment = document.createDocumentFragment();
    let start = 0;
    for (const match of source.matchAll(matcher)) {
      const value = match[0];
      const index = match.index ?? 0;
      fragment.append(document.createTextNode(source.slice(start, index)));
      const reference = lookup.get(value);
      if (reference) fragment.append(createReferenceControl(reference, selectedLanguage));
      else fragment.append(document.createTextNode(value));
      start = index + value.length;
    }
    fragment.append(document.createTextNode(source.slice(start)));
    node.replaceWith(fragment);
  }
}

function createReferenceControl(reference, selectedLanguage) {
  const control = document.createElement("span");
  control.className = `structured-reference ${reference.kind}-reference`;
  control.tabIndex = 0;
  control.setAttribute("role", "button");
  control.textContent = reference.value;
  control.title = "Reference actions";
  const openMenu = () => showReferenceMenu(control, reference, selectedLanguage);
  control.addEventListener("click", openMenu);
  control.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openMenu();
    }
  });
  return control;
}

function showReferenceMenu(anchor, reference, selectedLanguage) {
  document.querySelectorAll(".reference-popover").forEach((menu) => menu.remove());
  const menu = document.createElement("div");
  menu.className = "reference-popover";
  menu.setAttribute("role", "menu");
  for (const actionDefinition of identifierActions(reference, selectedLanguage)) {
    const action = document.createElement("button");
    action.type = "button";
    action.className = "reference-action";
    action.textContent = actionDefinition.label;
    action.disabled = isSubmitting;
    action.addEventListener("click", () => {
      if (actionDefinition.prompt) useAsFollowUp(actionDefinition.prompt);
      if (actionDefinition.copy) void copyIdentifier(reference.value);
      menu.remove();
    });
    menu.append(action);
  }
  anchor.after(menu);
}

function renderIdentifierReferences(identifiers, selectedLanguage) {
  if (!identifiers.length) return null;
  const section = document.createElement("section");
  section.className = "document-references";
  const title = document.createElement("h4");
  title.textContent = selectedLanguage === "DE" ? "Referenzen" : "References";
  const list = document.createElement("ul");
  for (const reference of identifiers) {
    const item = document.createElement("li");
    item.append(createReferenceControl({ ...reference, kind: "identifier" }, selectedLanguage));
    list.append(item);
  }
  section.append(title, list);
  return section;
}

function renderDocuments(documents, selectedLanguage) {
  const uniqueDocuments = [...new Map(documents.map((reference) => [reference.document_id, reference])).values()];
  if (!uniqueDocuments.length) return null;
  const section = document.createElement("section");
  section.className = "document-references";
  const title = document.createElement("h4");
  title.textContent = selectedLanguage === "DE" ? "Dokumente" : "Documents";
  const list = document.createElement("ul");
  for (const reference of uniqueDocuments) {
    const item = document.createElement("li");
    const documentTitle = document.createElement("span");
    documentTitle.className = "document-title";
    documentTitle.textContent = reference.title;
    const open = createDocumentAction(
      selectedLanguage === "DE" ? "Öffnen" : "Open",
      "open",
      () => openDocument(reference.document_id, userClearance.value),
    );
    const download = createDocumentAction(
      selectedLanguage === "DE" ? "Herunterladen" : "Download",
      "download",
      () => downloadDocument(reference.document_id, userClearance.value),
    );
    item.append(documentTitle, open, download);
    list.append(item);
  }
  section.append(title, list);
  return section;
}

function createDocumentAction(label, icon, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "reference-action document-action";
  button.title = label;
  button.append(createIcon(icon), document.createTextNode(label));
  button.disabled = isSubmitting;
  button.addEventListener("click", async () => {
    if (isSubmitting) return;
    try {
      await action();
    } catch (error) {
      showError(publicError(error, "The document could not be retrieved."));
    }
  });
  return button;
}

function identifierActions(reference, language) {
  const german = language === "DE";
  const actionsByType = {
    error_code: [
      [german ? "Untersuchen" : "Investigate", german ? `Untersuche ${reference.value} genauer.` : `Investigate ${reference.value} in more detail.`],
      [german ? "Dokumentation suchen" : "Search documentation", german ? `Suche technische Dokumentation zu ${reference.value}.` : `Search technical documentation for ${reference.value}.`],
    ],
    station: [
      [german ? "Station untersuchen" : "Investigate station", german ? `Untersuche Station ${reference.value} genauer.` : `Investigate station ${reference.value} in more detail.`],
      [german ? "Aktuellen Status prüfen" : "Check current status", german ? `Prüfe den aktuellen Status von Station ${reference.value}.` : `Check the current status of station ${reference.value}.`],
    ],
    product: [
      [german ? "Produkt untersuchen" : "Investigate product", german ? `Untersuche Produkt ${reference.value} genauer.` : `Investigate product ${reference.value} in more detail.`],
      [german ? "Produkthistorie anzeigen" : "Show product history", german ? `Zeige die Produkthistorie von ${reference.value}.` : `Show the product history for ${reference.value}.`],
    ],
    maintenance_ticket: [
      [german ? "Ticket prüfen" : "Inspect ticket", german ? `Prüfe Wartungsticket ${reference.value}.` : `Inspect maintenance ticket ${reference.value}.`],
    ],
  };
  const actions = actionsByType[reference.type] ?? [];
  return [
    ...actions.map(([label, prompt]) => ({ label, prompt })),
    { label: german ? "Kopieren" : "Copy", copy: true },
  ];
}

async function copyIdentifier(value) {
  if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function createTurnLabel(label) {
  const heading = document.createElement("h3");
  heading.className = "turn-label";
  heading.textContent = label;
  return heading;
}

function createIcon(name) {
  const paths = {
    "arrow-right": "M5 12h14m-6-6 6 6-6 6",
    open: "M14 4h6v6m0-6-9 9M18 13v6H4V5h6",
    download: "M12 3v12m-5-5 5 5 5-5M5 21h14",
  };
  const namespace = "http://www.w3.org/2000/svg";
  const icon = document.createElementNS(namespace, "svg");
  icon.setAttribute("aria-hidden", "true");
  icon.setAttribute("viewBox", "0 0 24 24");
  const path = document.createElementNS(namespace, "path");
  path.setAttribute("d", paths[name]);
  icon.append(path);
  return icon;
}

function createTurnError(errorCode, message, selectedLanguage) {
  const error = document.createElement("div");
  const providerLimited = isProviderLimitError(errorCode);
  error.className = providerLimited ? "turn-error turn-limit" : "turn-error";
  const title = document.createElement("strong");
  title.textContent = failureTitle(errorCode, selectedLanguage);
  const detail = document.createElement("p");
  detail.textContent = message;
  error.append(title, detail);
  return error;
}

function renderTools(calls) {
  const details = document.createElement("details");
  details.className = "tool-details";
  const summary = document.createElement("summary");
  summary.textContent = `${calls.length} executed tool call${calls.length === 1 ? "" : "s"}`;
  details.append(summary);
  if (calls.length) {
    const list = document.createElement("ol");
    list.className = "tool-calls";
    for (const call of calls) {
      const item = document.createElement("li");
      const name = document.createElement("span");
      name.className = "tool-name";
      name.textContent = call.tool;
      const argumentsView = document.createElement("pre");
      argumentsView.className = "tool-arguments";
      argumentsView.textContent = JSON.stringify(call.arguments, null, 2);
      item.append(name, argumentsView);
      list.append(item);
    }
    details.append(list);
  }
  return details;
}

function renderApproval(turn) {
  const approval = turn.approval_request;
  const section = document.createElement("section");
  section.className = "approval-card";
  const title = document.createElement("h3");
  title.textContent = "Approval required";
  const summary = document.createElement("p");
  summary.textContent = approval.summary;
  const approve = document.createElement("button");
  approve.type = "button";
  approve.textContent = "Approve";
  approve.addEventListener("click", () => decide(turn.run_id, "approve"));
  const reject = document.createElement("button");
  reject.type = "button";
  reject.className = "reject-button";
  reject.textContent = "Reject";
  reject.addEventListener("click", () => decide(turn.run_id, "reject"));
  section.append(title, summary, approve, reject);
  return section;
}

async function decide(runId, decision) {
  try {
    await resumeRun(runId, decision);
    await reloadInvestigation();
  } catch (error) {
    showError(publicError(error, "The decision could not be submitted."));
    setStatus("failed");
  }
}

function setSubmitting() {
  isSubmitting = true;
  composerMessage.disabled = true;
  composerButton.disabled = true;
  composerButton.setAttribute("aria-label", "Sending message");
  composerButton.title = "Sending message";
  newInvestigationButton.disabled = true;
}

function syncControls() {
  const hasInvestigation = Boolean(currentInvestigationId);
  composerMessage.disabled = isSubmitting;
  composerButton.disabled = isSubmitting;
  composerButton.setAttribute("aria-label", "Send message");
  composerButton.title = "Send message";
  newInvestigationButton.disabled = isSubmitting;
  exportPdfButton.disabled = !hasInvestigation;
  for (const action of history.querySelectorAll(".next-step-action, .reference-action")) {
    action.disabled = isSubmitting;
  }
}

function useAsFollowUp(nextStep) {
  if (isSubmitting) return;
  const existing = composerMessage.value;
  composerMessage.value = existing.trim()
    ? `${existing}${existing.endsWith("\n") ? "" : "\n"}${nextStep}`
    : nextStep;
  composerMessage.focus();
}

function nextStepActionLabel(responseLanguage) {
  return responseLanguage === "DE" ? "Als Folgefrage übernehmen" : "Use as follow-up";
}

function setStatus(status, selectedLanguage = responseLanguage.value) {
  runStatus.hidden = false;
  runStatus.dataset.status = status;
  runStatus.textContent = statusLabel(status, selectedLanguage);
}

function hideStatus() {
  runStatus.hidden = true;
  runStatus.dataset.status = "idle";
  runStatus.textContent = "";
}

function statusLabel(status, selectedLanguage = responseLanguage.value) {
  if (status === "running") return "Investigating";
  if (status === "limit_reached") {
    return selectedLanguage === "DE" ? "Limit erreicht" : "Limit reached";
  }
  return status
    .split("_")
    .map((part) => `${part[0].toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function turnStatusLabel(turn) {
  return isProviderLimitError(turn.error?.code)
    ? statusLabel("limit_reached", turn.response_language)
    : statusLabel(turn.status, turn.response_language);
}

function isProviderLimitError(errorCode) {
  return ["llm_rate_limit", "llm_quota_exceeded", "llm_provider_unavailable"].includes(errorCode);
}

function failureTitle(errorCode, selectedLanguage) {
  const german = selectedLanguage === "DE";
  if (errorCode === "llm_rate_limit" || errorCode === "llm_quota_exceeded") {
    return german ? "LLM-Limit erreicht" : "LLM limit reached";
  }
  if (errorCode === "llm_provider_unavailable") {
    return german ? "LLM-Anbieter nicht verfügbar" : "LLM provider unavailable";
  }
  return german ? "Untersuchungsschritt fehlgeschlagen." : "Investigation step failed.";
}

function scrollHistoryToLatest() {
  history.scrollTop = history.scrollHeight;
}

function publicError(error, fallback) {
  return error instanceof ApiClientError ? error.message : fallback;
}

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = false;
}

function hideError() {
  errorMessage.hidden = true;
  errorMessage.textContent = "";
}
