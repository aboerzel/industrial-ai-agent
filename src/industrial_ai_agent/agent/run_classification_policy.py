"""Server-owned classification policy for bounded agent run profiles."""

from dataclasses import dataclass
from enum import StrEnum

from industrial_ai_agent.agent.model_routing import (
    CostPreference,
    LLMCapability,
    QualityClass,
    TaskRequirements,
    TaskRole,
)
from industrial_ai_agent.domain.security import DataClassification


class AgentRunProfile(StrEnum):
    """Fixed server-side execution contracts; clients never submit these values."""

    INTERNAL_DIAGNOSTIC = "INTERNAL_DIAGNOSTIC"
    CONFIDENTIAL_TROUBLESHOOTING = "CONFIDENTIAL_TROUBLESHOOTING"


@dataclass(frozen=True, slots=True)
class InternalDiagnosticTarget:
    """Validated bounded resource references for an INTERNAL diagnostic."""

    product_id: str
    station_id: str


INTERNAL_DIAGNOSTIC_TOOLS = frozenset(
    {"get_product_history", "get_machine_status", "search_documentation"}
)
CONFIDENTIAL_TROUBLESHOOTING_TOOLS = frozenset(
    {
        "get_product_history",
        "get_machine_status",
        "search_documentation",
        "create_maintenance_ticket",
    }
)


@dataclass(frozen=True, slots=True)
class ResolvedRunPolicy:
    """Immutable execution scope resolved solely by deterministic server policy."""

    run_profile: AgentRunProfile
    data_classification: DataClassification
    mcp_clearance_ceiling: DataClassification
    task_requirements: TaskRequirements
    allowed_tool_names: frozenset[str]
    mcp_client_identity: str

    def __post_init__(self) -> None:
        if self.data_classification is not self.mcp_clearance_ceiling:
            raise ValueError("Run classification must match its immutable RLS ceiling")
        if self.task_requirements.data_classification is not self.data_classification:
            raise ValueError("Task requirements must match the resolved classification")
        if not self.allowed_tool_names:
            raise ValueError("Resolved run policy must authorize at least one tool")
        if not self.mcp_client_identity.strip():
            raise ValueError("Resolved run policy requires an MCP client identity")


class AgentRunClassificationPolicy:
    """Map known server-side profiles to non-downgradable execution scopes."""

    def resolve(self, profile: AgentRunProfile) -> ResolvedRunPolicy:
        if profile is AgentRunProfile.INTERNAL_DIAGNOSTIC:
            return ResolvedRunPolicy(
                run_profile=profile,
                data_classification=DataClassification.INTERNAL,
                mcp_clearance_ceiling=DataClassification.INTERNAL,
                task_requirements=_requirements(DataClassification.INTERNAL),
                allowed_tool_names=INTERNAL_DIAGNOSTIC_TOOLS,
                mcp_client_identity="industrial-agent-internal",
            )
        if profile is AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING:
            return ResolvedRunPolicy(
                run_profile=profile,
                data_classification=DataClassification.CONFIDENTIAL,
                mcp_clearance_ceiling=DataClassification.CONFIDENTIAL,
                task_requirements=_requirements(DataClassification.CONFIDENTIAL),
                allowed_tool_names=CONFIDENTIAL_TROUBLESHOOTING_TOOLS,
                mcp_client_identity="industrial-agent",
            )
        raise ValueError("Unknown agent run profile")

    def resolve_persisted(
        self,
        *,
        profile: AgentRunProfile,
        data_classification: DataClassification,
    ) -> ResolvedRunPolicy:
        resolved = self.resolve(profile)
        if resolved.data_classification is not data_classification:
            raise ValueError("Persisted run classification does not match its profile")
        return resolved


def _requirements(classification: DataClassification) -> TaskRequirements:
    return TaskRequirements(
        task_role=TaskRole.TROUBLESHOOTING,
        required_capabilities=frozenset(
            {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
        ),
        minimum_quality=QualityClass.HIGH,
        cost_preference=CostPreference.PREFER_QUALITY,
        data_classification=classification,
    )
