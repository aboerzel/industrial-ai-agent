import { ApiClientError, createRun, getRun, resumeRun } from "./api.js";

const form = document.querySelector("#investigation-form");
const messageInput = document.querySelector("#message");
const userClearance = document.querySelector("#user-clearance");
const runButton = document.querySelector("#run-button");
const runStatus = document.querySelector("#run-status");
const runId = document.querySelector("#run-id");
const runClassification = document.querySelector("#run-classification");
const answer = document.querySelector("#answer");
const toolCalls = document.querySelector("#tool-calls");
const errorMessage = document.querySelector("#error-message");
const approvalCard = document.querySelector("#approval-card");
const approvalAction = document.querySelector("#approval-action");
const approvalSummary = document.querySelector("#approval-summary");
const approvalArguments = document.querySelector("#approval-arguments");
const approveButton = document.querySelector("#approve-button");
const rejectButton = document.querySelector("#reject-button");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message) {
    showError("Enter a troubleshooting request before starting a run.");
    messageInput.focus();
    return;
  }

  setRunning();
  try {
    const result = await createRun(message, userClearance.value);
    renderRun(result);
  } catch (error) {
    showError(
      error instanceof ApiClientError
        ? error.message
        : "The investigation could not be started.",
    );
    setStatus("failed", "Failed");
  } finally {
    runButton.disabled = false;
  }
});

export async function reloadRun(runIdentifier) {
  const result = await getRun(runIdentifier);
  renderRun(result);
}

function setRunning() {
  runButton.disabled = true;
  hideError();
  setStatus("running", "Running");
  runId.textContent = "Assigned by the API after completion";
  runClassification.textContent = "Resolved by the server";
  answer.textContent = "The agent is investigating through the configured services.";
  answer.classList.add("empty-state");
  toolCalls.replaceChildren(createEmptyToolCall("Tool execution is in progress."));
}

function renderRun(result) {
  hideError();
  runId.textContent = result.run_id;
  runClassification.textContent = result.data_classification;
  setStatus(result.status, statusLabel(result.status));
  answer.textContent = result.answer ?? "The run finished without a final answer.";
  answer.classList.toggle("empty-state", result.answer === null);
  renderToolCalls(result.tool_calls);
  renderApproval(result);
}

function renderApproval(result) {
  const approval = result.approval_request;
  approvalCard.hidden = result.status !== "waiting_for_approval" || !approval;
  if (!approvalCard.hidden) {
    approvalAction.textContent = approval.action;
    approvalSummary.textContent = approval.summary;
    approvalArguments.textContent = JSON.stringify(approval.arguments, null, 2);
    approveButton.disabled = false;
    rejectButton.disabled = false;
    approveButton.onclick = () => decide(result.run_id, "approve");
    rejectButton.onclick = () => decide(result.run_id, "reject");
  }
}

async function decide(runIdentifier, decision) {
  approveButton.disabled = true;
  rejectButton.disabled = true;
  try {
    renderRun(await resumeRun(runIdentifier, decision));
  } catch (error) {
    showError(error instanceof ApiClientError ? error.message : "The decision could not be submitted.");
  }
}

function renderToolCalls(calls) {
  if (calls.length === 0) {
    toolCalls.replaceChildren(createEmptyToolCall("No tool calls were required."));
    return;
  }

  const items = calls.map((call) => {
    const item = document.createElement("li");
    item.className = "tool-call";

    const toolName = document.createElement("span");
    toolName.className = "tool-name";
    toolName.textContent = call.tool;

    const argumentsView = document.createElement("pre");
    argumentsView.className = "tool-arguments";
    argumentsView.textContent = JSON.stringify(call.arguments, null, 2);

    item.append(toolName, argumentsView);
    return item;
  });
  toolCalls.replaceChildren(...items);
}

function createEmptyToolCall(message) {
  const item = document.createElement("li");
  item.textContent = message;
  return item;
}

function setStatus(status, label) {
  runStatus.dataset.status = status;
  runStatus.textContent = label;
}

function statusLabel(status) {
  return status
    .split("_")
    .map((part) => `${part[0].toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = false;
}

function hideError() {
  errorMessage.hidden = true;
  errorMessage.textContent = "";
}
