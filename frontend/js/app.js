import {
  ApiClientError,
  createRun,
  downloadInvestigationPdf,
  getInvestigation,
  resumeRun,
} from "./api.js";
import { renderAgentAnswer } from "./markdown.js";

const form = document.querySelector("#investigation-form");
const messageInput = document.querySelector("#message");
const userClearance = document.querySelector("#user-clearance");
const runButton = document.querySelector("#run-button");
const followUpForm = document.querySelector("#follow-up-form");
const followUpMessage = document.querySelector("#follow-up-message");
const followUpButton = document.querySelector("#follow-up-button");
const history = document.querySelector("#conversation-history");
const runStatus = document.querySelector("#run-status");
const investigationId = document.querySelector("#investigation-id");
const investigationSummary = document.querySelector("#investigation-summary");
const resultTitle = document.querySelector("#result-title");
const exportPdfButton = document.querySelector("#export-pdf-button");
const errorMessage = document.querySelector("#error-message");

let currentInvestigationId = null;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitNewInvestigation(messageInput.value.trim());
});

followUpForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (currentInvestigationId) await submitFollowUp(followUpMessage.value.trim());
});

exportPdfButton.addEventListener("click", () => {
  if (currentInvestigationId) downloadInvestigationPdf(currentInvestigationId, userClearance.value);
});

async function submitNewInvestigation(message) {
  if (!message) return showError("Enter a troubleshooting request before starting an investigation.");
  setSubmitting(runButton, "Starting investigation...");
  try {
    const result = await createRun(message, userClearance.value);
    currentInvestigationId = result.investigation_id;
    await reloadInvestigation();
  } catch (error) {
    showError(publicError(error, "The investigation could not be started."));
    setStatus("failed", "Failed");
  } finally {
    runButton.disabled = false;
    runButton.textContent = "New Investigation";
  }
}

async function submitFollowUp(message) {
  if (!message) return showError("Enter a follow-up question before continuing.");
  setSubmitting(followUpButton, "Continuing investigation...");
  try {
    await createRun(message, userClearance.value, currentInvestigationId);
    followUpMessage.value = "";
    await reloadInvestigation();
  } catch (error) {
    showError(publicError(error, "The follow-up could not be started."));
    setStatus("failed", "Failed");
  } finally {
    followUpButton.disabled = false;
    followUpButton.textContent = "Continue Investigation";
  }
}

async function reloadInvestigation() {
  if (!currentInvestigationId) return;
  renderInvestigation(await getInvestigation(currentInvestigationId, userClearance.value));
}

function renderInvestigation(investigation) {
  hideError();
  currentInvestigationId = investigation.investigation_id;
  resultTitle.textContent = "Investigation";
  investigationId.textContent = investigation.investigation_id;
  investigationSummary.textContent = `Runs: ${investigation.run_count} / Tools: ${investigation.tool_call_count}`;
  setStatus(investigation.status, statusLabel(investigation.status));
  exportPdfButton.disabled = false;
  followUpButton.disabled = false;
  history.classList.remove("empty-state");
  history.replaceChildren(...investigation.turns.map(renderTurn));
}

function renderTurn(turn) {
  const article = document.createElement("article");
  article.className = "conversation-turn";
  const heading = document.createElement("p");
  heading.className = "turn-label";
  heading.textContent = `Turn ${turn.sequence} / ${statusLabel(turn.status)}`;
  const userLabel = document.createElement("h3");
  userLabel.textContent = "You";
  const userText = document.createElement("p");
  userText.className = "user-request";
  userText.textContent = turn.request;
  const agentLabel = document.createElement("h3");
  agentLabel.textContent = "Agent";
  const agentAnswer = document.createElement("div");
  agentAnswer.className = "agent-answer";
  renderAgentAnswer(agentAnswer, turn.answer ?? "No final answer recorded.");
  const metadata = document.createElement("p");
  metadata.className = "turn-metadata";
  metadata.textContent = `${turn.data_classification} / ${turn.response_language}`;
  article.append(heading, userLabel, userText, agentLabel, agentAnswer, renderTools(turn.tool_calls), metadata);
  if (turn.approval_request) article.append(renderApproval(turn));
  return article;
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
    setStatus("failed", "Failed");
  }
}

function setSubmitting(button, label) {
  hideError();
  button.disabled = true;
  button.textContent = label;
  setStatus("running", "Running");
}

function setStatus(status, label) {
  runStatus.dataset.status = status;
  runStatus.textContent = label;
}

function statusLabel(status) {
  return status.split("_").map((part) => `${part[0].toUpperCase()}${part.slice(1)}`).join(" ");
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
