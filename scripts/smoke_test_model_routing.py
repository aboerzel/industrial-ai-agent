from pathlib import Path

from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    ExecutionZone,
    ModelEgressPolicy,
)
from industrial_ai_agent.agent.model_routing import (
    CostPreference,
    DeterministicModelRouter,
    LLMCapability,
    NoEligibleModelError,
    QualityClass,
    TaskRequirements,
    TaskRole,
)
from industrial_ai_agent.infrastructure.llm.configuration import load_llm_configuration

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CAPABILITIES = frozenset({LLMCapability.TEXT, LLMCapability.TOOL_CALLING})


def main() -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    router = DeterministicModelRouter(ModelEgressPolicy())
    profiles = configuration.get_routing_profiles()

    public_tool_selection = TaskRequirements(
        task_role=TaskRole.TOOL_SELECTION,
        required_capabilities=REQUIRED_CAPABILITIES,
        minimum_quality=QualityClass.STANDARD,
        cost_preference=CostPreference.MINIMIZE_COST,
        data_classification=DataClassification.PUBLIC,
    )
    selected_public = router.route(public_tool_selection, profiles)
    if selected_public.name != "local_fast":
        raise RuntimeError("Unexpected PUBLIC tool-selection routing result")
    print(f"scenario=public_tool_selection selected={selected_public.name}")

    confidential_troubleshooting = TaskRequirements(
        task_role=TaskRole.TROUBLESHOOTING,
        required_capabilities=REQUIRED_CAPABILITIES,
        minimum_quality=QualityClass.HIGH,
        cost_preference=CostPreference.PREFER_QUALITY,
        data_classification=DataClassification.CONFIDENTIAL,
    )
    selected_confidential = router.route(confidential_troubleshooting, profiles)
    if (
        configuration.get_execution_zone(selected_confidential.name)
        is not ExecutionZone.LOCAL
    ):
        raise RuntimeError("CONFIDENTIAL task selected a non-local profile")
    print(
        f"scenario=confidential_troubleshooting selected={selected_confidential.name}"
    )

    public_fast_only = tuple(
        profile for profile in profiles if profile.profile.name == "public_fast"
    )
    try:
        router.route(confidential_troubleshooting, public_fast_only)
    except NoEligibleModelError:
        print("scenario=confidential_public_only result=NO_ELIGIBLE_MODEL")
    else:
        raise RuntimeError("CONFIDENTIAL task selected public_fast")


if __name__ == "__main__":
    main()
