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
            "model.selection_mode": decision.selection_mode.value,
            "model.display_name": "Unconfigured model"
            if model is None
            else model.display_name,
        }
        if decision.run_id is not None:
            attributes["run.id"] = str(decision.run_id)
        if decision.error_code is not None:
            attributes["error.code"] = decision.error_code
        if decision.call_type is not None:
            attributes["model.call_type"] = decision.call_type.value
        if decision.missing_capabilities:
            attributes["model.missing_capabilities"] = ",".join(
                sorted(capability.value for capability in decision.missing_capabilities)
            )
        if decision.incompatible_capability_combination:
            attributes["model.incompatible_capability_combination"] = ",".join(
                sorted(
                    capability.value
                    for capability in decision.incompatible_capability_combination
                )
            )
        if decision.duration_ms is not None:
            attributes["operation.duration_ms"] = decision.duration_ms
        if decision.selection_policy is not None:
            attributes["model.selection_policy"] = decision.selection_policy.value
        if decision.candidates:
            attributes.update(
                {
                    "model.selection_candidate_count": len(decision.candidates),
                    "model.selection_capability_rejected_count": sum(
                        item.runtime_available and not item.capability_allowed
                        for item in decision.candidates
                    ),
                    "model.selection_security_rejected_count": sum(
                        item.runtime_available and item.egress_allowed is False
                        for item in decision.candidates
                    ),
                    "model.selection_runtime_unavailable_count": sum(
                        not item.runtime_available for item in decision.candidates
                    ),
                }
            )
        if model is not None:
            attributes.update(
                {
                    "model.id": model.model_id.value,
                    "model.provider": model.provider,
                    "execution.zone": model.execution_zone.value,
                    "model.available_capabilities": ",".join(
                        sorted(capability.value for capability in model.capabilities)
                    ),
                }
            )
        with self._telemetry.span("model.decision", attributes):
            for candidate in decision.candidates:
                candidate_attributes: dict[str, object] = {
                    "model.consumer_id": decision.consumer_id.value,
                    "data.classification": decision.effective_data_classification.name,
                    "model.id": candidate.model.model_id.value,
                    "model.display_name": candidate.model.display_name,
                    "model.provider": candidate.model.provider,
                    "execution.zone": candidate.model.execution_zone.value,
                    "model.quality_class": candidate.model.quality_class.value,
                    "model.cost_class": candidate.model.cost_class.value,
                    "model.runtime_availability_decision": _decision_label(
                        candidate.runtime_available
                    ),
                    "model.available_capabilities": ",".join(
                        sorted(item.value for item in candidate.model.capabilities)
                    ),
                    "model.capability_decision": _decision_label(
                        candidate.capability_allowed
                    ),
                    "model.egress_decision": _decision_label(candidate.egress_allowed),
                    "model.selection_mode": decision.selection_mode.value,
                }
                if decision.selection_policy is not None:
                    candidate_attributes["model.selection_policy"] = (
                        decision.selection_policy.value
                    )
                if candidate.exclusion_reason is not None:
                    candidate_attributes["model.candidate_exclusion_reason"] = (
                        candidate.exclusion_reason
                    )
                if candidate.call_type is not None:
                    candidate_attributes["model.call_type"] = candidate.call_type.value
                if candidate.missing_capabilities:
                    candidate_attributes["model.missing_capabilities"] = ",".join(
                        sorted(
                            capability.value
                            for capability in candidate.missing_capabilities
                        )
                    )
                if candidate.incompatible_capability_combination:
                    candidate_attributes[
                        "model.incompatible_capability_combination"
                    ] = ",".join(
                        sorted(
                            capability.value
                            for capability in candidate.incompatible_capability_combination
                        )
                    )
                with self._telemetry.span(
                    "model.selection.candidate", candidate_attributes
                ):
                    pass
        self._telemetry.record_model_decision(attributes=attributes)


def _decision_label(value: bool | None) -> str:
    if value is None:
        return "NOT_EVALUATED"
    return "ALLOW" if value else "DENY"
