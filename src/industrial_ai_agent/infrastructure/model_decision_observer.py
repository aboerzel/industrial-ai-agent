"""Metadata-only OpenTelemetry projection of model resolution decisions."""

from industrial_ai_agent.agent.model_selection import ModelDecision
from industrial_ai_agent.infrastructure.telemetry import Telemetry


class TelemetryModelDecisionObserver:
    def __init__(self, telemetry: Telemetry) -> None:
        self._telemetry = telemetry

    def record(self, decision: ModelDecision) -> None:
        model = decision.model
        attributes: dict[str, object] = {
            "model.consumer_id": decision.consumer_id.value,
            "data.classification": decision.effective_data_classification.name,
            "model.required_capabilities": ",".join(
                sorted(
                    capability.value for capability in decision.required_capabilities
                )
            ),
            "model.capability_decision": _decision_label(decision.capability_allowed),
            "model.egress_decision": _decision_label(decision.egress_allowed),
            "model.decision_outcome": decision.outcome.value,
        }
        if decision.run_id is not None:
            attributes["run.id"] = str(decision.run_id)
        if decision.error_code is not None:
            attributes["error.code"] = decision.error_code
        if decision.duration_ms is not None:
            attributes["operation.duration_ms"] = decision.duration_ms
        if model is not None:
            attributes.update(
                {
                    "model.id": model.model_id.value,
                    "model.provider": model.provider,
                    "execution.zone": model.execution_zone.value,
                }
            )
        with self._telemetry.span("model.decision", attributes):
            pass


def _decision_label(value: bool | None) -> str:
    if value is None:
        return "NOT_EVALUATED"
    return "ALLOW" if value else "DENY"
