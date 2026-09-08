import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import cast

import pytest
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from industrial_ai_agent.agent.agent_run import (
    MAX_NEXT_STEPS,
    MAX_TOOL_CALLS,
    AgentRunResult,
    AgentRunStatus,
    FinalAgentOutput,
    FinalAgentOutputContractError,
    InvestigationStep,
)
from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
    _resolve_investigation_steps,
)
from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMResponse,
    LLMToolCall,
    ModelProfile,
)
from industrial_ai_agent.agent.mcp_tool_provider import McpToolProvider, McpToolSession
from industrial_ai_agent.agent.model_egress import DataClassification
from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.agent.tool_policy import ToolOperation, ToolPolicy
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel


@dataclass
class FakeLLMClient:
    responses: list[LLMResponse]
    requests: list[object] = field(default_factory=list)

    def chat(self, profile: ModelProfile, request: object) -> LLMResponse:
        del profile
        self.requests.append(request)
        return self.responses.pop(0)


class ReadRecordingMcpToolProvider:
    @asynccontextmanager
    async def open_session(self) -> AsyncIterator[McpToolSession]:
        async def get_product_history(product_id: str) -> str:
            assert product_id == "P4711"
            return '{"classification":"CONFIDENTIAL"}'

        yield McpToolSession(
            tools=(
                StructuredTool.from_function(
                    coroutine=get_product_history,
                    name="get_product_history",
                    description="Get product history.",
                ),
            ),
            discovered_tool_names=("get_product_history",),
            server_name="fake_read_mcp",
            server_version="test",
            protocol_version="test",
            tool_policies=(ToolPolicy("get_product_history", ToolOperation.READ),),
        )


def test_final_agent_output_preserves_german_next_steps_and_technical_ids() -> None:
    output = FinalAgentOutput.model_validate(
        {
            "answer": "### Zusammenfassung\n\nS04 meldet QUALITY-09.",
            "next_steps": (
                "Prüfe die Qualitäts-Sensoren von Station S04.",
                "Suche technische Dokumentation zu QUALITY-09.",
            ),
        }
    )

    assert output.next_steps == (
        "Prüfe die Qualitäts-Sensoren von Station S04.",
        "Suche technische Dokumentation zu QUALITY-09.",
    )


def test_final_agent_output_preserves_english_next_steps_and_technical_ids() -> None:
    output = FinalAgentOutput.model_validate(
        {
            "answer": "### Summary\n\nS07 reports PROTO-COMM-07.",
            "next_steps": (
                "Check the current status of station S07.",
                "Search technical documentation for PROTO-COMM-07.",
            ),
        }
    )

    assert output.next_steps[-1] == "Search technical documentation for PROTO-COMM-07."


def test_final_agent_output_allows_no_next_steps() -> None:
    output = FinalAgentOutput.model_validate(
        {"answer": "No further checks are needed."}
    )

    assert output.next_steps == ()


def test_final_agent_output_unwraps_an_empty_serialized_provider_wrapper() -> None:
    output = FinalAgentOutput.from_model_text(
        '{"answer":"{\\"answer\\":\\"S04 is FAULTED with QUALITY-09.\\",'
        '\\"investigation_steps\\":[{\\"step\\":\\"1\\",\\"tool\\":'
        '\\"get_machine_status\\",\\"finding\\":\\"Station S04 is '
        'FAULTED with QUALITY-09.\\"}],\\"next_steps\\":['
        '\\"Check the calibration state of station S04.\\"]}",'
        '"investigation_steps":[{"step":1,"tool":"get_machine_status",'
        '"finding":"Outer fallback finding."}],"next_steps":[]}'
    )

    assert output.answer == "S04 is FAULTED with QUALITY-09."
    assert [(step.step, step.action) for step in output.investigation_steps] == [
        (1, "get_machine_status")
    ]
    assert output.next_steps == ("Check the calibration state of station S04.",)


def test_final_agent_output_detects_observed_recommended_actions_section() -> None:
    output = FinalAgentOutput.model_validate(
        {
            "answer": (
                "**Recommended Actions:**\n\n"
                "1. **Review Product History** - Check recent quality data for patterns\n"
                "2. **Verify S04 Fault State** - Confirm the latest fault state"
            ),
            "next_steps": (),
        }
    )

    assert output.forbidden_action_sections() == ("recommended actions",)
    with pytest.raises(FinalAgentOutputContractError):
        output.require_no_action_sections()


def test_final_agent_output_rejects_investigation_summary_markdown_sections() -> None:
    output = FinalAgentOutput.model_validate(
        {
            "answer": "### Investigation Summary\n\n| Step | Action | Findings / Notes |",
            "investigation_steps": (),
            "next_steps": (),
        }
    )

    assert output.forbidden_investigation_summary_sections() == (
        "investigation summary",
    )
    with pytest.raises(FinalAgentOutputContractError):
        output.require_no_investigation_summary_sections()


