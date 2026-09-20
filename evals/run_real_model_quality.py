"""Run deterministic quality checks over real LangGraph/MCP model executions."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from mcp.client.stdio import StdioServerParameters

from evals.real_model_quality import (
    QualityScenario,
    RealModelRunArtifact,
    annotate_repeatability,
    evaluate_real_model_run,
)
from evals.run_trajectory import (
    DEFAULT_CONFIG_PATH,
    PROJECT_ROOT,
    _mcp_servers_from_args,
)
from industrial_ai_agent.agent.failure_origin import FailureOrigin
from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import (
    LLMClient,
    LLMProviderError,
    LLMReasoningEffort,
    LLMRequest,
    LLMResponse,
    ModelId,
)
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
)
from industrial_ai_agent.agent.model_selection import (
    AGENT_REQUIREMENTS,
    ModelCapability,
)
from industrial_ai_agent.infrastructure.llm.configuration import load_model_catalog
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.local_environment import load_local_environment
from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    DEFAULT_ALLOWED_KNOWLEDGE_TOOLS,
    McpLangChainToolProvider,
    McpServerConfiguration,
)

_BM25_KNOWLEDGE_SERVER_SOURCE = """
from pathlib import Path
from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import InMemoryBm25KnowledgeRetriever, load_markdown_chunks
from industrial_ai_agent.infrastructure.knowledge_mcp_server import create_knowledge_mcp_server
from industrial_ai_agent.tools.documentation_search import DocumentationSearchCapability
knowledge_root = Path(__import__('sys').argv[1])
create_knowledge_mcp_server(documentation_search=DocumentationSearchCapability(InMemoryBm25KnowledgeRetriever(load_markdown_chunks(knowledge_root)))).run(transport='stdio')
"""

S04_SCENARIO = QualityScenario(
    scenario_id="s04_quality_09_real_model",
    requested_language="de",
    required_tools=("get_machine_status", "search_documentation"),
    allowed_tools=("get_machine_status", "search_documentation"),
    required_identifiers=("S04", "QUALITY-09"),
    required_documents=("DOC-QUALITY-09",),
    require_next_steps=True,
)
S04_REQUEST = (
    "Untersuche Station S04 genauer. Ermittle die Ursache des aktuellen Fehlers, "
    "nutze die technische Dokumentation und schlage sinnvolle nächste Schritte vor."
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate real-model troubleshooting quality."
    )
    parser.add_argument("--model-id", default="local_quality")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--mcp-transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--mcp-url", default="http://127.0.0.1:8001/mcp")
    parser.add_argument("--knowledge-mcp", action="store_true", default=True)
    parser.add_argument("--knowledge-mcp-url", default="http://127.0.0.1:8002/mcp")
    parser.add_argument(
        "--knowledge-base",
        type=Path,
        default=PROJECT_ROOT / "knowledge_base",
        help="Local corpus used only by the Stdio evaluation MCP server.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "evals/results/real-model-quality-local_quality.json",
    )
    return parser.parse_args()


async def _run(
    args: argparse.Namespace,
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    load_local_environment(PROJECT_ROOT / ".env")
    configuration = load_model_catalog(args.config)
    model_id = ModelId(args.model_id)
    model = configuration.get_model(model_id.value)
    if not AGENT_REQUIREMENTS <= model.capabilities:
        raise ValueError("Configured evaluation model lacks agent capabilities")

    quality_results = []
    first_calls: dict[str, dict[str, object]] = {}
    with OpenAICompatibleLLMClient(configuration) as adapter:
        llm = EgressCheckedLLMClient(
            adapter, configuration, DataClassification.INTERNAL
        )
        for _ in range(args.runs):
            started = perf_counter()
            run_id = str(uuid4())
            try:
                tracing_client = _FirstCallTracingClient(llm, model_id.value)
                agent = LangGraphTroubleshootingAgent(
                    LLMClientChatModel(
                        tracing_client,
                        model_id,
                        supports_structured_output=(
                            ModelCapability.STRUCTURED_OUTPUT in model.capabilities
                        ),
                        reasoning_effort=(
                            LLMReasoningEffort.NONE
                            if model.provider.casefold() == "ollama"
                            else None
                        ),
                    ),
                    mcp_tool_provider=McpLangChainToolProvider(_eval_mcp_servers(args)),
                )
                admitted_tools: tuple[str, ...] = ()

                def observe_session(session) -> None:
                    nonlocal admitted_tools
                    admitted_tools = tuple(tool.name for tool in session.tools)

                run = await agent.aanswer_via_mcp(
                    S04_REQUEST, session_observer=observe_session
                )
                artifact = RealModelRunArtifact(
                    run_id=run_id,
                    model_id=model_id.value,
                    display_name=model.display_name,
                    status=run.status,
                    final_answer=run.final_answer,
                    tool_calls=run.executed_tool_calls,
                    identifiers=run.identifiers,
                    documents=run.documents,
                    next_steps=run.next_steps,
                    duration_ms=(perf_counter() - started) * 1_000,
                )
            except Exception as error:  # noqa: BLE001 - diagnostic boundary
                artifact = RealModelRunArtifact(
                    run_id=run_id,
                    model_id=model_id.value,
                    display_name=model.display_name,
                    failure_origin=_failure_origin(error),
                    duration_ms=(perf_counter() - started) * 1_000,
                )
            quality_results.append(evaluate_real_model_run(S04_SCENARIO, artifact))
            first_calls[run_id] = tracing_client.first_call_summary(admitted_tools)
    return [
        result.model_dump(mode="json")
        for result in annotate_repeatability(tuple(quality_results))
    ], first_calls


class _FirstCallTracingClient(LLMClient):
    """Capture content-free first-call facts while delegating production requests."""

    def __init__(self, delegate: LLMClient, model_id: str) -> None:
        self._delegate = delegate
        self._model_id = model_id
        self._request: LLMRequest | None = None
        self._response: LLMResponse | None = None

    def chat(self, model_id: ModelId, request: LLMRequest) -> LLMResponse:
        response = self._delegate.chat(model_id, request)
        if self._request is None:
            self._request = request
            self._response = response
        return response

    def first_call_summary(self, admitted_tools: tuple[str, ...]) -> dict[str, object]:
        request = self._request
        response = self._response
        if request is None or response is None:
            return {"call_observed": False, "admitted_tools": admitted_tools}
        diagnostics = response.request_diagnostics
        return {
            "call_observed": True,
            "call_type": "tool_decision" if request.tools else "finalization",
            "model_id": self._model_id,
            "required_capabilities": ["text", "tool_calling"],
            "tools_supplied": len(request.tools),
            "tool_names": [tool.name for tool in request.tools],
            "admitted_tools": admitted_tools,
            "tool_choice": "provider_default",
            "reasoning_effort": (
                request.reasoning_effort.value if request.reasoning_effort else None
            ),
            "response_http_status": 200,
            "finish_reason": response.finish_reason.value,
            "normal_text_present": bool(response.text and response.text.strip()),
            "reasoning_content_present": response.reasoning_content_present,
            "tool_calls_present": bool(response.tool_calls),
            "tool_call_count": len(response.tool_calls),
            "selected_tool_names": [call.name for call in response.tool_calls],
            "tool_call_parsing": "PARSED",
            "tool_call_admission": (
                "ADMITTED"
                if all(call.name in admitted_tools for call in response.tool_calls)
                else "NOT_APPLICABLE"
            ),
            "request_payload_bytes": (
                diagnostics.request_payload_bytes if diagnostics is not None else None
            ),
            "message_count": diagnostics.message_count
            if diagnostics is not None
            else None,
        }


def _eval_mcp_servers(args: argparse.Namespace) -> tuple[McpServerConfiguration, ...]:
    """Keep the live runner's transport choice while pinning a local Stdio corpus."""
    servers = _mcp_servers_from_args(args)
    if args.mcp_transport == "http":
        return servers
    factory_server = servers[0]
    knowledge_server = McpServerConfiguration(
        server_id="knowledge",
        transport=StdioServerParameters(
            command=sys.executable,
            args=[
                "-c",
                _BM25_KNOWLEDGE_SERVER_SOURCE,
                str(args.knowledge_base.resolve()),
            ],
        ),
        allowed_tool_names=DEFAULT_ALLOWED_KNOWLEDGE_TOOLS,
    )
    return (factory_server, knowledge_server)


