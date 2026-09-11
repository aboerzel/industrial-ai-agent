from dataclasses import dataclass, field
from pathlib import Path

import pytest

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMClient,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    MessageRole,
    ModelProfile,
)
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
    ExecutionZone,
    ModelEgressPolicy,
)
from industrial_ai_agent.agent.model_routing import (
    CostClass,
    CostPreference,
    DeterministicModelRouter,
    LLMCapability,
    ModelProfileMetadata,
    NoEligibleModelError,
    QualityClass,
    TaskRequirements,
    TaskRole,
)
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    AgentRunProfile,
    resolve_demo_run_profile,
)
from industrial_ai_agent.infrastructure.llm.configuration import load_llm_configuration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALL_CAPABILITIES = frozenset({LLMCapability.TEXT, LLMCapability.TOOL_CALLING})


def make_profile(
    name: str,
    *,
    capabilities: frozenset[LLMCapability] = ALL_CAPABILITIES,
    quality: QualityClass = QualityClass.STANDARD,
    cost: CostClass = CostClass.LOW,
    zone: ExecutionZone = ExecutionZone.LOCAL,
    max_data_classification: DataClassification = DataClassification.RESTRICTED,
) -> ModelProfileMetadata:
    return ModelProfileMetadata(
        profile=ModelProfile(name),
        capabilities=capabilities,
        quality_class=quality,
        cost_class=cost,
        execution_zone=zone,
        max_data_classification=max_data_classification,
    )


def requirements(
    *,
    classification: DataClassification = DataClassification.PUBLIC,
    minimum_quality: QualityClass = QualityClass.STANDARD,
    cost_preference: CostPreference = CostPreference.BALANCED,
    required_capabilities: frozenset[LLMCapability] = ALL_CAPABILITIES,
    task_role: TaskRole = TaskRole.TOOL_SELECTION,
) -> TaskRequirements:
    return TaskRequirements(
        task_role=task_role,
        required_capabilities=required_capabilities,
        minimum_quality=minimum_quality,
        cost_preference=cost_preference,
        data_classification=classification,
    )


def profile_names(profiles: tuple[ModelProfileMetadata, ...]) -> tuple[str, ...]:
    return tuple(item.profile.name for item in profiles)


def test_public_task_sees_local_and_public_cloud_profiles() -> None:
    candidates = (
        make_profile("local"),
        make_profile("public", zone=ExecutionZone.PUBLIC_CLOUD),
    )

    eligible = DeterministicModelRouter().eligible_profiles(requirements(), candidates)

    assert profile_names(eligible) == ("local", "public")


def test_confidential_task_sees_public_profile_with_sufficient_maximum() -> None:
    candidates = (
        make_profile("local_quality", quality=QualityClass.HIGH),
        make_profile(
            "public_fast",
            quality=QualityClass.HIGH,
            zone=ExecutionZone.PUBLIC_CLOUD,
        ),
    )

    eligible = DeterministicModelRouter().eligible_profiles(
        requirements(classification=DataClassification.CONFIDENTIAL),
        candidates,
    )

    assert profile_names(eligible) == ("local_quality", "public_fast")


@pytest.mark.parametrize(
    "classification", (DataClassification.PUBLIC, DataClassification.CONFIDENTIAL)
)
def test_full_demo_routes_eligible_public_classifications_to_public_fast(
    classification: DataClassification,
) -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )

    selected = DeterministicModelRouter().route(
        requirements(classification=classification, minimum_quality=QualityClass.HIGH),
        configuration.get_routing_profiles(),
    )

    assert selected == ModelProfile("public_fast")


def test_s04_position_reference_recovery_requires_nvidia_quality() -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    profile = resolve_demo_run_profile(
        "Untersuche den Positionsreferenzfehler an Station S04 und stelle die Station wieder her."
    )
    task = AgentRunClassificationPolicy().resolve(profile).task_requirements

    selected = DeterministicModelRouter().route(
        task, configuration.get_routing_profiles()
    )

    assert profile is AgentRunProfile.CONFIDENTIAL_RECOVERY
    assert task.required_model_profile == ModelProfile("nvidia_quality")
    assert selected == ModelProfile("nvidia_quality")


def test_s04_position_reference_recovery_fails_closed_without_nvidia_profile() -> None:
    task = (
        AgentRunClassificationPolicy()
        .resolve(AgentRunProfile.CONFIDENTIAL_RECOVERY)
        .task_requirements
    )

    with pytest.raises(NoEligibleModelError):
        DeterministicModelRouter().route(
            task,
            (
                make_profile(
                    "public_fast",
                    quality=QualityClass.HIGH,
                    zone=ExecutionZone.PUBLIC_CLOUD,
                    max_data_classification=DataClassification.CONFIDENTIAL,
                ),
            ),
        )


