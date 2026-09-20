from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import cast

from langchain_core.tools import StructuredTool

from industrial_ai_agent.agent.agent_run import AgentRunStatus
from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
    _evidence_ledger_from_state,
)
from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    ModelProfile,
)
from industrial_ai_agent.agent.mcp_tool_provider import McpToolProvider, McpToolSession
from industrial_ai_agent.agent.model_egress import DataClassification
from industrial_ai_agent.agent.tool_policy import ToolOperation, ToolPolicy
from industrial_ai_agent.domain.investigation_evidence import (
    EvidenceRequirementId,
    InvestigationType,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel


@dataclass
class FakeLLMClient:
    responses: list[LLMResponse]
    requests: list[LLMRequest] = field(default_factory=list)

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        del profile
        self.requests.append(request)
        return self.responses.pop(0)


@dataclass
class EvidenceMcpToolProvider:
    machine_station_id: str = "S04"
    documentation_fault_id: str = "QUALITY-09"
    calls: list[str] = field(default_factory=list)

    @asynccontextmanager
    async def open_session(self) -> AsyncIterator[McpToolSession]:
        async def machine_status(station_id: str) -> str:
            self.calls.append("machine")
            return json.dumps(
                {
                    "station_id": self.machine_station_id,
                    "found": True,
                    "state": "FAULTED",
                    "active_error_code": "QUALITY-09",
                    "classification": "CONFIDENTIAL",
                }
            )

        async def documentation(query: str) -> str:
            self.calls.append("documentation")
            return json.dumps(
                {
                    "query": query,
                    "results": [
                        {
                            "content": "not retained by evidence state",
                            "document_id": "doc-quality-procedure",
                            "source": "quality.md",
                            "chunk_id": "quality::001",
                            "classification": "CONFIDENTIAL",
                            "metadata": {"fault_ids": [self.documentation_fault_id]},
                        }
                    ],
                }
            )

        yield McpToolSession(
            tools=(
                StructuredTool.from_function(
                    coroutine=machine_status,
                    name="get_machine_status",
                    description="Read machine state.",
                ),
                StructuredTool.from_function(
                    coroutine=documentation,
                    name="search_documentation",
                    description="Read technical documentation.",
                ),
            ),
            discovered_tool_names=("get_machine_status", "search_documentation"),
            server_name="evidence-test",
            server_version="test",
            protocol_version="test",
            tool_policies=(
                ToolPolicy("get_machine_status", ToolOperation.READ),
                ToolPolicy("search_documentation", ToolOperation.READ),
            ),
        )


def test_premature_finalization_is_blocked_and_missing_evidence_reaches_model() -> None:
    client = FakeLLMClient(
        [
            _final("Unbelegte Antwort."),
            _tool("get_machine_status", {"station_id": "S04"}, "machine-1"),
            _final("Noch ohne Dokumentation."),
            _tool("search_documentation", {"query": "QUALITY-09"}, "doc-1"),
            _final("Jetzt ist die Untersuchung begründet."),
        ]
    )

    state = _run(client, EvidenceMcpToolProvider())

    assert state["run_status"] is AgentRunStatus.SUCCESS
    assert state["evidence_missing"] == ()
    assert state["evidence_guard_interventions"] == 2
    assert len(client.requests) == 5
    feedback = client.requests[1].messages[-1].content
    assert "aktueller Maschinenzustand der Zielstation" in feedback
    assert "CURRENT_MACHINE_STATE" in feedback
    assert "RELEVANT_FAULT_DOCUMENTATION" in feedback
    second_feedback = client.requests[3].messages[-1].content
    assert "RELEVANT_FAULT_DOCUMENTATION" in second_feedback


def test_machine_state_without_documentation_blocks_finalization() -> None:
    client = FakeLLMClient(
        [
            _tool("get_machine_status", {"station_id": "S04"}, "machine-1"),
            _final("Ohne Dokumentation."),
            _final("Weiterhin ohne Dokumentation."),
            _final("Noch immer ohne Dokumentation."),
            _final("Letzter unbelegter Versuch."),
        ]
    )

    state = _run(client, EvidenceMcpToolProvider())

    assert state["run_status"] is AgentRunStatus.EVIDENCE_REQUIREMENTS_UNSATISFIED
    assert state["evidence_missing"] == (
        EvidenceRequirementId.RELEVANT_FAULT_DOCUMENTATION,
    )
    assert "erforderliche Evidenz fehlt" in (state["final_answer"] or "")


def test_documentation_without_machine_state_does_not_satisfy_rca_contract() -> None:
    client = FakeLLMClient(
        [
            _tool("search_documentation", {"query": "QUALITY-09"}, "doc-1"),
            _final("Dokumentation allein reicht nicht."),
            _final("Unbelegt."),
            _final("Unbelegt."),
            _final("Unbelegt."),
        ]
    )

    state = _run(client, EvidenceMcpToolProvider())

    assert state["run_status"] is AgentRunStatus.EVIDENCE_REQUIREMENTS_UNSATISFIED
    assert state["evidence_missing"] == (
        EvidenceRequirementId.CURRENT_MACHINE_STATE,
        EvidenceRequirementId.ACTIVE_FAULT,
        EvidenceRequirementId.RELEVANT_FAULT_DOCUMENTATION,
    )


def test_unrelated_station_and_documentation_do_not_satisfy_s04_requirements() -> None:
    client = FakeLLMClient(
        [
            _tool("get_machine_status", {"station_id": "S03"}, "machine-1"),
            _tool("search_documentation", {"query": "POSITION-ENC-02"}, "doc-1"),
            _final("Unbelegt."),
            _final("Unbelegt."),
            _final("Unbelegt."),
            _final("Unbelegt."),
        ]
    )

    state = _run(
        client,
        EvidenceMcpToolProvider(
            machine_station_id="S03", documentation_fault_id="POSITION-ENC-02"
        ),
    )

    assert state["run_status"] is AgentRunStatus.EVIDENCE_REQUIREMENTS_UNSATISFIED
    assert state["evidence_missing"] == (
        EvidenceRequirementId.CURRENT_MACHINE_STATE,
        EvidenceRequirementId.ACTIVE_FAULT,
        EvidenceRequirementId.RELEVANT_FAULT_DOCUMENTATION,
    )


def test_tool_budget_exhaustion_has_a_deterministic_evidence_outcome() -> None:
    client = FakeLLMClient(
        [
            _tool("get_machine_status", {"station_id": "S04"}, "machine-1"),
            _tool("get_machine_status", {"station_id": "S04"}, "machine-2"),
            _tool("get_machine_status", {"station_id": "S04"}, "machine-3"),
            _tool("get_machine_status", {"station_id": "S04"}, "machine-4"),
            _tool("get_machine_status", {"station_id": "S04"}, "machine-5"),
        ]
    )

    state = _run(client, EvidenceMcpToolProvider())

    assert state["run_status"] is AgentRunStatus.EVIDENCE_REQUIREMENTS_UNSATISFIED
    assert state["executed_tool_count"] == 4
    assert state["evidence_guard_interventions"] == 0


def test_checkpoint_state_reconstructs_exactly_and_preserves_classification() -> None:
    client = FakeLLMClient(
        [
            _tool("get_machine_status", {"station_id": "S04"}, "machine-1"),
            _tool("search_documentation", {"query": "QUALITY-09"}, "doc-1"),
            _final("Begründete Antwort."),
        ]
    )
    agent = _agent(client, EvidenceMcpToolProvider())
    checkpoint_state = agent._initial_state(
        "Untersuche S04.",
        system_content="test",
    )
    state = asyncio.run(agent.ainvoke_via_mcp("Untersuche S04."))
    del checkpoint_state

    restored = _evidence_ledger_from_state(
        {
            **agent._initial_state("Untersuche S04.", system_content="test"),
            "evidence_required": tuple(
                item.value for item in state["evidence_required"]
            ),
            "evidence_satisfied": tuple(
                item.value for item in state["evidence_satisfied"]
            ),
            "evidence_missing": tuple(item.value for item in state["evidence_missing"]),
            "evidence_observations": state["evidence_observations"],
            "evidence_effective_classification": int(
                state["evidence_effective_classification"]
            ),
        }
    )

    assert restored is not None
    assert restored.complete is True
    assert restored.effective_data_classification is DataClassification.CONFIDENTIAL
    assert state["evidence_guard_interventions"] == 0


def test_station_list_and_status_only_requirements_remain_proportional() -> None:
    station_list = LangGraphTroubleshootingAgent(
        LLMClientChatModel(FakeLLMClient([_final("S04")]), ModelProfile("test")),
        mcp_tool_provider=cast(McpToolProvider, EvidenceMcpToolProvider()),
        run_classification=DataClassification.CONFIDENTIAL,
        investigation_type=InvestigationType.STATION_LIST,
        normalize_structured_final_output=False,
    )
    list_state = asyncio.run(
        station_list.ainvoke_via_mcp("Welche Stationen kennst du?")
    )
    assert list_state["run_status"] is AgentRunStatus.SUCCESS
    assert list_state["evidence_required"] == ()

    status_client = FakeLLMClient(
        [
            _tool("get_machine_status", {"station_id": "S04"}, "machine-1"),
            _final("S04 ist fehlerhaft."),
        ]
    )
    status_state = _run(
        status_client,
        EvidenceMcpToolProvider(),
        investigation_type=InvestigationType.STATION_STATUS,
    )
    assert status_state["run_status"] is AgentRunStatus.SUCCESS
    assert status_state["evidence_required"] == (
        EvidenceRequirementId.CURRENT_MACHINE_STATE,
    )


def _run(
    client: FakeLLMClient,
    provider: EvidenceMcpToolProvider,
    *,
    investigation_type: InvestigationType = InvestigationType.STATION_TROUBLESHOOTING,
):
    return asyncio.run(
        _agent(client, provider, investigation_type=investigation_type).ainvoke_via_mcp(
            "Untersuche Station S04 genauer."
        )
    )


def _agent(
    client: FakeLLMClient,
    provider: EvidenceMcpToolProvider,
    *,
    investigation_type: InvestigationType = InvestigationType.STATION_TROUBLESHOOTING,
) -> LangGraphTroubleshootingAgent:
    return LangGraphTroubleshootingAgent(
        LLMClientChatModel(client, ModelProfile("test")),
        mcp_tool_provider=cast(McpToolProvider, provider),
        run_classification=DataClassification.CONFIDENTIAL,
        investigation_type=investigation_type,
        normalize_structured_final_output=False,
    )


def _tool(name: str, arguments: dict[str, object], call_id: str) -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=(LLMToolCall(id=call_id, name=name, arguments=arguments),),
        finish_reason=FinishReason.TOOL_CALLS,
    )


def _final(text: str) -> LLMResponse:
    return LLMResponse(text=text, finish_reason=FinishReason.STOP)