def _failure_origin(error: Exception) -> FailureOrigin:
    if isinstance(error, LLMProviderError):
        return {
            "llm_rate_limit": FailureOrigin.PROVIDER_RATE_LIMIT,
            "llm_quota_exceeded": FailureOrigin.PROVIDER_RATE_LIMIT,
            "llm_provider_unavailable": FailureOrigin.PROVIDER_CONNECTION,
            "llm_provider_request_invalid": FailureOrigin.PROVIDER_REQUEST,
        }.get(error.code, FailureOrigin.PROVIDER_REQUEST)
    name = type(error).__name__.casefold()
    if "mcp" in name:
        return FailureOrigin.MCP
    return FailureOrigin.ORCHESTRATION


def main() -> None:
    args = _parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")
    results, first_calls = asyncio.run(_run(args))
    report = {
        "model_id": args.model_id,
        "scenario_id": S04_SCENARIO.scenario_id,
        "requested_language": S04_SCENARIO.requested_language,
        "runs": results,
        "first_calls": first_calls,
        "summary": _summary(results),
    }
    serialized = json.dumps(report, indent=2)
    print(serialized)
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized + "\n", encoding="utf-8")


def _summary(results: list[dict[str, object]]) -> dict[str, object]:
    healthy = [
        result for result in results if result["infrastructure_health"] == "HEALTHY"
    ]
    dimensions = (
        "task_completion",
        "tool_use_correctness",
        "grounding",
        "causal_discipline",
        "finding_usefulness",
        "next_step_usefulness",
        "reference_relevance",
        "language_compliance",
        "output_cleanliness",
        "repeatability",
    )
    return {
        "total_runs": len(results),
        "infrastructure_health": f"{len(healthy)}/{len(results)}",
        "technical_failures": len(results) - len(healthy),
        "dimensions": {
            dimension: f"{sum(run[dimension]['result'] == 'PASS' for run in healthy)}/{len(healthy)}"
            for dimension in dimensions
        },
        "detected_languages": {
            language: sum(run.get("detected_language") == language for run in healthy)
            for language in ("GERMAN", "ENGLISH", "CHINESE", "MIXED", "UNKNOWN")
        },
        "trajectory": {
            quality: sum(run.get("tool_trajectory") == quality for run in healthy)
            for quality in (
                "COMPLETE",
                "INCOMPLETE",
                "REDUNDANT",
                "IRRELEVANT",
                "LOOPING",
            )
        },
    }


if __name__ == "__main__":
    main()
