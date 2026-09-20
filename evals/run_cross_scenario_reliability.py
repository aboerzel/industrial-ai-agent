"""Measure real local-model reliability across existing demo scenarios only.

This runner is intentionally evaluation-only.  It uses the deployed, authenticated
HTTP MCP services so each scenario observes its server-owned clearance projection.
It neither changes model routing nor retries/repairs model output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from langchain_core.messages import ToolMessage

from evals.real_model_quality import (
    DetectedLanguage,
    QualityScenario,
    RealModelRunArtifact,
    detect_output_artifacts,
    detect_output_language,
    evaluate_real_model_run,
)
from evals.run_real_model_quality import (
    _failure_origin,
    _FirstCallTracingClient,
    _safe_evidence_state,
    _trusted_reference_fault_ids,
)
from evals.run_trajectory import PROJECT_ROOT
from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import LLMReasoningEffort, ModelId
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
)
from industrial_ai_agent.agent.model_selection import ModelCapability
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    AgentRunProfile,
    RunClearanceDeniedError,
)
from industrial_ai_agent.domain.investigation_evidence import InvestigationType
from industrial_ai_agent.domain.security import SecurityContext
from industrial_ai_agent.infrastructure.factory_mcp_client import (
    StreamableHttpServerParameters,
)
from industrial_ai_agent.infrastructure.llm.configuration import load_model_catalog
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

_SAFE_IDENTIFIER = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b|\bS\d{2,3}\b")


@dataclass(frozen=True, slots=True)
class ScenarioContract:
    scenario_id: str
    request: str
    classification: DataClassification
    profile: AgentRunProfile
    investigation_type: InvestigationType | None
    required_identifiers: tuple[str, ...]
    required_answer_facts: tuple[str, ...]
    required_documents: tuple[str, ...] = ()
    required_reference_fault_ids: tuple[str, ...] = ()


SCENARIOS = (
    ScenarioContract(
        "public_station_list",
        "Liste die Produktionsstationen auf, die in dieser Demo fuer mich verfuegbar sind.",
        DataClassification.PUBLIC,
        AgentRunProfile.PUBLIC_INFORMATION,
        InvestigationType.STATION_LIST,
        ("S01", "S05"),
        ("S01", "S05"),
    ),
    ScenarioContract(
        "internal_s02_status",
        "Wie ist der aktuelle Status von Station S02?",
        DataClassification.INTERNAL,
        AgentRunProfile.INTERNAL_DIAGNOSTIC,
        InvestigationType.STATION_STATUS,
        ("S02",),
        ("S02", "RUNNING"),
    ),
    ScenarioContract(
        "confidential_quality_09_documentation",
        "Erklaere QUALITY-09 anhand der verfuegbaren technischen Dokumentation.",
        DataClassification.CONFIDENTIAL,
        AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
        None,
        ("QUALITY-09",),
        ("QUALITY-09",),
        ("doc-s04quality09procedure",),
    ),
    ScenarioContract(
        "confidential_s04_rca_control",
        "Untersuche Station S04 genauer. Ermittle die Ursache des aktuellen Fehlers, nutze die technische Dokumentation und schlage sinnvolle naechste Schritte vor.",
        DataClassification.CONFIDENTIAL,
        AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
        InvestigationType.STATION_TROUBLESHOOTING,
        ("S04", "QUALITY-09"),
        ("S04", "QUALITY-09"),
        (),
        ("QUALITY-09",),
    ),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", default="local_quality")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--scenarios",
        nargs="+",
        choices=tuple(contract.scenario_id for contract in SCENARIOS),
        help="Optional subset; intended for a proportional comparison sample.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "evals/results/phase5d-cross-scenario-9b.json",
    )
    return parser.parse_args()


def _token_for(profile: AgentRunProfile) -> str:
    name = {
        AgentRunProfile.PUBLIC_INFORMATION: "MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN",
        AgentRunProfile.INTERNAL_DIAGNOSTIC: "MCP_INDUSTRIAL_AGENT_INTERNAL_TOKEN",
        AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING: "MCP_INDUSTRIAL_AGENT_TOKEN",
    }[profile]
    token = os.getenv(name)
    if not token:
        raise RuntimeError(f"{name} is required for the HTTP reliability evaluation")
    return token


def _provider(contract: ScenarioContract) -> McpLangChainToolProvider:
    policy = AgentRunClassificationPolicy().resolve(contract.profile)
    token = _token_for(contract.profile)
    factory_tools = frozenset(DEFAULT_ALLOWED_FACTORY_TOOLS) & policy.allowed_tool_names
    knowledge_tools = (
        frozenset(DEFAULT_ALLOWED_KNOWLEDGE_TOOLS) & policy.allowed_tool_names
    )
    servers = []
    if factory_tools:
        servers.append(
            McpServerConfiguration(
                server_id="factory",
                transport=StreamableHttpServerParameters(
                    "http://127.0.0.1:8001/mcp", bearer_token=token
                ),
                allowed_tool_names=factory_tools,
            )
        )
    if knowledge_tools:
        servers.append(
            McpServerConfiguration(
                server_id="knowledge",
                transport=StreamableHttpServerParameters(
                    "http://127.0.0.1:8002/mcp", bearer_token=token
                ),
                allowed_tool_names=knowledge_tools,
            )
        )
    return McpLangChainToolProvider(
        tuple(servers), data_classification=contract.classification.name
    )


def _quality_contract(contract: ScenarioContract) -> QualityScenario:
    return QualityScenario(
        scenario_id=contract.scenario_id,
        requested_language="de",
        required_identifiers=contract.required_identifiers,
        required_answer_facts=contract.required_answer_facts,
        required_documents=contract.required_documents,
        required_reference_fault_ids=contract.required_reference_fault_ids,
    )


def _filtering_interventions(
    decisions: list[dict[str, object]], admitted_tools: tuple[str, ...]
) -> int:
    # Action-tool removal is a separate deterministic read-only boundary.  Count only
    # narrowing among the eligible read observations as evidence-source filtering.
    admitted = set(admitted_tools) - {"create_maintenance_ticket"}
    return sum(
        bool(set(decision["visible_tool_names"]) < admitted)
        for decision in decisions
        if decision["call_type"] == "tool_decision"
        and isinstance(decision.get("visible_tool_names"), list)
    )


def _safe_tool_structure(
    state: dict[str, object], tracing: _FirstCallTracingClient
) -> dict[str, object]:
    """Record structure and trusted metadata, never query/document prose."""
    observations = {
        message.tool_call_id: message.content
        for message in state.get("messages", ())
        if isinstance(message, ToolMessage) and isinstance(message.tool_call_id, str)
    }
    calls: list[dict[str, object]] = []
    for raw_call in state.get("executed_tool_calls", ()):
        call = (
            raw_call.model_dump(mode="json")
            if callable(getattr(raw_call, "model_dump", None))
            else raw_call
        )
        if not isinstance(call, dict):
            continue
        tool = call.get("tool")
        arguments = call.get("arguments")
        safe_arguments: dict[str, object] = {
            "field_names": sorted(arguments) if isinstance(arguments, dict) else [],
        }
        if tool == "search_documentation" and isinstance(arguments, dict):
            query = arguments.get("query")
            query_text = query if isinstance(query, str) else ""
            safe_arguments.update(
                {
                    "query_identifier_tokens": sorted(
                        {
                            token.upper()
                            for token in _SAFE_IDENTIFIER.findall(query_text)
                        }
                    ),
                    "quality_09_explicit": "QUALITY-09" in query_text.upper(),
                    "query_length": len(query_text),
                }
            )
        payload: dict[str, object] = {}
        content = observations.get(call.get("tool_call_id"))
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict) and tool == "search_documentation":
                results = parsed.get("results")
                if isinstance(results, list):
                    payload = {
                        "retrieval_result_count": len(results),
                        "retrieval_documents": [
                            {
                                "document_id": item.get("document_id"),
                                "rank": item.get("rank"),
                                "trusted_fault_ids": (item.get("metadata") or {}).get(
                                    "fault_ids", []
                                )
                                if isinstance(item, dict)
                                else [],
                            }
                            for item in results
                            if isinstance(item, dict)
                        ],
                    }
        calls.append({"tool": tool, "arguments": safe_arguments, **payload})

    model_knows_quality_after_status = False
    calls_seen = getattr(tracing, "_calls", ())
    for index, (_, response) in enumerate(calls_seen):
        if any(call.name == "get_machine_status" for call in response.tool_calls):
            if index + 1 < len(calls_seen):
                next_request, _ = calls_seen[index + 1]
                model_knows_quality_after_status = any(
                    "QUALITY-09" in str(message.content).upper()
                    for message in next_request.messages
                )
            break
    return {
        "tool_calls": calls,
        "quality_09_in_next_model_runtime_context": model_knows_quality_after_status,
    }


async def _run_contract(
    contract: ScenarioContract, *, model_id: ModelId, model, runs: int, configuration
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    with OpenAICompatibleLLMClient(configuration) as adapter:
        llm = EgressCheckedLLMClient(adapter, configuration, contract.classification)
        for _ in range(runs):
            started = perf_counter()
            run_id = str(uuid4())
            state: dict[str, object] | None = None
            admitted_tools: tuple[str, ...] = ()
            tracing = _FirstCallTracingClient(llm, model_id.value)
            error: Exception | None = None
            try:
                agent = LangGraphTroubleshootingAgent(
                    LLMClientChatModel(
                        tracing,
                        model_id,
                        supports_structured_output=ModelCapability.STRUCTURED_OUTPUT
                        in model.capabilities,
                        reasoning_effort=LLMReasoningEffort.NONE,
                    ),
                    mcp_tool_provider=_provider(contract),
                    run_classification=contract.classification,
                    investigation_type=contract.investigation_type,
                )

                def observe(session) -> None:
                    nonlocal admitted_tools
                    admitted_tools = tuple(tool.name for tool in session.tools)

                state = await agent.ainvoke_via_mcp(
                    contract.request, session_observer=observe
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
            except Exception as caught:  # noqa: BLE001 - preserve measurement boundary
                error = caught
                artifact = RealModelRunArtifact(
                    run_id=run_id,
                    model_id=model_id.value,
                    display_name=model.display_name,
                    failure_origin=_failure_origin(caught),
                    duration_ms=(perf_counter() - started) * 1_000,
                )
            quality = evaluate_real_model_run(
                _quality_contract(contract), artifact
            ).model_dump(mode="json")
            answer = artifact.final_answer or ""
            answer_upper = answer.upper()
            answer_facts = all(
                fact.upper() in answer_upper for fact in contract.required_answer_facts
            )
            evidence = _safe_evidence_state(state) if state is not None else None
            evidence_complete = evidence is not None and not evidence["missing"]
            decisions = tracing.decision_summaries(admitted_tools)
            output.append(
                {
                    "run_id": run_id,
                    "quality": quality,
                    "answer_facts_complete": answer_facts,
                    "evidence_complete": evidence_complete
                    if contract.investigation_type is not None
                    else "NOT_EVALUATED",
                    "evidence_state": evidence,
                    "evidence_source_filtering_interventions": _filtering_interventions(
                        decisions, admitted_tools
                    ),
                    "decision_trajectory": decisions,
                    "safe_tool_structure": _safe_tool_structure(state, tracing)
                    if state is not None
                    else None,
                    "tool_call_count": len(artifact.tool_calls),
                    "budget_exhausted": getattr(artifact.status, "value", None)
                    == "LIMIT_REACHED",
                    "output_artifacts": detect_output_artifacts(answer),
                    "detected_language": detect_output_language(answer).value
                    if answer
                    else DetectedLanguage.UNKNOWN.value,
                    "error": None
                    if error is None
                    else {
                        "type": type(error).__name__,
                        "origin": artifact.failure_origin.value
                        if artifact.failure_origin
                        else None,
                    },
                }
            )
    return output


def _security_control() -> dict[str, object]:
    context = SecurityContext(
        "phase5d-internal", ("internal",), DataClassification.INTERNAL, True
    )
    try:
        AgentRunClassificationPolicy().resolve(
            AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING, security_context=context
        )
    except RunClearanceDeniedError:
        return {"passed": True, "model_calls": 0, "protected_facts_disclosed": False}
    return {"passed": False, "model_calls": 0, "protected_facts_disclosed": False}


def _summary(results: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    runs = [run for scenario_runs in results.values() for run in scenario_runs]
    healthy = [
        run for run in runs if run["quality"]["infrastructure_health"] == "HEALTHY"
    ]
    answer_runs = [
        run
        for run in healthy
        if run["quality"]["language_compliance"]["result"] != "NOT_EVALUATED"
    ]
    return {
        "total_real_model_runs": len(runs),
        "infrastructure_healthy": f"{len(healthy)}/{len(runs)}",
        "task_complete": f"{sum(run['quality']['task_completion']['result'] == 'PASS' and run['answer_facts_complete'] for run in healthy)}/{len(healthy)}",
        "grounded": f"{sum(run['quality']['grounding']['result'] == 'PASS' and run['answer_facts_complete'] for run in healthy)}/{len(healthy)}",
        "german": f"{sum(run['quality']['language_compliance']['result'] == 'PASS' for run in answer_runs)}/{len(answer_runs)}",
        "language_not_evaluated": sum(
            run["quality"]["language_compliance"]["result"] == "NOT_EVALUATED"
            for run in healthy
        ),
        "unsupported_claims": sum(
            run["quality"]["causal_discipline"]["result"] == "FAIL" for run in healthy
        ),
        "output_artifacts": sum(bool(run["output_artifacts"]) for run in healthy),
        "budget_exhausted": sum(run["budget_exhausted"] for run in runs),
        "evidence_guard_interventions": sum(
            (run["evidence_state"] or {}).get("guard_interventions", 0) for run in runs
        ),
        "evidence_source_filtering_interventions": sum(
            run["evidence_source_filtering_interventions"] for run in runs
        ),
    }


async def _main(args: argparse.Namespace) -> dict[str, object]:
    load_local_environment(PROJECT_ROOT / ".env")
    configuration = load_model_catalog(PROJECT_ROOT / "config/model_catalog.toml")
    model_id = ModelId(args.model_id)
    model = configuration.get_model(model_id.value)
    selected = tuple(
        contract
        for contract in SCENARIOS
        if args.scenarios is None or contract.scenario_id in args.scenarios
    )
    results = {
        contract.scenario_id: await _run_contract(
            contract,
            model_id=model_id,
            model=model,
            runs=args.runs,
            configuration=configuration,
        )
        for contract in selected
    }
    return {
        "phase": "5D",
        "model_id": model_id.value,
        "display_name": model.display_name,
        "reasoning_effort": "none",
        "contracts": [asdict(contract) for contract in selected],
        "results": results,
        "security_control": _security_control(),
        "summary": _summary(results),
    }


def main() -> None:
    args = _parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")
    report = asyncio.run(_main(args))
    serialized = json.dumps(report, indent=2, default=str)
    print(serialized)
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
