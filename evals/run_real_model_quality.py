"""Run deterministic quality checks over real LangGraph/MCP model executions."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from langchain_core.messages import SystemMessage
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
from industrial_ai_agent.agent.langchain_model import to_llm_response
from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    MCP_TROUBLESHOOTING_SYSTEM_MESSAGE,
    LangGraphTroubleshootingAgent,
    _missing_evidence_instruction,
    _read_only_tools,
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
from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.domain.investigation_evidence import (
    EvidenceLedger,
    EvidenceSource,
    EvidenceSourceType,
    InvestigationType,
    MachineStateEvidence,
)
from industrial_ai_agent.domain.machine_status import MachineState
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
    required_reference_fault_ids=("QUALITY-09",),
)
S04_REQUEST = (
    "Untersuche Station S04 genauer. Ermittle die Ursache des aktuellen Fehlers, "
    "nutze die technische Dokumentation und schlage sinnvolle nächste Schritte vor."
)
S04_EVALUATION_CLASSIFICATION = DataClassification.CONFIDENTIAL


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate real-model troubleshooting quality."
    )
    parser.add_argument("--model-id", default="local_quality")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument(
        "--diagnose-evidence-decisions",
        action="store_true",
        help="Run content-free controlled tool-decision diagnostics for RCA evidence.",
    )
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
) -> tuple[
    list[dict[str, object]],
    dict[str, dict[str, object]],
    dict[str, list[dict[str, object]]],
    dict[str, dict[str, object]],
]:
    load_local_environment(PROJECT_ROOT / ".env")
    configuration = load_model_catalog(args.config)
    model_id = ModelId(args.model_id)
    model = configuration.get_model(model_id.value)
    if not AGENT_REQUIREMENTS <= model.capabilities:
        raise ValueError("Configured evaluation model lacks agent capabilities")

    quality_results = []
    first_calls: dict[str, dict[str, object]] = {}
    trajectories: dict[str, list[dict[str, object]]] = {}
    evidence_states: dict[str, dict[str, object]] = {}
    execution_errors: dict[str, dict[str, object]] = {}
    with OpenAICompatibleLLMClient(configuration) as adapter:
        llm = EgressCheckedLLMClient(
            adapter, configuration, S04_EVALUATION_CLASSIFICATION
        )
        for _ in range(args.runs):
            started = perf_counter()
            run_id = str(uuid4())
            state = None
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
                    run_classification=S04_EVALUATION_CLASSIFICATION,
                    investigation_type=InvestigationType.STATION_TROUBLESHOOTING,
                )
                admitted_tools: tuple[str, ...] = ()

                def observe_session(session) -> None:
                    nonlocal admitted_tools
                    admitted_tools = tuple(tool.name for tool in session.tools)

                state = await agent.ainvoke_via_mcp(
                    S04_REQUEST, session_observer=observe_session
                )
                artifact = RealModelRunArtifact(
                    run_id=run_id,
                    model_id=model_id.value,
                    display_name=model.display_name,
                    status=state["run_status"],
                    final_answer=state["final_answer"],
                    tool_calls=state["executed_tool_calls"],
                    identifiers=state["identifiers"],
                    documents=state["documents"],
                    trusted_reference_fault_ids=_trusted_reference_fault_ids(state),
                    next_steps=state["next_steps"],
                    duration_ms=(perf_counter() - started) * 1_000,
                )
            except Exception as error:  # noqa: BLE001 - diagnostic boundary
                execution_errors[run_id] = {
                    "error_type": type(error).__name__,
                    "error_code": getattr(error, "code", None),
                    "contained_error_types": _contained_error_types(error),
                }
                artifact = RealModelRunArtifact(
                    run_id=run_id,
                    model_id=model_id.value,
                    display_name=model.display_name,
                    failure_origin=_failure_origin(error),
                    duration_ms=(perf_counter() - started) * 1_000,
                )
            quality_results.append(evaluate_real_model_run(S04_SCENARIO, artifact))
            first_calls[run_id] = tracing_client.first_call_summary(admitted_tools)
            trajectories[run_id] = tracing_client.decision_summaries(admitted_tools)
            if state is not None:
                evidence_states[run_id] = _safe_evidence_state(state)
    controlled = (
        await _run_controlled_evidence_decisions(args, llm, model_id, model)
        if args.diagnose_evidence_decisions
        else {}
    )
    return (
        [
            result.model_dump(mode="json")
            for result in annotate_repeatability(tuple(quality_results))
        ],
        first_calls,
        trajectories,
        {
            **evidence_states,
            "controlled": controlled,
            "execution_errors": execution_errors,
        },
    )


async def _run_controlled_evidence_decisions(
    args: argparse.Namespace,
    llm: LLMClient,
    model_id: ModelId,
    model,
) -> dict[str, dict[str, int]]:
    """Measure tool selection from real schemas without dispatching a tool."""
    scenarios = {
        "missing_all_rca_evidence": EvidenceLedger.for_investigation(
            InvestigationType.STATION_TROUBLESHOOTING,
            station_id="S04",
            effective_data_classification=S04_EVALUATION_CLASSIFICATION,
        ),
        "missing_fault_documentation": EvidenceLedger.for_investigation(
            InvestigationType.STATION_TROUBLESHOOTING,
            station_id="S04",
            effective_data_classification=S04_EVALUATION_CLASSIFICATION,
        ).record(
            MachineStateEvidence(
                station_id="S04",
                state=MachineState.FAULTED,
                active_fault_id="QUALITY-09",
                source=EvidenceSource(EvidenceSourceType.MACHINE_STATE, "synthetic"),
                data_classification=S04_EVALUATION_CLASSIFICATION,
            )
        ),
    }
    outcomes: dict[str, dict[str, int]] = {}
    for scenario_id, ledger in scenarios.items():
        counts: dict[str, int] = {}
        for _ in range(5):
            provider = McpLangChainToolProvider(_eval_mcp_servers(args))
            agent = LangGraphTroubleshootingAgent(
                LLMClientChatModel(
                    llm,
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
                mcp_tool_provider=provider,
                run_classification=S04_EVALUATION_CLASSIFICATION,
                investigation_type=InvestigationType.STATION_TROUBLESHOOTING,
            )
            async with provider.open_session() as session:
                tools = _read_only_tools(session.tools, session.tool_policies)
                messages = agent._initial_messages(
                    "Untersuche die synthetische Station S04."
                    " Wähle die nächste Untersuchungshandlung.",
                    system_content=MCP_TROUBLESHOOTING_SYSTEM_MESSAGE,
                    response_language=ResponseLanguage.DE,
                )
                messages.append(
                    SystemMessage(
                        content=_missing_evidence_instruction(
                            ledger, ResponseLanguage.DE
                        )
                    )
                )
                response = to_llm_response(
                    agent._chat_model.bind_tools(tools).invoke(messages)
                )
            selected = (
                response.tool_calls[0].name
                if len(response.tool_calls) == 1
                else "no_tool_or_other"
            )
            counts[selected] = counts.get(selected, 0) + 1
        outcomes[scenario_id] = counts
    return outcomes


class _FirstCallTracingClient(LLMClient):
    """Capture content-free model-call facts while delegating production requests."""

    def __init__(self, delegate: LLMClient, model_id: str) -> None:
        self._delegate = delegate
        self._model_id = model_id
        self._request: LLMRequest | None = None
        self._response: LLMResponse | None = None
        self._calls: list[tuple[LLMRequest, LLMResponse]] = []

    def chat(self, model_id: ModelId, request: LLMRequest) -> LLMResponse:
        response = self._delegate.chat(model_id, request)
        if self._request is None:
            self._request = request
            self._response = response
        self._calls.append((request, response))
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

    def decision_summaries(
        self, admitted_tools: tuple[str, ...]
    ) -> list[dict[str, object]]:
        return [
            _safe_call_summary(index, request, response, admitted_tools)
            for index, (request, response) in enumerate(self._calls, start=1)
        ]


def _safe_call_summary(
    iteration: int,
    request: LLMRequest,
    response: LLMResponse,
    admitted_tools: tuple[str, ...],
) -> dict[str, object]:
    diagnostics = response.request_diagnostics
    missing = _missing_evidence_ids_from_messages(request)
    return {
        "iteration": iteration,
        "call_type": "tool_decision" if request.tools else "finalization",
        "reasoning_effort": (
            request.reasoning_effort.value if request.reasoning_effort else None
        ),
        "visible_tool_count": len(request.tools),
        "visible_tool_names": [tool.name for tool in request.tools],
        "request_payload_bytes": (
            diagnostics.request_payload_bytes if diagnostics is not None else None
        ),
        "message_roles": [message.role.value for message in request.messages],
        "missing_evidence_instruction_included": bool(missing),
        "missing_evidence_ids": missing,
        "response_finish_reason": response.finish_reason.value,
        "response_has_text": bool(response.text and response.text.strip()),
        "response_has_reasoning": response.reasoning_content_present,
        "response_has_tool_calls": bool(response.tool_calls),
        "selected_tool_names": [call.name for call in response.tool_calls],
        "tool_call_parsing": "PARSED" if response.tool_calls else "NOT_APPLICABLE",
        "tool_call_admission": (
            "ADMITTED"
            if response.tool_calls
            and all(call.name in admitted_tools for call in response.tool_calls)
            else "NOT_APPLICABLE"
        ),
    }


def _missing_evidence_ids_from_messages(request: LLMRequest) -> list[str]:
    requirement_ids = (
        "CURRENT_MACHINE_STATE",
        "ACTIVE_FAULT",
        "RELEVANT_FAULT_DOCUMENTATION",
    )
    return [
        requirement_id
        for message in request.messages
        if message.role.value == "system" and isinstance(message.content, str)
        for line in message.content.splitlines()
        for requirement_id in requirement_ids
        if requirement_id in line
    ]


def _safe_evidence_state(state: dict[str, object]) -> dict[str, object]:
    return {
        "required": [item.value for item in state["evidence_required"]],
        "satisfied": [item.value for item in state["evidence_satisfied"]],
        "missing": [item.value for item in state["evidence_missing"]],
        "guard_interventions": state["evidence_guard_interventions"],
        "finalization_attempts": state["evidence_finalization_attempts"],
        "trusted_reference_fault_ids": _trusted_reference_fault_ids(state),
    }


def _trusted_reference_fault_ids(state: dict[str, object]) -> tuple[str, ...]:
    """Expose only fault IDs from trusted documentation evidence to the evaluator."""
    return tuple(
        sorted(
            {
                fault_id.strip().upper()
                for observation in state.get("evidence_observations", ())
                if isinstance(observation, dict)
                and observation.get("observation_type") == "documentation"
                and isinstance((fault_id := observation.get("fault_id")), str)
                and fault_id.strip()
            }
        )
    )


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


def _contained_error_types(error: BaseException) -> list[str]:
    if isinstance(error, BaseExceptionGroup):
        return sorted(
            {
                name
                for nested in error.exceptions
                for name in _contained_error_types(nested)
            }
        )
    return [type(error).__name__]


def main() -> None:
    args = _parse_args()
    if args.runs < 0 or (args.runs == 0 and not args.diagnose_evidence_decisions):
        raise SystemExit(
            "--runs must be at least 1 unless --diagnose-evidence-decisions is set"
        )
    results, first_calls, trajectories, evidence_states = asyncio.run(_run(args))
    report = {
        "model_id": args.model_id,
        "scenario_id": S04_SCENARIO.scenario_id,
        "requested_language": S04_SCENARIO.requested_language,
        "runs": results,
        "first_calls": first_calls,
        "decision_trajectories": trajectories,
        "evidence_states": evidence_states,
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
