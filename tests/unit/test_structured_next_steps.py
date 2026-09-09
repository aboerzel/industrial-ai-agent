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
    MCP_TROUBLESHOOTING_SYSTEM_MESSAGE,
    LangGraphTroubleshootingAgent,
    _deduplicate_document_references,
    _document_references_from_observation,
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
from industrial_ai_agent.agent.troubleshooting_run_service import ConversationTurn
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


class DocumentationRecordingMcpToolProvider:
    @asynccontextmanager
    async def open_session(self) -> AsyncIterator[McpToolSession]:
        async def search_documentation(query: str) -> str:
            assert query == "QUALITY-09 S04"
            return (
                '{"classification":"CONFIDENTIAL","results":[{"document_id":"DOC-QUALITY-09",'
                '"metadata":{"document_title":"S04 QUALITY-09 Troubleshooting '
                'Procedure","format":"markdown"}}]}'
            )

        yield McpToolSession(
            tools=(
                StructuredTool.from_function(
                    coroutine=search_documentation,
                    name="search_documentation",
                    description="Search technical documentation.",
                ),
            ),
            discovered_tool_names=("search_documentation",),
            server_name="fake_knowledge_mcp",
            server_version="test",
            protocol_version="test",
            tool_policies=(ToolPolicy("search_documentation", ToolOperation.READ),),
        )