def test_final_agent_output_rejects_more_than_the_bounded_number_of_next_steps() -> (
    None
):
    with pytest.raises(ValidationError):
        FinalAgentOutput.model_validate(
            {
                "answer": "Summary",
                "next_steps": [
                    f"Check {index}." for index in range(MAX_NEXT_STEPS + 1)
                ],
            }
        )


def test_limit_reached_result_cannot_expose_next_steps_without_an_answer() -> None:
    with pytest.raises(ValidationError):
        AgentRunResult(
            status=AgentRunStatus.LIMIT_REACHED,
            tool_call_count=MAX_TOOL_CALLS,
            next_steps=("Check station S04.",),
        )


def test_investigation_steps_cannot_diverge_from_the_tool_trajectory() -> None:
    with pytest.raises(ValidationError):
        AgentRunResult(
            status=AgentRunStatus.SUCCESS,
            final_answer="P4711 failed at S04.",
            investigation_steps=(
                InvestigationStep(
                    step=1,
                    action="search_documentation",
                    finding="QUALITY-09 is documented.",
                ),
            ),
            tool_call_count=1,
            executed_tool_calls=(
                {"tool": "get_product_history", "arguments": {"product_id": "P4711"}},
            ),
        )


def test_unknown_finalizer_action_is_replaced_by_the_actual_tool_trajectory() -> None:
    resolved = _resolve_investigation_steps(
        ({"tool": "get_machine_status", "arguments": {"station_id": "S04"}},),
        (
            InvestigationStep(
                step=1,
                action="search_documentation",
                finding="Invented tool observation.",
            ),
        ),
        ResponseLanguage.DE,
    )

    assert resolved == (
        InvestigationStep(
            step=1,
            action="get_machine_status",
            finding="Autorisierte Beobachtung mit get_machine_status abgeschlossen.",
        ),
    )


def test_matching_multiple_and_repeated_tool_steps_preserve_execution_order() -> None:
    executed_tool_calls = (
        {"tool": "get_machine_status", "arguments": {"station_id": "S04"}},
        {"tool": "search_documentation", "arguments": {"query": "QUALITY-09"}},
        {"tool": "get_machine_status", "arguments": {"station_id": "S07"}},
    )
    proposed_steps = (
        InvestigationStep(
            step=1,
            action="get_machine_status",
            finding="Station S04 is FAULTED with QUALITY-09.",
        ),
        InvestigationStep(
            step=2,
            action="search_documentation",
            finding="QUALITY-09 has a troubleshooting procedure.",
        ),
        InvestigationStep(
            step=3,
            action="get_machine_status",
            finding="Station S07 is available.",
        ),
    )

    resolved = _resolve_investigation_steps(
        executed_tool_calls, proposed_steps, ResponseLanguage.EN
    )

    assert resolved == proposed_steps


