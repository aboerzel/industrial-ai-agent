"""Composition root for the confidential MCP-backed troubleshooting application service."""

import os
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from mcp.client.stdio import StdioServerParameters

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import ModelProfile
from industrial_ai_agent.agent.model_egress import (
    EgressCheckedLLMClient,
    ModelEgressPolicy,
)
from industrial_ai_agent.agent.model_routing import (
    DeterministicModelRouter,
)
from industrial_ai_agent.agent.run_classification_policy import ResolvedRunPolicy
from industrial_ai_agent.agent.troubleshooting_run_service import (
    McpBackedTroubleshootingAgent,
    RoutedTroubleshootingAgentFactory,
    TroubleshootingRunService,
)
from industrial_ai_agent.infrastructure.factory_mcp_client import (
    McpTransport,
    StreamableHttpServerParameters,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    LLMConfiguration,
    load_llm_configuration,
    local_only_mode_enabled,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    DEFAULT_ALLOWED_FACTORY_TOOLS,
    DEFAULT_ALLOWED_KNOWLEDGE_TOOLS,
    McpLangChainToolProvider,
    McpServerConfiguration,
)
from industrial_ai_agent.infrastructure.observed_llm_client import ObservedLLMClient
from industrial_ai_agent.infrastructure.persistence.langgraph_checkpointer import (
    PostgreSqlCheckpointerFactory,
)
from industrial_ai_agent.infrastructure.telemetry import Telemetry

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_CONFIGURATION_PATH = Path(
    os.getenv(
        "MODEL_CONFIGURATION_PATH",
        str(PROJECT_ROOT / "config" / "model_profiles.toml"),
    )
)
DEFAULT_FACTORY_MCP_URL = "http://127.0.0.1:8001/mcp"
DEFAULT_KNOWLEDGE_MCP_URL = "http://127.0.0.1:8002/mcp"
MCP_INDUSTRIAL_AGENT_TOKEN_ENV = "MCP_INDUSTRIAL_AGENT_TOKEN"


class _LangGraphTroubleshootingAgentFactory(RoutedTroubleshootingAgentFactory):
    """Create a short-lived, security-checked agent around shared configuration."""

    def __init__(
        self,
        *,
        configuration: LLMConfiguration,
        mcp_tool_provider_factory,
        egress_policy: ModelEgressPolicy,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._configuration = configuration
        self._mcp_tool_provider_factory = mcp_tool_provider_factory
        self._egress_policy = egress_policy
        self._telemetry = telemetry

    def open_agent(
        self,
        *,
        profile: ModelProfile,
        run_policy: ResolvedRunPolicy,
        checkpointer: object | None = None,
    ) -> AbstractContextManager[McpBackedTroubleshootingAgent]:
        return self._open_agent(
            profile=profile, run_policy=run_policy, checkpointer=checkpointer
        )

    @contextmanager
    def _open_agent(
        self,
        *,
        profile: ModelProfile,
        run_policy: ResolvedRunPolicy,
        checkpointer: object | None,
    ) -> Iterator[McpBackedTroubleshootingAgent]:
        with OpenAICompatibleLLMClient(self._configuration) as adapter:
            checked_client = EgressCheckedLLMClient(
                adapter,
                self._configuration,
                run_policy.data_classification,
                policy=self._egress_policy,
            )
            llm_client = (
                ObservedLLMClient(
                    checked_client,
                    configuration=self._configuration,
                    data_classification=run_policy.data_classification,
                    telemetry=self._telemetry,
                )
                if self._telemetry is not None
                else checked_client
            )
            yield LangGraphTroubleshootingAgent(
                LLMClientChatModel(llm_client, profile),
                mcp_tool_provider=self._mcp_tool_provider_factory(run_policy),
                checkpointer=checkpointer,
                run_classification=run_policy.data_classification,
            )


def create_default_troubleshooting_run_service(
    *,
    model_configuration_path: Path = DEFAULT_MODEL_CONFIGURATION_PATH,
    mcp_transport: str | None = None,
    factory_mcp_url: str | None = None,
    knowledge_mcp_url: str | None = None,
    runtime_database_url: str | None = None,
    telemetry: Telemetry | None = None,
    internal_diagnostic_scope_validator=None,
) -> TroubleshootingRunService:
    """Compose the local demo service without exposing deployment details to FastAPI."""
    configuration = load_llm_configuration(model_configuration_path)
    policy = ModelEgressPolicy()
    transport = mcp_transport or os.getenv("AGENT_MCP_TRANSPORT", "http")
    resolved_factory_mcp_url = factory_mcp_url or os.getenv(
        "FACTORY_MCP_URL", DEFAULT_FACTORY_MCP_URL
    )
    resolved_knowledge_mcp_url = knowledge_mcp_url or os.getenv(
        "KNOWLEDGE_MCP_URL", DEFAULT_KNOWLEDGE_MCP_URL
    )

    def mcp_tool_provider_factory(
        policy: ResolvedRunPolicy,
    ) -> McpLangChainToolProvider:
        return McpLangChainToolProvider(
            _mcp_server_configurations(
                mcp_transport=transport,
                factory_mcp_url=resolved_factory_mcp_url,
                knowledge_mcp_url=resolved_knowledge_mcp_url,
                factory_database_url=runtime_database_url,
                run_policy=policy,
            ),
            telemetry=telemetry,
            data_classification=policy.data_classification.name,
            run_profile=policy.run_profile.value,
        )

    return TroubleshootingRunService(
        router=DeterministicModelRouter(policy),
        profiles=configuration.get_routing_profiles(
            local_only=local_only_mode_enabled()
        ),
        agent_factory=_LangGraphTroubleshootingAgentFactory(
            configuration=configuration,
            mcp_tool_provider_factory=mcp_tool_provider_factory,
            egress_policy=policy,
            telemetry=telemetry,
        ),
        internal_diagnostic_scope_validator=internal_diagnostic_scope_validator,
        checkpointer_factory=(
            PostgreSqlCheckpointerFactory(runtime_database_url)
            if runtime_database_url
            else None
        ),
    )


def _mcp_server_configurations(
    *,
    mcp_transport: str,
    factory_mcp_url: str,
    knowledge_mcp_url: str,
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