class ThreeTurnMcpToolProvider:
    @asynccontextmanager
    async def open_session(self) -> AsyncIterator[McpToolSession]:
        async def get_machine_status(station_id: str) -> str:
            assert station_id == "S04"
            return '{"classification":"CONFIDENTIAL","station_id":"S04"}'

        async def search_documentation(query: str) -> str:
            assert query == "QUALITY-09"
            return (
                '{"classification":"CONFIDENTIAL","results":['
                '{"document_id":"DOC-QUALITY-09","metadata":{'
                '"document_title":"S04 QUALITY-09 Troubleshooting Procedure",'
                '"format":"markdown"}}]}'
            )

        yield McpToolSession(
            tools=(
                StructuredTool.from_function(
                    coroutine=get_machine_status,
                    name="get_machine_status",
                    description="Get machine status.",
                ),
                StructuredTool.from_function(
                    coroutine=search_documentation,
                    name="search_documentation",
                    description="Search technical documentation.",
                ),
            ),
            discovered_tool_names=("get_machine_status", "search_documentation"),
            server_name="fake_factory_and_knowledge_mcp",
            server_version="test",
            protocol_version="test",
            tool_policies=(
                ToolPolicy("get_machine_status", ToolOperation.READ),
                ToolPolicy("search_documentation", ToolOperation.READ),
            ),
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


def test_final_agent_output_bounds_typed_references() -> None:
    output = FinalAgentOutput.model_validate(
        {
            "answer": "S04 reports QUALITY-09 for P4711.",
            "identifiers": [
                {"value": "S04", "type": "station"},
                {"value": "QUALITY-09", "type": "error_code"},
            ],
            "documents": [
                {
                    "document_id": "s04-quality-procedure",
                    "title": "S04 Quality Procedure",
                    "format": "markdown",
                }
            ],
        }
    )

    assert [reference.value for reference in output.identifiers] == [
        "S04",
        "QUALITY-09",
    ]
    assert output.documents[0].document_id == "s04-quality-procedure"


def test_document_references_use_catalog_titles_and_deduplicate_by_document_id() -> (
    None
):
    documents = _document_references_from_observation(
        """{
          "results": [
            {
              "document_id": "DOC-001",
              "metadata": {
                "title": "Document",
                "document_title": "S04 QUALITY-09 Troubleshooting Procedure",
                "mime_type": "application/pdf"
              }
            },
            {
              "document_id": "DOC-002",
              "metadata": {
                "title": "Quality Inspection Workflow",
                "format": "markdown"
              }
            },
            {
              "document_id": "DOC-001",
              "metadata": {
                "title": "Document",
                "document_title": "S04 QUALITY-09 Troubleshooting Procedure",
                "mime_type": "application/pdf"
              }
            }
          ]
        }"""
    )

    references = _deduplicate_document_references(documents)

    assert [
        (reference.document_id, reference.title, reference.format)
        for reference in references
    ] == [
        (
            "DOC-001",
            "S04 QUALITY-09 Troubleshooting Procedure",
            "application/pdf",
        ),
        ("DOC-002", "Quality Inspection Workflow", "markdown"),
    ]
    assert all(reference.title != "Document" for reference in references)


def test_document_reference_without_authorized_name_uses_document_id_fallback() -> None:
    references = _document_references_from_observation(
        '{"results":[{"document_id":"DOC-003","metadata":{"format":"markdown"}}]}'
    )

    assert [
        (reference.document_id, reference.title, reference.format)
        for reference in references
    ] == [("DOC-003", "Document DOC-003", "markdown")]


def test_document_reference_compacts_an_overlong_known_mime_type() -> None:
    references = _document_references_from_observation(
        """{
          "results": [
            {
              "document_id": "DOC-004",
              "metadata": {
                "document_title": "S04 QUALITY-09 Troubleshooting Procedure",
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              }
            }
          ]
        }"""
    )

    assert [
        (reference.document_id, reference.title, reference.format)
        for reference in references
    ] == [("DOC-004", "S04 QUALITY-09 Troubleshooting Procedure", "docx")]


def test_model_prompt_does_not_ask_for_a_json_pseudo_tool_call() -> None:
    assert (
        "return only the configured JSON object"
        not in MCP_TROUBLESHOOTING_SYSTEM_MESSAGE
    )
    assert "return narrative Markdown only; do not emit JSON" in (
        MCP_TROUBLESHOOTING_SYSTEM_MESSAGE
    )
    assert "Copy technical identifiers exactly" in MCP_TROUBLESHOOTING_SYSTEM_MESSAGE


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
    assert [
        (reference.value, reference.type.value) for reference in result.identifiers
    ] == [
        ("P4711", "product"),
        ("S04", "station"),
    ]
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


def test_unsupported_profile_uses_safe_narrative_for_reserved_action_sections() -> None:
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

    result = asyncio.run(agent.aanswer_via_mcp("Investigate P4711 at S04."))

    assert result.status is AgentRunStatus.SUCCESS
    assert result.final_answer == "The authorized check is complete."


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


@pytest.mark.parametrize("finalizer_text", (None, ""))
def test_structured_finalizer_retains_valid_draft_when_provider_returns_no_text(
    finalizer_text: str | None,
) -> None:
    client = FakeLLMClient(
        responses=[
            LLMResponse(
                text="The investigation is complete and no additional checks are useful.",
                finish_reason=FinishReason.STOP,
            ),
            LLMResponse(text=finalizer_text, finish_reason=FinishReason.STOP),
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

    assert result.final_answer == (
        "The investigation is complete and no additional checks are useful."
    )
    assert result.next_steps == ()
    assert result.investigation_steps == ()


@pytest.mark.parametrize(
    "invalid_finalizer_text",
    (
        "{",
        '{"answer":42}',
        '{"answer":"Summary","unexpected":true}',
    ),
)
def test_structured_finalizer_retains_valid_draft_when_provider_returns_invalid_shape(
    invalid_finalizer_text: str,
) -> None:
    draft = "S04 reports QUALITY-09."
    client = FakeLLMClient(
        responses=[
            LLMResponse(text=draft, finish_reason=FinishReason.STOP),
            LLMResponse(text=invalid_finalizer_text, finish_reason=FinishReason.STOP),
        ]
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(
            client, ModelProfile("local_quality"), supports_structured_output=True
        ),
        mcp_tool_provider=cast(McpToolProvider, ReadRecordingMcpToolProvider()),
        run_classification=DataClassification.CONFIDENTIAL,
    )

    result = asyncio.run(agent.aanswer_via_mcp("Investigate QUALITY-09 at S04."))

    assert result.final_answer == draft
    assert result.next_steps == ()
    assert result.investigation_steps == ()
    assert '{"answer"' not in (result.final_answer or "")


def test_structured_finalizer_unwraps_one_valid_nested_contract() -> None:
    nested = (
        '{"answer":"{\\"answer\\":\\"S04 reports QUALITY-09.\\",'
        '\\"next_steps\\":[\\"Check station S04.\\"]}",'
        '"next_steps":[]}'
    )
    client = FakeLLMClient(
        responses=[
            LLMResponse(
                text="S04 reports QUALITY-09.", finish_reason=FinishReason.STOP
            ),
            LLMResponse(text=nested, finish_reason=FinishReason.STOP),
        ]
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(
            client, ModelProfile("local_quality"), supports_structured_output=True
        ),
        mcp_tool_provider=cast(McpToolProvider, ReadRecordingMcpToolProvider()),
        run_classification=DataClassification.CONFIDENTIAL,
    )

    result = asyncio.run(agent.aanswer_via_mcp("Investigate QUALITY-09 at S04."))

    assert result.final_answer == "S04 reports QUALITY-09."
    assert result.next_steps == ("Check station S04.",)


def test_invalid_structured_finalizer_keeps_system_derived_references() -> None:
    client = FakeLLMClient(
        responses=[
            LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="documentation",
                        name="search_documentation",
                        arguments={"query": "QUALITY-09 S04"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            LLMResponse(
                text="S04 reports QUALITY-09.", finish_reason=FinishReason.STOP
            ),
            LLMResponse(text='{"answer":42}', finish_reason=FinishReason.STOP),
        ]
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(
            client, ModelProfile("local_quality"), supports_structured_output=True
        ),
        mcp_tool_provider=cast(
            McpToolProvider, DocumentationRecordingMcpToolProvider()
        ),
        run_classification=DataClassification.CONFIDENTIAL,
    )

    result = asyncio.run(agent.aanswer_via_mcp("Investigate QUALITY-09 at S04."))

    assert result.final_answer == "S04 reports QUALITY-09."
    assert [(step.step, step.action) for step in result.investigation_steps] == [
        (1, "search_documentation")
    ]
    assert {reference.value for reference in result.identifiers} >= {
        "QUALITY-09",
        "S04",
    }
    assert [
        (reference.document_id, reference.title, reference.format)
        for reference in result.documents
    ] == [("DOC-QUALITY-09", "S04 QUALITY-09 Troubleshooting Procedure", "markdown")]


def test_three_turn_follow_up_keeps_tool_trajectory_and_references_per_run() -> None:
    provider = cast(McpToolProvider, ThreeTurnMcpToolProvider())

    def run_agent(
        responses: list[LLMResponse],
        request: str,
        context: tuple[ConversationTurn, ...] = (),
        *,
        supports_structured_output: bool = True,
    ) -> AgentRunResult:
        agent = LangGraphTroubleshootingAgent(
            LLMClientChatModel(
                FakeLLMClient(responses),
                ModelProfile("local_quality"),
                supports_structured_output=supports_structured_output,
            ),
            mcp_tool_provider=provider,
            run_classification=DataClassification.CONFIDENTIAL,
        )
        return asyncio.run(
            agent.aanswer_via_mcp(
                request,
                response_language=ResponseLanguage.EN,
                conversation_context=context,
            )
        )

    first = run_agent(
        [
            LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="status-1",
                        name="get_machine_status",
                        arguments={"station_id": "S04"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            LLMResponse(text="S04 was checked.", finish_reason=FinishReason.STOP),
            LLMResponse(
                text='{"answer":"S04 was checked.","next_steps":[]}',
                finish_reason=FinishReason.STOP,
            ),
        ],
        "Status S04.",
    )
    second = run_agent(
        [
            LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="documentation-2",
                        name="search_documentation",
                        arguments={"query": "QUALITY-09"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            LLMResponse(
                text="QUALITY-09 documentation was checked.",
                finish_reason=FinishReason.STOP,
            ),
            LLMResponse(
                text=(
                    '{"answer":"QUALITY-09 documentation was checked.","next_steps":[]}'
                ),
                finish_reason=FinishReason.STOP,
            ),
        ],
        "Investigate QUALITY-09 in more detail.",
        (ConversationTurn("Status S04.", first.final_answer),),
    )
    third = run_agent(
        [
            LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="status-3",
                        name="get_machine_status",
                        arguments={"station_id": "S04"},
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            LLMResponse(
                text="S04 was checked.\n\n### Next Steps\n\n- Check station S04.",
                finish_reason=FinishReason.STOP,
            ),
        ],
        "Check the current status of station S04.",
        (
            ConversationTurn("Status S04.", first.final_answer),
            ConversationTurn(
                "Investigate QUALITY-09 in more detail.", second.final_answer
            ),
        ),
        supports_structured_output=False,
    )

    assert [result.status for result in (first, second, third)] == [
        AgentRunStatus.SUCCESS,
        AgentRunStatus.SUCCESS,
        AgentRunStatus.SUCCESS,
    ]
    assert [call.tool for call in third.executed_tool_calls] == ["get_machine_status"]
    assert third.tool_call_count == 1
    assert third.final_answer == "The authorized check is complete."
    assert third.documents == ()
    assert {reference.value for reference in third.identifiers} == {"S04"}


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
