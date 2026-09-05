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
    TaskRequirements,
)
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
from industrial_ai_agent.infrastructure.persistence.langgraph_checkpointer import (
    PostgreSqlCheckpointerFactory,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_CONFIGURATION_PATH = PROJECT_ROOT / "config" / "model_profiles.toml"
DEFAULT_FACTORY_MCP_URL = "http://127.0.0.1:8001/mcp"
DEFAULT_KNOWLEDGE_MCP_URL = "http://127.0.0.1:8002/mcp"


class _LangGraphTroubleshootingAgentFactory(RoutedTroubleshootingAgentFactory):
    """Create a short-lived, security-checked agent around shared configuration."""

    def __init__(
        self,
        *,
        configuration: LLMConfiguration,
        mcp_tool_provider: McpLangChainToolProvider,
        egress_policy: ModelEgressPolicy,
    ) -> None:
        self._configuration = configuration
        self._mcp_tool_provider = mcp_tool_provider
        self._egress_policy = egress_policy

    def open_agent(
        self,
        *,
        profile: ModelProfile,
        requirements: TaskRequirements,
        checkpointer: object | None = None,
    ) -> AbstractContextManager[McpBackedTroubleshootingAgent]:
        return self._open_agent(
            profile=profile, requirements=requirements, checkpointer=checkpointer
        )

    @contextmanager
    def _open_agent(
        self,
        *,
        profile: ModelProfile,
        requirements: TaskRequirements,
        checkpointer: object | None,
    ) -> Iterator[McpBackedTroubleshootingAgent]:
        with OpenAICompatibleLLMClient(self._configuration) as adapter:
            checked_client = EgressCheckedLLMClient(
                adapter,
                self._configuration,
                requirements.data_classification,
                policy=self._egress_policy,
            )
            yield LangGraphTroubleshootingAgent(
                LLMClientChatModel(checked_client, profile),
                mcp_tool_provider=self._mcp_tool_provider,
                checkpointer=checkpointer,
                run_classification=requirements.data_classification,
            )


def create_default_troubleshooting_run_service(
    *,
    model_configuration_path: Path = DEFAULT_MODEL_CONFIGURATION_PATH,
    mcp_transport: str | None = None,
    factory_mcp_url: str | None = None,
    knowledge_mcp_url: str | None = None,
    runtime_database_url: str | None = None,
) -> TroubleshootingRunService:
    """Compose the local demo service without exposing deployment details to FastAPI."""
    configuration = load_llm_configuration(model_configuration_path)
    policy = ModelEgressPolicy()
    provider = McpLangChainToolProvider(
        _mcp_server_configurations(
            mcp_transport=mcp_transport or os.getenv("AGENT_MCP_TRANSPORT", "http"),
            factory_mcp_url=factory_mcp_url
            or os.getenv("FACTORY_MCP_URL", DEFAULT_FACTORY_MCP_URL),
            knowledge_mcp_url=knowledge_mcp_url
            or os.getenv("KNOWLEDGE_MCP_URL", DEFAULT_KNOWLEDGE_MCP_URL),
            factory_database_url=runtime_database_url,
        )
    )
    return TroubleshootingRunService(
        router=DeterministicModelRouter(policy),
        profiles=configuration.get_routing_profiles(),
        agent_factory=_LangGraphTroubleshootingAgentFactory(
            configuration=configuration,
            mcp_tool_provider=provider,
            egress_policy=policy,
        ),
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
) -> tuple[McpServerConfiguration, ...]:
    if mcp_transport == "http":
        factory_transport: McpTransport = StreamableHttpServerParameters(
            url=factory_mcp_url
        )
        knowledge_transport: McpTransport = StreamableHttpServerParameters(
            url=knowledge_mcp_url
        )
    elif mcp_transport == "stdio":
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

    return (
        McpServerConfiguration(
            server_id="factory",
            transport=factory_transport,
            allowed_tool_names=DEFAULT_ALLOWED_FACTORY_TOOLS,
        ),
        McpServerConfiguration(
            server_id="knowledge",
            transport=knowledge_transport,
            allowed_tool_names=DEFAULT_ALLOWED_KNOWLEDGE_TOOLS,
        ),
    )