def test_multi_loop_final_output_retains_structured_next_steps() -> None:
    client = FakeLLMClient(
        responses=[
            LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="history",
                        name="get_product_history",
                        arguments={"product_id": "P4711"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            LLMResponse(
                text=(
                    '{"answer":"P4711 failed at S04.",'
                    '"investigation_steps":[{"step":1,"action":"get_product_history",'
                    '"finding":"P4711 failed at S04."}],'
                    '"next_steps":["Check station S04.",'
                    '"Search technical documentation for QUALITY-09."]}'
                ),
                finish_reason=FinishReason.STOP,
            ),
            LLMResponse(
                text=(
                    '{"answer":"P4711 failed at S04.",'
                    '"investigation_steps":[{"step":1,"action":"get_product_history",'
                    '"finding":"P4711 failed at S04."}],'
                    '"next_steps":["Check station S04.",'
                    '"Search technical documentation for QUALITY-09."]}'
                ),
                finish_reason=FinishReason.STOP,
            ),
        ]
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(
            client, ModelProfile("local_quality"), supports_structured_output=True
        ),
        mcp_tool_provider=cast(McpToolProvider, ReadRecordingMcpToolProvider()),
        run_classification=DataClassification.CONFIDENTIAL,
    )

    result = asyncio.run(agent.aanswer_via_mcp("Investigate P4711 at S04."))

    assert result.status is AgentRunStatus.SUCCESS
    assert result.final_answer == "P4711 failed at S04."
    assert [(step.step, step.action) for step in result.investigation_steps] == [
        (1, "get_product_history")
    ]
    assert result.next_steps == (
        "Check station S04.",
        "Search technical documentation for QUALITY-09.",
    )
    assert len(client.requests) == 3
    finalization_request = client.requests[-1]
    assert finalization_request.response_format is not None
    assert finalization_request.response_format.json_schema.name == (
        "troubleshooting_final_output"
    )
    assert "Response language: English." in (
        finalization_request.messages[0].content or ""
    )


def test_structured_finalizer_replaces_observed_action_list_with_next_steps() -> None:
    observed_answer = (
        "P4711 failed at station S04.\n\n"
        "**Recommended Actions:**\n\n"
        "1. **Review Product History** - Check recent quality data for patterns\n"
        "2. **Verify S04 Fault State** - Confirm latest fault state matches expected behavior\n"
        "3. **Compare Inspection Results** - Measure against normal public S04 inspection overview\n"
        "4. **Document Defect Frame** - Reference IMG-324 defect frame images for comparison"
    )
    client = FakeLLMClient(
        responses=[
            LLMResponse(text=observed_answer, finish_reason=FinishReason.STOP),
            LLMResponse(
                text=(
                    '{"answer":"P4711 failed at station S04.",'
                    '"next_steps":['
                    '"Review the recent product history of P4711 for recurring quality issues.",'
                    '"Check the current fault state of station S04 and compare it with the observed QUALITY-09 failure.",'
                    '"Compare the inspection results with the normal public S04 inspection overview.",'
                    '"Review defect frame IMG-324 and compare it with normal S04 inspection data."]}'
                ),
                finish_reason=FinishReason.STOP,
            ),
        ]
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(
            client, ModelProfile("local_quality"), supports_structured_output=True
        ),
        mcp_tool_provider=cast(McpToolProvider, ReadRecordingMcpToolProvider()),
        run_classification=DataClassification.CONFIDENTIAL,
    )

    result = asyncio.run(agent.aanswer_via_mcp("Investigate P4711 at S04."))

    assert "Recommended Actions" not in (result.final_answer or "")
    assert "Investigation Summary" not in (result.final_answer or "")
    assert result.next_steps == (
        "Review the recent product history of P4711 for recurring quality issues.",
        "Check the current fault state of station S04 and compare it with the observed QUALITY-09 failure.",
        "Compare the inspection results with the normal public S04 inspection overview.",
        "Review defect frame IMG-324 and compare it with normal S04 inspection data.",
    )
    assert client.requests[-1].response_format is not None


def test_unsupported_profile_rejects_action_sections_instead_of_falling_back() -> None:
    client = FakeLLMClient(
        responses=[
            LLMResponse(
                text="### Next Steps\n\n- Check station S04.",
                finish_reason=FinishReason.STOP,
            )
        ]
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(client, ModelProfile("public_fast")),
        mcp_tool_provider=cast(McpToolProvider, ReadRecordingMcpToolProvider()),
        run_classification=DataClassification.CONFIDENTIAL,
    )

    with pytest.raises(FinalAgentOutputContractError):
        asyncio.run(agent.aanswer_via_mcp("Investigate P4711 at S04."))


def test_structured_finalizer_preserves_an_empty_next_steps_list() -> None:
    client = FakeLLMClient(
        responses=[
            LLMResponse(
                text="The investigation is complete and no additional checks are useful.",
                finish_reason=FinishReason.STOP,
            ),
            LLMResponse(
                text=(
                    '{"answer":"The investigation is complete and no additional checks are useful.",'
                    '"next_steps":[]}'
                ),
                finish_reason=FinishReason.STOP,
            ),
        ]
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(
            client, ModelProfile("local_quality"), supports_structured_output=True
        ),
        mcp_tool_provider=cast(McpToolProvider, ReadRecordingMcpToolProvider()),
        run_classification=DataClassification.CONFIDENTIAL,
    )

    result = asyncio.run(agent.aanswer_via_mcp("Is any further investigation useful?"))

    assert (
        result.final_answer
        == "The investigation is complete and no additional checks are useful."
    )
    assert result.next_steps == ()
    assert result.investigation_steps == ()


def test_structured_finalizer_preserves_german_language_and_identifiers() -> None:
    client = FakeLLMClient(
        responses=[
            LLMResponse(
                text="S04 benötigt weitere Untersuchung.",
                finish_reason=FinishReason.STOP,
            ),
            LLMResponse(
                text=(
                    '{"answer":"S04 benötigt weitere Untersuchung.","next_steps":['
                    '"Prüfe den aktuellen Fehlerstatus von Station S04 für QUALITY-09.",'
                    '"Suche technische Dokumentation zu QUALITY-09."]}'
                ),
                finish_reason=FinishReason.STOP,
            ),
        ]
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(
            client, ModelProfile("local_quality"), supports_structured_output=True
        ),
        mcp_tool_provider=cast(McpToolProvider, ReadRecordingMcpToolProvider()),
        run_classification=DataClassification.CONFIDENTIAL,
    )

    result = asyncio.run(agent.aanswer_via_mcp("Untersuche den Fehler an S04."))

    assert result.next_steps == (
        "Prüfe den aktuellen Fehlerstatus von Station S04 für QUALITY-09.",
        "Suche technische Dokumentation zu QUALITY-09.",
    )
    assert "Response language: German." in (
        client.requests[-1].messages[0].content or ""
    )
