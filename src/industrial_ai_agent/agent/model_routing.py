from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from industrial_ai_agent.agent.llm import ModelProfile
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    ExecutionZone,
    ModelEgressPolicy,
)


class TaskRole(StrEnum):
    TOOL_SELECTION = "TOOL_SELECTION"
    TROUBLESHOOTING = "TROUBLESHOOTING"
    GENERAL_REASONING = "GENERAL_REASONING"


class LLMCapability(StrEnum):
    TEXT = "TEXT"
    TOOL_CALLING = "TOOL_CALLING"


class QualityClass(StrEnum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"

    @property
    def rank(self) -> int:
        return {
            QualityClass.STANDARD: 0,
            QualityClass.HIGH: 1,
        }[self]


class CostClass(StrEnum):
    LOW = "LOW"
    HIGH = "HIGH"

    @property
    def rank(self) -> int:
        return {
            CostClass.LOW: 0,
            CostClass.HIGH: 1,
        }[self]


class CostPreference(StrEnum):
    MINIMIZE_COST = "MINIMIZE_COST"
    BALANCED = "BALANCED"
    PREFER_QUALITY = "PREFER_QUALITY"

    def sort_key(self, profile: ModelProfileMetadata) -> tuple[int, int, str]:
        if self is CostPreference.MINIMIZE_COST:
            return (
                profile.cost_class.rank,
                profile.quality_class.rank,
                profile.profile.name,
            )
        if self is CostPreference.BALANCED:
            return (
                profile.cost_class.rank,
                -profile.quality_class.rank,
                profile.profile.name,
            )
        return (
            -profile.quality_class.rank,
            profile.cost_class.rank,
            profile.profile.name,
        )


@dataclass(frozen=True, slots=True)
class TaskRequirements:
    task_role: TaskRole
    required_capabilities: frozenset[LLMCapability]
    minimum_quality: QualityClass
    cost_preference: CostPreference
    data_classification: DataClassification

    def __post_init__(self) -> None:
        if not isinstance(self.task_role, TaskRole):
            raise TypeError("Unknown task role")
        if not isinstance(self.required_capabilities, frozenset) or any(
            not isinstance(capability, LLMCapability)
            for capability in self.required_capabilities
        ):
            raise TypeError("Required capabilities must be known LLM capabilities")
        if not self.required_capabilities:
            raise ValueError("At least one LLM capability is required")
        if not isinstance(self.minimum_quality, QualityClass):
            raise TypeError("Unknown minimum quality class")
        if not isinstance(self.cost_preference, CostPreference):
            raise TypeError("Unknown cost preference")
        if not isinstance(self.data_classification, DataClassification):
            raise TypeError("Unknown data classification")


@dataclass(frozen=True, slots=True)
class ModelProfileMetadata:
    profile: ModelProfile
    capabilities: frozenset[LLMCapability]
    quality_class: QualityClass
    cost_class: CostClass
    execution_zone: ExecutionZone

    def __post_init__(self) -> None:
        if not isinstance(self.profile, ModelProfile):
            raise TypeError("Model profile metadata requires a ModelProfile")
        if not isinstance(self.capabilities, frozenset) or any(
            not isinstance(capability, LLMCapability)
            for capability in self.capabilities
        ):
            raise TypeError("Model profile capabilities must be known LLM capabilities")
        if not self.capabilities:
            raise ValueError("Model profile requires at least one capability")
        if not isinstance(self.quality_class, QualityClass):
            raise TypeError("Unknown model quality class")
        if not isinstance(self.cost_class, CostClass):
            raise TypeError("Unknown model cost class")
        if not isinstance(self.execution_zone, ExecutionZone):
            raise TypeError("Unknown model execution zone")


class NoEligibleModelError(RuntimeError):
    def __init__(self, requirements: TaskRequirements) -> None:
        self.task_role = requirements.task_role
        self.data_classification = requirements.data_classification
        super().__init__(
            f"No eligible model profile for task role: {requirements.task_role.value}"
        )


class DeterministicModelRouter:
    def __init__(self, egress_policy: ModelEgressPolicy | None = None) -> None:
        self._egress_policy = egress_policy or ModelEgressPolicy()

    def eligible_profiles(
        self,
        requirements: TaskRequirements,
        profiles: tuple[ModelProfileMetadata, ...],
    ) -> tuple[ModelProfileMetadata, ...]:
        security_eligible = (
            profile
            for profile in profiles
            if self._egress_policy.is_allowed(
                requirements.data_classification,
                profile.execution_zone,
            )
        )
        capability_eligible = (
            profile
            for profile in security_eligible
            if requirements.required_capabilities <= profile.capabilities
        )
        quality_eligible = (
            profile
            for profile in capability_eligible
            if profile.quality_class.rank >= requirements.minimum_quality.rank
        )
        return tuple(sorted(quality_eligible, key=lambda item: item.profile.name))

    def route(
        self,
        requirements: TaskRequirements,
        profiles: tuple[ModelProfileMetadata, ...],
    ) -> ModelProfile:
        eligible_profiles = self.eligible_profiles(requirements, profiles)
        if not eligible_profiles:
            raise NoEligibleModelError(requirements)
        return min(eligible_profiles, key=requirements.cost_preference.sort_key).profile
