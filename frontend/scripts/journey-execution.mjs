import { MissingEvidence, recordAssertion } from "./journey-assertions.mjs";

export function classifyJourneyFailure(error, terminal = {}, step = {}) {
  if (/Protected identifier leaked|Denied investigation leaked|Protected document leaked/.test(error.message)) return "SECURITY_DEFECT";
  if (error.result_category) return error.result_category;
  if (error.status === 401) return "HARNESS_ERROR";
  if (["llm_provider_unavailable", "llm_rate_limit", "llm_quota_exceeded"].includes(terminal.error_code)) return "BLOCKED_BY_PROVIDER";
  if (terminal.error_code === "agent_execution_timeout") return "INFRASTRUCTURE_ERROR";
  if (/Required (?:investigation ID|matching persisted run)|UI investigation reference/.test(error.message)) return "PRODUCT_DEFECT";
  if (error.name === "AssertionError" && ["pdf", "document", "reload", "switch-user", "new-chat"].includes(step.kind)) return "PRODUCT_DEFECT";
  if (error instanceof MissingEvidence || error.name === "AssertionError") return "MODEL_VARIANCE";
  return "HARNESS_ERROR";
}

export async function evaluateJourneyStep(result, step, index, execute, httpGuard) {
  result.current_assertion_id = `step-${index + 1}:${step.kind}`;
  result.last_terminal = null;
  const assertion = result.assertions.find(item => item.id === result.current_assertion_id);
  try {
    await execute();
    httpGuard.assertSuccessful();
  } catch (error) {
    const category = classifyJourneyFailure(error, result.last_terminal ?? {}, step);
    if (assertion.status === "NOT_RUN") {
      recordAssertion(result, assertion.id, error instanceof MissingEvidence ? "BLOCKED" : "FAIL", error.message, !(error instanceof MissingEvidence));
    }
    if (assertion.status === "PASS") {
      assertion.status = "FAIL";
      assertion.note = error.message;
      const observation = result.steps.find(item => item.assertion_id === assertion.id);
      if (observation) observation.test_result = "FAIL";
    }
    assertion.result_category = category;
    result.step_failures ??= [];
    result.step_failures.push({ assertion_id: assertion.id, result_category: category, http_status: error.status ?? null,
      http_classification: error.http_classification ?? null, error_code: error.code ?? result.last_terminal?.error_code ?? null,
      terminal: result.last_terminal ? { ...result.last_terminal } : null,
      message: String(error.message).replace(/(Bearer|Basic)\s+[^\s]+/gi, "$1 [REDACTED]").slice(0, 500) });
    // The failed assertion retains the error; do not poison later independent checks.
    httpGuard.takeFailures?.();
  } finally {
    assertion.evaluated = true;
    if (!assertion.result_category) assertion.result_category = assertion.status === "PASS" ? "PASS" : "MODEL_VARIANCE";
  }
}

export function journeyResultCategory(result) {
  const categories = [result.fatal_category, ...(result.inventory_smoke ?? []).map(item => item.result_category), ...(result.step_failures ?? []).map(item => item.result_category),
    ...result.assertions.filter(item => item.requirement === "REQUIRED").map(item => item.result_category)];
  return ["SECURITY_DEFECT", "HARNESS_ERROR", "INFRASTRUCTURE_ERROR", "PRODUCT_DEFECT", "BLOCKED_BY_PROVIDER", "MODEL_VARIANCE"].find(category => categories.includes(category)) ?? "PASS";
}