def test_s04_position_reference_recovery_does_not_fall_back_when_nvidia_key_is_absent() -> (
    None
):
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    task = (
        AgentRunClassificationPolicy()
        .resolve(AgentRunProfile.CONFIDENTIAL_RECOVERY)
        .task_requirements
    )
    available_profiles = configuration.get_available_routing_profiles(
        environment={"GROQ_API_KEY": "configured"}
    )

    with pytest.raises(NoEligibleModelError):
        DeterministicModelRouter().route(task, available_profiles)


def test_s04_position_reference_recovery_keeps_final_egress_check() -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    task = (
        AgentRunClassificationPolicy()
        .resolve(AgentRunProfile.CONFIDENTIAL_RECOVERY)
        .task_requirements
    )
    selected = DeterministicModelRouter().route(
        task, configuration.get_routing_profiles()
    )
    adapter = RecordingLLMClient()
    client = EgressCheckedLLMClient(
        adapter,
        configuration,
        task.data_classification,
    )
    request = LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="synthetic request"),)
    )

    client.chat(selected, request)

    assert selected == ModelProfile("nvidia_quality")
    assert adapter.calls == [(selected, request)]


def test_local_only_configuration_excludes_public_profiles_and_routes_confidential_locally() -> (
    None
):
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    profiles = configuration.get_routing_profiles(local_only=True)

    selected = DeterministicModelRouter().route(
        requirements(
            classification=DataClassification.CONFIDENTIAL,
            minimum_quality=QualityClass.HIGH,
        ),
        profiles,
    )

    assert profile_names(profiles) == ("local_fast", "local_quality")
    assert selected == ModelProfile("local_quality")


@pytest.mark.parametrize(
    "message",
    ("Why did the last batch fail?", "  Export customer production plans.  "),
)
def test_unknown_free_text_never_has_an_eligible_public_cloud_route(
    message: str,
) -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    profile = resolve_demo_run_profile(message)
    requirements = AgentRunClassificationPolicy().resolve(profile).task_requirements

    eligible = DeterministicModelRouter().eligible_profiles(
        requirements, configuration.get_routing_profiles()
    )

    assert profile is AgentRunProfile.RESTRICTED_TROUBLESHOOTING
    assert all(item.execution_zone is ExecutionZone.LOCAL for item in eligible)


def test_restricted_task_excludes_public_profile_below_its_maximum() -> None:
    candidates = (
        make_profile("local_quality", quality=QualityClass.HIGH),
        make_profile(
            "public_fast",
            quality=QualityClass.HIGH,
            zone=ExecutionZone.PUBLIC_CLOUD,
            max_data_classification=DataClassification.CONFIDENTIAL,
        ),
    )

    eligible = DeterministicModelRouter().eligible_profiles(
        requirements(classification=DataClassification.RESTRICTED), candidates
    )

    assert profile_names(eligible) == ("local_quality",)


def test_restricted_information_routes_to_local_fast_without_public_egress() -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    requirements = (
        AgentRunClassificationPolicy()
        .resolve(AgentRunProfile.RESTRICTED_INFORMATION)
        .task_requirements
    )

    selected = DeterministicModelRouter().route(
        requirements, configuration.get_routing_profiles()
    )

    assert selected == ModelProfile("local_fast")


def test_public_deployment_is_preferred_after_security_eligibility() -> None:
    candidates = (
        make_profile("local_expensive", cost=CostClass.HIGH),
        make_profile("public_cheap", zone=ExecutionZone.PUBLIC_CLOUD),
    )

    selected = DeterministicModelRouter().route(
        requirements(
            classification=DataClassification.CONFIDENTIAL,
            cost_preference=CostPreference.MINIMIZE_COST,
        ),
        candidates,
    )

    assert selected == ModelProfile("public_cheap")


def test_profile_without_required_tool_calling_is_excluded() -> None:
    candidates = (
        make_profile("text-only", capabilities=frozenset({LLMCapability.TEXT})),
        make_profile("tool-capable"),
    )

    eligible = DeterministicModelRouter().eligible_profiles(requirements(), candidates)

    assert profile_names(eligible) == ("tool-capable",)


def test_profile_with_all_required_capabilities_remains_eligible() -> None:
    candidate = make_profile("complete")

    eligible = DeterministicModelRouter().eligible_profiles(
        requirements(),
        (candidate,),
    )

    assert eligible == (candidate,)


