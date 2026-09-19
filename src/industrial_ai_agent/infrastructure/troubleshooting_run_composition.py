"""Composition root for the confidential MCP-backed troubleshooting application service."""

import os
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from mcp.client.stdio import StdioServerParameters

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    MCP_TROUBLESHOOTING_SYSTEM_MESSAGE,
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import LLMReasoningEffort, ModelId
from industrial_ai_agent.agent.model_egress import (
    EgressCheckedLLMClient,
    ModelExecutionAuthorizer,
)
from industrial_ai_agent.agent.model_selection import (
    AGENT_CONSUMER,
    AGENT_REQUIREMENTS,
    ModelCapability,
    ModelResolutionService,
)
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunProfile,
    ResolvedRunPolicy,
)
from industrial_ai_agent.agent.troubleshooting_run_service import (
    McpBackedTroubleshootingAgent,
    RoutedTroubleshootingAgentFactory,
    TroubleshootingRunService,
)
from industrial_ai_agent.domain.security import DEMO_RUNTIME_SECURITY_CONTEXT
from industrial_ai_agent.infrastructure.factory_mcp_client import (
    McpTransport,
    StreamableHttpServerParameters,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    ModelCatalogConfiguration,
    load_model_catalog,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    DEFAULT_ALLOWED_FACTORY_TOOLS,
    DEFAULT_ALLOWED_HARDWARE_TOOLS,
    DEFAULT_ALLOWED_KNOWLEDGE_TOOLS,
    McpLangChainToolProvider,
    McpServerConfiguration,
)
from industrial_ai_agent.infrastructure.model_decision_observer import (
    TelemetryModelDecisionObserver,
)
from industrial_ai_agent.infrastructure.observed_llm_client import ObservedLLMClient
from industrial_ai_agent.infrastructure.persistence.langgraph_checkpointer import (
    PostgreSqlCheckpointerFactory,
)
from industrial_ai_agent.infrastructure.persistence.model_assignments import (
    PostgreSqlModelAssignmentRepository,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.infrastructure.telemetry import Telemetry

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_CATALOG_PATH = Path(
    os.getenv(
        "MODEL_CATALOG_PATH",
        str(PROJECT_ROOT / "config" / "model_catalog.toml"),
    )
)
DEFAULT_FACTORY_MCP_URL = "http://127.0.0.1:8001/mcp"
DEFAULT_KNOWLEDGE_MCP_URL = "http://127.0.0.1:8002/mcp"
DEFAULT_HARDWARE_MCP_URL = "http://127.0.0.1:8006/mcp"
MCP_INDUSTRIAL_AGENT_TOKEN_ENV = "MCP_INDUSTRIAL_AGENT_TOKEN"


class _LangGraphTroubleshootingAgentFactory(RoutedTroubleshootingAgentFactory):
    """Create a short-lived, security-checked agent around shared configuration."""

    def __init__(
        self,
        *,
        configuration: ModelCatalogConfiguration,
        mcp_tool_provider_factory,
        authorizer: ModelExecutionAuthorizer,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._configuration = configuration
        self._mcp_tool_provider_factory = mcp_tool_provider_factory
        self._authorizer = authorizer
        self._telemetry = telemetry

    def open_agent(
        self,
        *,
        model_id: ModelId,
        run_policy: ResolvedRunPolicy,
        checkpointer: object | None = None,
    ) -> AbstractContextManager[McpBackedTroubleshootingAgent]:
        return self._open_agent(
            model_id=model_id, run_policy=run_policy, checkpointer=checkpointer
        )

    @contextmanager
    def _open_agent(
        self,
        *,
        model_id: ModelId,
        run_policy: ResolvedRunPolicy,
        checkpointer: object | None,
    ) -> Iterator[McpBackedTroubleshootingAgent]:
        with OpenAICompatibleLLMClient(self._configuration) as adapter:
            checked_client = EgressCheckedLLMClient(
                adapter,
                self._configuration,
                run_policy.data_classification,
                authorizer=self._authorizer,
            )
            llm_client = (
                ObservedLLMClient(
                    checked_client,
                    catalog=self._configuration,
                    data_classification=run_policy.data_classification,
                    telemetry=self._telemetry,
                    consumer_id=run_policy.model_consumer_id,
                    required_capabilities=AGENT_REQUIREMENTS,
                )
                if self._telemetry is not None
                else checked_client
            )
            yield LangGraphTroubleshootingAgent(
                LLMClientChatModel(
                    llm_client,
                    model_id,
                    supports_structured_output=(
                        ModelCapability.STRUCTURED_OUTPUT
                        in self._configuration.get_model(model_id.value).capabilities
                    ),
                    reasoning_effort=_restricted_ollama_reasoning_effort(
                        configuration=self._configuration,
                        model_id=model_id,
                        run_policy=run_policy,
                    ),
                ),
                mcp_tool_provider=self._mcp_tool_provider_factory(run_policy),
                checkpointer=checkpointer,
                run_classification=run_policy.data_classification,
                system_message=_system_message_for(run_policy),
                normalize_structured_final_output=(
                    run_policy.run_profile is not AgentRunProfile.RESTRICTED_INFORMATION
                ),
                requires_verified_recovery=(
                    run_policy.run_profile is AgentRunProfile.CONFIDENTIAL_RECOVERY
                ),
            )


def create_default_troubleshooting_run_service(
    *,
    model_catalog_path: Path = DEFAULT_MODEL_CATALOG_PATH,
    mcp_transport: str | None = None,
    factory_mcp_url: str | None = None,
    knowledge_mcp_url: str | None = None,
    hardware_mcp_url: str | None = None,
    runtime_database_url: str | None = None,
    telemetry: Telemetry | None = None,
    internal_diagnostic_scope_validator=None,
    model_assignment_repository=None,
) -> TroubleshootingRunService:
    """Compose the local demo service without exposing deployment details to FastAPI."""
    configuration = load_model_catalog(model_catalog_path)
    authorizer = ModelExecutionAuthorizer()
    if model_assignment_repository is None and not runtime_database_url:
        raise RuntimeError("runtime_database_url is required for model assignments")
    assignments = model_assignment_repository or PostgreSqlModelAssignmentRepository(
        PostgreSqlSessionFactory(runtime_database_url or ""),
        DEMO_RUNTIME_SECURITY_CONTEXT,
    )
    model_resolver = ModelResolutionService(
        catalog=configuration,
        assignments=assignments,
        authorizer=authorizer,
        consumer_requirements={AGENT_CONSUMER: AGENT_REQUIREMENTS},
        observer=(
            TelemetryModelDecisionObserver(telemetry) if telemetry is not None else None
        ),
    )
    transport = mcp_transport or os.getenv("AGENT_MCP_TRANSPORT", "http")
    resolved_factory_mcp_url = factory_mcp_url or os.getenv(
        "FACTORY_MCP_URL", DEFAULT_FACTORY_MCP_URL
    )
    resolved_knowledge_mcp_url = knowledge_mcp_url or os.getenv(
        "KNOWLEDGE_MCP_URL", DEFAULT_KNOWLEDGE_MCP_URL
    )
    resolved_hardware_mcp_url = hardware_mcp_url or os.getenv(
        "HARDWARE_MCP_URL", DEFAULT_HARDWARE_MCP_URL
    )

    def mcp_tool_provider_factory(
        policy: ResolvedRunPolicy,
    ) -> McpLangChainToolProvider:
        return McpLangChainToolProvider(
            _mcp_server_configurations(
                mcp_transport=transport,
                factory_mcp_url=resolved_factory_mcp_url,
                knowledge_mcp_url=resolved_knowledge_mcp_url,
                hardware_mcp_url=resolved_hardware_mcp_url,
                factory_database_url=runtime_database_url,
                run_policy=policy,
            ),
            telemetry=telemetry,
            data_classification=policy.data_classification.name,
            run_profile=policy.run_profile.value,
        )

    return TroubleshootingRunService(
        model_resolver=model_resolver,
        agent_factory=_LangGraphTroubleshootingAgentFactory(
            configuration=configuration,
            mcp_tool_provider_factory=mcp_tool_provider_factory,
            authorizer=authorizer,
            telemetry=telemetry,
        ),
        internal_diagnostic_scope_validator=internal_diagnostic_scope_validator,
        checkpointer_factory=(
            PostgreSqlCheckpointerFactory(runtime_database_url)
            if runtime_database_url
            else None
        ),
    )


def _restricted_ollama_reasoning_effort(
    *,
    configuration: ModelCatalogConfiguration,
    model_id: ModelId,
    run_policy: ResolvedRunPolicy,
) -> LLMReasoningEffort | None:
    """Disable unbounded local thinking for restricted agent tool workflows."""
    profile_config = configuration.get_model_config(model_id.value)
    if (
        run_policy.data_classification.name == "RESTRICTED"
        and profile_config.provider.casefold() == "ollama"
    ):
        return LLMReasoningEffort.NONE
    return None


_RESTRICTED_INFORMATION_SYSTEM_MESSAGE = (
    "You are an industrial operations assistant. Use one provided read-only tool when "
    "its evidence is necessary. Base the concise final answer in the requested response "
    "language only on authorized tool results. Do not invent industrial data, access "
    "scope, or follow-up actions. "
    "Return narrative Markdown only."
)


def _system_message_for(run_policy: ResolvedRunPolicy) -> str:
    if run_policy.run_profile is AgentRunProfile.RESTRICTED_INFORMATION:
        return _RESTRICTED_INFORMATION_SYSTEM_MESSAGE
    return MCP_TROUBLESHOOTING_SYSTEM_MESSAGE


def _mcp_server_configurations(
    *,
    mcp_transport: str,
    factory_mcp_url: str,
    knowledge_mcp_url: str,
    hardware_mcp_url: str,
    factory_database_url: str | None,
    run_policy: ResolvedRunPolicy,
) -> tuple[McpServerConfiguration, ...]:
    if mcp_transport == "http":
        factory_transport: McpTransport = StreamableHttpServerParameters(
            url=factory_mcp_url,
            bearer_token=_required_mcp_bearer_token(run_policy.mcp_client_identity),
        )
        knowledge_transport: McpTransport = StreamableHttpServerParameters(
            url=knowledge_mcp_url,
            bearer_token=_required_mcp_bearer_token(run_policy.mcp_client_identity),
        )
        hardware_transport: McpTransport = StreamableHttpServerParameters(
            url=hardware_mcp_url,
            bearer_token=_required_mcp_bearer_token(run_policy.mcp_client_identity),
        )
    elif mcp_transport == "stdio":
        if run_policy.mcp_client_identity != "industrial-agent":
            raise RuntimeError("INTERNAL diagnostics require authenticated HTTP MCP")
        factory_transport = StdioServerParameters(
            command=sys.executable,
            args=["-m", "industrial_ai_agent.infrastructure.factory_mcp_server"],
            env=(
                {"FACTORY_DATABASE_URL": factory_database_url}
                if factory_database_url
                else None
            ),
        )
        knowledge_transport = StdioServerParameters(
            command=sys.executable,
            args=["-m", "industrial_ai_agent.infrastructure.knowledge_mcp_server"],
        )
    else:
        raise ValueError("AGENT_MCP_TRANSPORT must be either 'http' or 'stdio'")

    candidates = (
        (
            "factory",
            factory_transport,
            frozenset(
                tool
                for tool in DEFAULT_ALLOWED_FACTORY_TOOLS
                if tool in run_policy.allowed_tool_names
            ),
        ),
        (
            "knowledge",
            knowledge_transport,
            frozenset(
                tool
                for tool in DEFAULT_ALLOWED_KNOWLEDGE_TOOLS
                if tool in run_policy.allowed_tool_names
            ),
        ),
    )
    if mcp_transport == "http":
        candidates += (
            (
                "hardware",
                hardware_transport,
                frozenset(
                    tool
                    for tool in DEFAULT_ALLOWED_HARDWARE_TOOLS
                    if tool in run_policy.allowed_tool_names
                ),
            ),
        )
    # Do not establish an MCP session for a server that has no capability in this
    # server-resolved run scope. This preserves the policy boundary before discovery.
    return tuple(
        McpServerConfiguration(
            server_id=server_id,
            transport=transport,
            allowed_tool_names=allowed_tool_names,
        )
        for server_id, transport, allowed_tool_names in candidates
        if allowed_tool_names
    )


def _required_mcp_bearer_token(client_identity: str) -> str:
    token_name = (
        "MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN"
        if client_identity == "industrial-agent-public"
        else MCP_INDUSTRIAL_AGENT_TOKEN_ENV
        if client_identity == "industrial-agent"
        else "MCP_INDUSTRIAL_AGENT_INTERNAL_TOKEN"
        if client_identity == "industrial-agent-internal"
        else "MCP_INDUSTRIAL_AGENT_RESTRICTED_TOKEN"
        if client_identity == "industrial-agent-restricted"
        else None
    )
    if token_name is None:
        raise RuntimeError("Unknown server-selected MCP client identity")
    token = os.getenv(token_name)
    if token is None or not token.strip():
        raise RuntimeError(f"{token_name} is required for HTTP MCP")
    return token
