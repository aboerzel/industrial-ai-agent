import argparse
import asyncio
import os
import sys
from pathlib import Path

from mcp.client.stdio import StdioServerParameters

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import LLMReasoningEffort, ModelId
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
    ModelExecutionAuthorizer,
)
from industrial_ai_agent.agent.model_selection import AGENT_REQUIREMENTS
from industrial_ai_agent.domain.investigation_evidence import InvestigationType
from industrial_ai_agent.infrastructure.factory_mcp_client import (
    FactoryMcpTransport,
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
from industrial_ai_agent.infrastructure.local_environment import load_local_environment
from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    DEFAULT_ALLOWED_FACTORY_TOOLS,
    DEFAULT_ALLOWED_KNOWLEDGE_TOOLS,
    McpLangChainToolProvider,
    McpServerConfiguration,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "model_catalog.toml"
PUBLIC_PROMPT = "Reply exactly with LANGGRAPH_LLM_OK. Do not call a tool."
CONFIDENTIAL_PROMPT = (
    "Investigate station S04. Establish the current machine state and active fault, "
    "then retrieve the technical documentation relevant to that fault. Provide a final "
    "diagnosis in German."
)
_LOCAL_BM25_KNOWLEDGE_SERVER_SOURCE = """
import os
from pathlib import Path

from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
    InMemoryBm25KnowledgeRetriever,
    load_markdown_chunks,
)
from industrial_ai_agent.infrastructure.knowledge_mcp_server import create_knowledge_mcp_server
from industrial_ai_agent.tools.documentation_search import DocumentationSearchCapability

knowledge_root = Path(os.environ["KNOWLEDGE_ROOT"])
retriever = InMemoryBm25KnowledgeRetriever(load_markdown_chunks(knowledge_root))
create_knowledge_mcp_server(
    documentation_search=DocumentationSearchCapability(retriever),
).run(transport="stdio")
"""


def main() -> None:
    args = _parse_args()
    load_local_environment(PROJECT_ROOT / ".env")
    configuration = load_model_catalog(CONFIG_PATH)
    authorizer = ModelExecutionAuthorizer()

    if args.confidential_troubleshooting:
        model_id = ModelId("local_quality")
        data_classification = DataClassification.CONFIDENTIAL
        prompt = CONFIDENTIAL_PROMPT
    else:
        model_id = ModelId(args.model_id)
        data_classification = DataClassification.PUBLIC
        prompt = PUBLIC_PROMPT

    _validate_model(configuration, model_id, data_classification, authorizer)

    with OpenAICompatibleLLMClient(configuration) as adapter:
        checked_client = EgressCheckedLLMClient(
            adapter,
            configuration,
            data_classification,
            authorizer=authorizer,
        )
        agent = LangGraphTroubleshootingAgent(
            LLMClientChatModel(
                checked_client,
                model_id,
                supports_structured_output=args.confidential_troubleshooting,
                reasoning_effort=(
                    LLMReasoningEffort.NONE
                    if args.confidential_troubleshooting
                    else None
                ),
            ),
            mcp_tool_provider=McpLangChainToolProvider(_mcp_servers_from_args(args)),
            run_classification=(
                data_classification if args.confidential_troubleshooting else None
            ),
            investigation_type=(
                InvestigationType.STATION_TROUBLESHOOTING
                if args.confidential_troubleshooting
                else None
            ),
        )
        session_lines: list[str] = []
        result = asyncio.run(
            agent.aanswer_via_mcp(
                prompt,
                session_observer=lambda session: session_lines.extend(
                    (
                        "mcp_session_initialized=true",
                        *(
                            f"mcp_server={server.server_id}:"
                            f"{server.server_name} {server.server_version}"
                            for server in session.servers
                        ),
                        f"mcp_discovered_tools={','.join(session.discovered_tool_names)}",
                    )
                ),
            )
        )

    if result.final_answer is None:
        raise RuntimeError("LangGraph smoke did not return a final answer")
    if (
        not args.confidential_troubleshooting
        and result.final_answer != "LANGGRAPH_LLM_OK"
    ):
        raise RuntimeError("Synthetic LangGraph response did not match expected text")
    if args.confidential_troubleshooting:
        actual_tools = [call.tool for call in result.executed_tool_calls]
        if set(actual_tools) != {"get_machine_status", "search_documentation"}:
            raise RuntimeError(
                "MCP troubleshooting smoke did not obtain the required S04 evidence: "
                f"{actual_tools}"
            )
    print(f"model_id={model_id.value}")
    print(f"classification={data_classification.name}")
    print(f"status={result.status.value}")
    print(f"tool_call_count={result.tool_call_count}")
    for line in session_lines:
        print(line)
    print(result.final_answer)


def _validate_model(
    configuration: ModelCatalogConfiguration,
    model_id: ModelId,
    data_classification: DataClassification,
    authorizer: ModelExecutionAuthorizer,
) -> None:
    model = configuration.get_model(model_id.value)
    if not AGENT_REQUIREMENTS <= model.capabilities:
        raise RuntimeError("Configured smoke-test model lacks agent capabilities")
    authorizer.require_allowed(
        data_classification, model.execution_zone, model.max_data_classification
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run explicit LangGraph troubleshooting smoke scenarios."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--model-id")
    selection.add_argument("--confidential-troubleshooting", action="store_true")
    parser.add_argument(
        "--mcp-transport",
        choices=("stdio", "http"),
        default="stdio",
        help="Select both MCP connections at this composition root.",
    )
    parser.add_argument(
        "--mcp-url",
        default="http://127.0.0.1:8001/mcp",
        help="Factory Streamable HTTP endpoint used with --mcp-transport http.",
    )
    parser.add_argument(
        "--knowledge-mcp-url",
        default="http://127.0.0.1:8002/mcp",
        help="Knowledge Streamable HTTP endpoint used with --mcp-transport http.",
    )
    return parser.parse_args()


def _mcp_servers_from_args(
    args: argparse.Namespace,
) -> tuple[McpServerConfiguration, ...]:
    if args.mcp_transport == "http":
        factory_transport: FactoryMcpTransport = StreamableHttpServerParameters(
            url=args.mcp_url,
            bearer_token=_required_industrial_agent_token(),
        )
        knowledge_transport: FactoryMcpTransport = StreamableHttpServerParameters(
            url=args.knowledge_mcp_url,
            bearer_token=_required_industrial_agent_token(),
        )
    else:
        factory_transport = StdioServerParameters(
            command=sys.executable,
            args=["-m", "industrial_ai_agent.infrastructure.factory_mcp_server"],
        )
        knowledge_transport = StdioServerParameters(
            command=sys.executable,
            args=["-c", _LOCAL_BM25_KNOWLEDGE_SERVER_SOURCE],
            env={"KNOWLEDGE_ROOT": str(PROJECT_ROOT / "knowledge_base")},
        )
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


def _required_industrial_agent_token() -> str:
    token = os.getenv("MCP_INDUSTRIAL_AGENT_TOKEN")
    if not token:
        raise RuntimeError("MCP_INDUSTRIAL_AGENT_TOKEN must be configured")
    return token


if __name__ == "__main__":
    main()