def test_standard_quality_accepts_standard_and_high_profiles() -> None:
    candidates = (
        make_profile("standard"),
        make_profile("high", quality=QualityClass.HIGH),
    )

    eligible = DeterministicModelRouter().eligible_profiles(
        requirements(minimum_quality=QualityClass.STANDARD),
        candidates,
    )

    assert profile_names(eligible) == ("high", "standard")


def test_high_quality_excludes_standard_profiles() -> None:
    candidates = (
        make_profile("standard"),
        make_profile("high", quality=QualityClass.HIGH),
    )

    eligible = DeterministicModelRouter().eligible_profiles(
        requirements(minimum_quality=QualityClass.HIGH),
        candidates,
    )

    assert profile_names(eligible) == ("high",)


def test_minimize_cost_selects_lowest_cost_then_smallest_quality() -> None:
    candidates = (
        make_profile("low-high", quality=QualityClass.HIGH),
        make_profile("low-standard"),
        make_profile("high-standard", cost=CostClass.HIGH),
    )

    selected = DeterministicModelRouter().route(
        requirements(cost_preference=CostPreference.MINIMIZE_COST),
        candidates,
    )

    assert selected == ModelProfile("low-standard")


def test_prefer_quality_selects_highest_quality_then_lowest_cost() -> None:
    candidates = (
        make_profile("standard-low"),
        make_profile("high-high", quality=QualityClass.HIGH, cost=CostClass.HIGH),
        make_profile("high-low", quality=QualityClass.HIGH),
    )

    selected = DeterministicModelRouter().route(
        requirements(cost_preference=CostPreference.PREFER_QUALITY),
        candidates,
    )

    assert selected == ModelProfile("high-low")


def test_balanced_selects_lowest_cost_then_highest_quality() -> None:
    candidates = (
        make_profile("low-standard"),
        make_profile("low-high", quality=QualityClass.HIGH),
        make_profile("high-high", quality=QualityClass.HIGH, cost=CostClass.HIGH),
    )

    selected = DeterministicModelRouter().route(
        requirements(cost_preference=CostPreference.BALANCED),
        candidates,
    )

    assert selected == ModelProfile("low-high")


def test_profile_id_breaks_complete_tie_independently_of_input_order() -> None:
    alpha = make_profile("alpha")
    beta = make_profile("beta")
    router = DeterministicModelRouter()
    task = requirements()

    assert router.route(task, (beta, alpha)) == ModelProfile("alpha")
    assert router.route(task, (alpha, beta)) == ModelProfile("alpha")


def test_no_eligible_profile_raises_structured_error() -> None:
    task = requirements(
        classification=DataClassification.RESTRICTED,
        task_role=TaskRole.TROUBLESHOOTING,
    )

    with pytest.raises(NoEligibleModelError) as captured_error:
        DeterministicModelRouter().route(
            task,
            (
                make_profile(
                    "public_fast",
                    zone=ExecutionZone.PUBLIC_CLOUD,
                    max_data_classification=DataClassification.CONFIDENTIAL,
                ),
            ),
        )

    assert captured_error.value.task_role is TaskRole.TROUBLESHOOTING
    assert captured_error.value.data_classification is DataClassification.RESTRICTED


def test_invalid_core_metadata_fails_closed() -> None:
    with pytest.raises(TypeError, match="Unknown model cost class"):
        make_profile("invalid", cost="unknown")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "classification",
    list(DataClassification),
)
def test_selected_profile_is_always_egress_eligible(
    classification: DataClassification,
) -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    policy = ModelEgressPolicy()
    task = requirements(classification=classification)

    selected = DeterministicModelRouter(policy).route(
        task,
        configuration.get_routing_profiles(),
    )

    assert policy.is_allowed(
        classification,
        configuration.get_execution_zone(selected.name),
        configuration.get_max_data_classification(selected.name),
    )


@dataclass
class RecordingLLMClient(LLMClient):
    calls: list[tuple[ModelProfile, LLMRequest]] = field(default_factory=list)

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        self.calls.append((profile, request))
        return LLMResponse(text="ok", finish_reason=FinishReason.STOP)


def test_routed_profile_still_passes_final_egress_check() -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    policy = ModelEgressPolicy()
    task = requirements(classification=DataClassification.PUBLIC)
    selected = DeterministicModelRouter(policy).route(
        task,
        configuration.get_routing_profiles(),
    )
    adapter = RecordingLLMClient()
    client = EgressCheckedLLMClient(
        adapter,
        configuration,
        task.data_classification,
        policy=policy,
    )
    request = LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="public synthetic data"),)
    )

    response = client.chat(selected, request)

    assert response.text == "ok"
    assert adapter.calls == [(selected, request)]
