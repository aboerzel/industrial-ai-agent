import {
  ApiClientError,
  createRun,
  downloadInvestigationPdf,
  getInvestigation,
  resumeRun,
} from "./api.js";
import { renderAgentAnswer } from "./markdown.js";

const composerForm = document.querySelector("#composer-form");
const composerMessage = document.querySelector("#composer-message");
const composerButton = document.querySelector("#composer-button");
const userClearance = document.querySelector("#user-clearance");
const newInvestigationButton = document.querySelector("#new-investigation-button");
const history = document.querySelector("#conversation-history");
const runStatus = document.querySelector("#run-status");
const investigationRuns = document.querySelector("#investigation-runs");
const investigationTools = document.querySelector("#investigation-tools");
const investigationMetadata = document.querySelector("#investigation-metadata");
const investigationContext = document.querySelector("#investigation-context");
const resultTitle = document.querySelector("#result-title");
const exportPdfButton = document.querySelector("#export-pdf-button");
const errorMessage = document.querySelector("#error-message");

let currentInvestigationId = null;
let isSubmitting = false;
let pendingAgentTurn = null;

composerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitRequest(composerMessage.value.trim());
});

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

renderEmptyInvestigation();

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
      currentInvestigationId,
    );
    currentInvestigationId = result.investigation_id;
    composerMessage.value = "";
    await reloadInvestigation();
  } catch (error) {
    renderPendingFailure(publicError(error, "The agent run could not be completed."));
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
  resultTitle.textContent = "No active investigation";
  investigationContext.textContent =
    "Ask about a production issue, station, product, maintenance ticket, or available documentation.";
  investigationMetadata.hidden = true;
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
  resultTitle.textContent = "Investigation";
  investigationContext.textContent = investigationContextFor(investigation.turns);
  investigationRuns.textContent = String(investigation.run_count);
  investigationTools.textContent = String(investigation.tool_call_count);
  investigationMetadata.hidden = false;
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

function renderPendingConversation(message, { replace }) {
  hideError();
  resultTitle.textContent = "Investigation";
  if (replace) {
    investigationContext.textContent = "Starting a new investigation.";
    investigationMetadata.hidden = true;
    history.replaceChildren();
  }
  history.classList.remove("empty-state");
  const turn = { request: message, status: "running" };
  pendingAgentTurn = renderAgentTurn(turn);
  history.append(renderUserTurn(turn), pendingAgentTurn);
  setStatus("running");
  scrollHistoryToLatest();
}

function renderPendingFailure(message) {
  if (pendingAgentTurn) {
    pendingAgentTurn.classList.remove("is-pending");
    pendingAgentTurn.classList.add("is-error");
    pendingAgentTurn.replaceChildren(
      createTurnLabel("Agent"),
      createTurnError(message),
    );
  } else {
    showError(message);
  }
  pendingAgentTurn = null;
  setStatus("failed");
  scrollHistoryToLatest();
}

function createEmptyState() {
  const emptyState = document.createElement("div");
  emptyState.className = "empty-investigation";
  const title = document.createElement("h3");
  title.textContent = "Start a new investigation";
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
    article.classList.add("is-error");
    article.append(createTurnError("The agent run could not be completed."));
    return article;
  }

  const answer = document.createElement("div");
  answer.className = "agent-answer";
  renderAgentAnswer(answer, turn.answer ?? "No final answer recorded.");
  article.append(answer, renderTools(turn.tool_calls));

  const metadata = document.createElement("p");
  metadata.className = "turn-metadata";
  metadata.textContent = [turn.data_classification, statusLabel(turn.status)]
    .filter(Boolean)
    .join(" / ");
  article.append(metadata);
  if (turn.approval_request) article.append(renderApproval(turn));
  return article;
}

function createTurnLabel(label) {
  const heading = document.createElement("h3");
  heading.className = "turn-label";
  heading.textContent = label;
  return heading;
}

function createTurnError(message) {
  const error = document.createElement("div");
  error.className = "turn-error";
  const title = document.createElement("strong");
  title.textContent = "Investigation step failed.";
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
  composerButton.textContent = "Investigating...";
  newInvestigationButton.disabled = true;
}

function syncControls() {
  const hasInvestigation = Boolean(currentInvestigationId);
  composerMessage.disabled = isSubmitting;
  composerButton.disabled = isSubmitting;
  composerButton.textContent = hasInvestigation ? "Send" : "Start Investigation";
  newInvestigationButton.disabled = isSubmitting;
  exportPdfButton.disabled = !hasInvestigation;
}

function setStatus(status) {
  runStatus.hidden = false;
  runStatus.dataset.status = status;
  runStatus.textContent = statusLabel(status);
}

function hideStatus() {
  runStatus.hidden = true;
  runStatus.dataset.status = "idle";
  runStatus.textContent = "";
}

function statusLabel(status) {
  if (status === "running") return "Investigating";
  return status
    .split("_")
    .map((part) => `${part[0].toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function investigationContextFor(turns) {
  const identifiers = [
    ...new Set(
      (turns[0]?.request.match(/\b(?:P\d+|S\d{2,3})\b/g) ?? []).map(
        (identifier) => identifier.toUpperCase(),
      ),
    ),
  ];
  return identifiers.length ? identifiers.join(" / ") : "Active investigation";
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
