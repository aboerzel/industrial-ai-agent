"""Isolate S04 documentation-evidence decisions without exposing raw prompts."""

from __future__ import annotations

import asyncio
import json

from langchain_core.messages import SystemMessage

from evals.run_cross_scenario_reliability import SCENARIOS, _provider
from evals.run_trajectory import PROJECT_ROOT
from industrial_ai_agent.agent.langchain_model import to_llm_response
from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    MCP_TROUBLESHOOTING_SYSTEM_MESSAGE,
    LangGraphTroubleshootingAgent,
    _missing_evidence_instruction,
    _read_only_tools,
)
from industrial_ai_agent.agent.llm import LLMReasoningEffort, ModelId
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
)
from industrial_ai_agent.agent.model_selection import ModelCapability
from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.application.investigation_evidence_adapters import (
    documentation_evidence_from_result,
)
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
from industrial_ai_agent.tools.documentation_search import DocumentationSearchResult

S04_CONTRACT = next(
    scenario
    for scenario in SCENARIOS
    if scenario.scenario_id == "confidential_s04_rca_control"
)


def _ledger() -> EvidenceLedger:
    return EvidenceLedger.for_investigation(
        InvestigationType.STATION_TROUBLESHOOTING,
        station_id="S04",
        effective_data_classification=DataClassification.CONFIDENTIAL,
    ).record(
        MachineStateEvidence(
            station_id="S04",
            state=MachineState.FAULTED,
            active_fault_id="QUALITY-09",
            source=EvidenceSource(EvidenceSourceType.MACHINE_STATE, "controlled"),
            data_classification=DataClassification.CONFIDENTIAL,
        )
    )


async def _decision_counts() -> dict[str, int]:
    configuration = load_model_catalog(PROJECT_ROOT / "config/model_catalog.toml")
    model_id = ModelId("local_quality")
    model = configuration.get_model(model_id.value)
    ledger = _ledger()
    counts = {
        "search_documentation": 0,
        "correct_quality_09_binding": 0,
        "malformed_or_insufficient": 0,
        "no_tool": 0,
    }
    with OpenAICompatibleLLMClient(configuration) as adapter:
        llm = EgressCheckedLLMClient(
            adapter, configuration, DataClassification.CONFIDENTIAL
        )
        for _ in range(10):
            provider = _provider(S04_CONTRACT)
            agent = LangGraphTroubleshootingAgent(
                LLMClientChatModel(
                    llm,
                    model_id,
                    supports_structured_output=ModelCapability.STRUCTURED_OUTPUT
                    in model.capabilities,
                    reasoning_effort=LLMReasoningEffort.NONE,
                ),
                mcp_tool_provider=provider,
                run_classification=DataClassification.CONFIDENTIAL,
                investigation_type=InvestigationType.STATION_TROUBLESHOOTING,
            )
            async with provider.open_session() as session:
                tools = tuple(
                    tool
                    for tool in _read_only_tools(session.tools, session.tool_policies)
                    if tool.name == "search_documentation"
                )
                messages = agent._initial_messages(
                    "Untersuche die Zielstation.",
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
            if (
                len(response.tool_calls) != 1
                or response.tool_calls[0].name != "search_documentation"
            ):
                counts["no_tool"] += 1
                continue
            counts["search_documentation"] += 1
            query = response.tool_calls[0].arguments.get("query")
            if isinstance(query, str) and "QUALITY-09" in query.upper():
                counts["correct_quality_09_binding"] += 1
            else:
                counts["malformed_or_insufficient"] += 1
    return counts


async def _retrieval_control() -> dict[str, object]:
    provider = _provider(S04_CONTRACT)
    async with provider.open_session() as session:
        tool = next(
            tool for tool in session.tools if tool.name == "search_documentation"
        )
        payload = await tool.ainvoke({"query": "QUALITY-09", "top_k": 3})
    result = DocumentationSearchResult.model_validate_json(payload)
    evidence = documentation_evidence_from_result(
        result,
        fault_id="QUALITY-09",
        source=EvidenceSource(EvidenceSourceType.DOCUMENTATION, "controlled"),
    )
    return {
        "result_count": len(result.results),
        "document_ids": [item.document_id for item in result.results],
        "ranks": list(range(1, len(result.results) + 1)),
        "trusted_fault_ids": [
            list(item.metadata.get("fault_ids", ())) for item in result.results
        ],
        "documentation_evidence_created": evidence is not None,
        "requirement_satisfied": evidence is not None
        and _ledger().record(evidence).complete,
    }


async def _main() -> dict[str, object]:
    load_local_environment(PROJECT_ROOT / ".env")
    return {
        "controlled_decisions": await _decision_counts(),
        "controlled_retrieval": await _retrieval_control(),
    }


def main() -> None:
    report = asyncio.run(_main())
    destination = PROJECT_ROOT / "evals/results/phase5d1-controlled-documentation.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
