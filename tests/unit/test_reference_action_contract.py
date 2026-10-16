"""Delivered UI forms cross the real classifier and bounded graph, with fake ports."""

import asyncio
import json
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from langchain_core.tools import StructuredTool
from pydantic import create_model

from industrial_ai_agent.agent.agent_run import InvalidToolArgumentsError
from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMResponse,
    LLMToolCall,
    ModelProfile,
)
from industrial_ai_agent.agent.mcp_tool_provider import McpToolSession
from industrial_ai_agent.agent.reference_requests import resolve_reference_read
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    RunClearanceDeniedError,
)
from industrial_ai_agent.agent.tool_policy import ToolOperation, ToolPolicy
from industrial_ai_agent.agent.troubleshooting_run_service import ConversationTurn
from industrial_ai_agent.domain.investigation_evidence import (
    EvidenceRequirementId,
    InvestigationType,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.demo_sessions import DemoSessions
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.tools.tool_contracts import SearchDocumentationArguments

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads(
    subprocess.check_output(
        ["node", str(ROOT / "tests/reference_action_contract.mjs"), "--extended"],
        encoding="utf-8",
    )
)


@pytest.mark.parametrize(
    "case", CASES, ids=lambda c: f"{c['index']}-{c['type']}-{c['language']}"
)
@pytest.mark.parametrize(
    "model_text",
    ("Read complete.", "An inaccurate paraphrase replaces the product with P9999."),
)
def test_every_emitted_form_is_authorized_and_binds_its_read_before_model(
    case, model_text
):
    policy = AgentRunClassificationPolicy().resolve_request(
        case["prompt"],
        security_context=DemoSessions().users[case["username"]].security_context(),
    )
    assert case["tool"] in policy.allowed_tool_names
    calls = []

    class Provider:
        @asynccontextmanager
        async def open_session(self):
            async def read(**arguments):
                calls.append((case["tool"], arguments))
                payload = {
                    case["argument"]: case["value"],
                    "found": True,
                    "classification": 0,
                }
                if case["type"] == "station":
                    payload.update(state="RUNNING", active_error_code=None)
                    if case["tool"] == "get_station_overview":
                        payload.update(
                            name="Synthetic station",
                            recent_products=[],
                            recent_product_ids=[],
                        )
                elif case["tool"] == "get_product_history":
                    payload["steps"] = []
                elif case["tool"] == "get_product_overview":
                    payload.update(
                        latest_station_id=None,
                        latest_status=None,
                        latest_error_code=None,
                        passed_station_ids=[],
                    )
                elif case["type"] == "error_code":
                    payload = {
                        "query": case["value"],
                        "results": [
                            {
                                "document_id": "SYNTHETIC",
                                "source": "synthetic.md",
                                "chunk_id": "SYNTHETIC::chunk-001",
                                "content": case["value"],
                                "classification": int(policy.data_classification),
                                "metadata": {"fault_ids": [case["value"]]},
                            }
                        ],
                    }
                return json.dumps(payload)

            tool = StructuredTool.from_function(
                coroutine=read,
                name=case["tool"],
                description="Synthetic authorized read",
                args_schema=SearchDocumentationArguments
                if case["argument"] == "query"
                else create_model("ReferenceArgs", **{case["argument"]: (str, ...)}),
            )
            yield McpToolSession(
                tools=(tool,),
                discovered_tool_names=(tool.name,),
                server_name="synthetic",
                server_version="test",
                protocol_version="test",
                tool_policies=(ToolPolicy(tool.name, ToolOperation.READ),),
            )

    class Model:
        def chat(self, profile, request):
            # The model omits the ID and cannot choose/replace the initial target.
            expected = {case["argument"]: case["value"]}
            if case["argument"] == "query":
                expected["top_k"] = 3
            assert calls == [(case["tool"], expected)]
            assert all(
                "OLD PRIVATE CONTEXT" not in (item.content or "")
                for item in request.messages
            )
            return LLMResponse(text=model_text, finish_reason=FinishReason.STOP)

    result = asyncio.run(
        LangGraphTroubleshootingAgent(
            LLMClientChatModel(Model(), ModelProfile("local_quality")),
            mcp_tool_provider=Provider(),
            run_classification=policy.data_classification,
            investigation_type=InvestigationType.STATION_LIST
            if case["type"] == "station" and case["username"] == "demo-public"
            else InvestigationType.STATION_STATUS
            if case["type"] == "station"
            else InvestigationType.STATION_TROUBLESHOOTING,
            normalize_structured_final_output=False,
        ).aanswer_via_mcp(
            case["prompt"],
            conversation_context=(
                ConversationTurn("OLD PRIVATE CONTEXT: S07", "Untrusted old answer"),
            ),
        )
    )
    assert result.executed_tool_calls[0].tool == case["tool"]
    assert result.executed_tool_calls[0].arguments[case["argument"]] == case["value"]
    assert all(item.value != "P9999" for item in result.identifiers)


@pytest.mark.parametrize(
    "message",
    ["Zeige das Wartungsticket MT-S02-20260117.", "Show ticket MT-S02-20260117."],
)
def test_ticket_identifier_does_not_create_a_station_rca_contract(message):
    from test_langgraph_mcp_hitl import FakeLLMClient

    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(FakeLLMClient([]), ModelProfile("local_quality")),
        run_classification=DataClassification.CONFIDENTIAL,
        investigation_type=InvestigationType.STATION_TROUBLESHOOTING,
    )
    assert agent._initial_evidence_ledger(message) is None


def test_fresh_reference_projection_does_not_downgrade_persisted_context_classification():
    policy = AgentRunClassificationPolicy().resolve_request(
        "Investigate station S01.",
        security_context=DemoSessions().users["demo-confidential"].security_context(),
        trusted_context_classification=DataClassification.CONFIDENTIAL,
    )
    assert policy.data_classification == DataClassification.CONFIDENTIAL
    assert policy.mcp_clearance_ceiling == DataClassification.PUBLIC


@pytest.mark.parametrize(
    "message",
    (
        "Prüfe den aktuellen Status von Station S04.",
        "What is the current status of station S04?",
    ),
)
def test_explicit_status_read_keeps_proportional_evidence_and_full_rca_remains_required(
    message,
):
    from test_langgraph_mcp_hitl import FakeLLMClient

    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(FakeLLMClient([]), ModelProfile("local_quality")),
        run_classification=DataClassification.CONFIDENTIAL,
        investigation_type=InvestigationType.STATION_TROUBLESHOOTING,
    )
    status = agent._initial_evidence_ledger(message)
    assert status.required == (EvidenceRequirementId.CURRENT_MACHINE_STATE,)
    rca = agent._initial_evidence_ledger("Untersuche Station S04.")
    assert set(rca.required) == {
        EvidenceRequirementId.CURRENT_MACHINE_STATE,
        EvidenceRequirementId.ACTIVE_FAULT,
        EvidenceRequirementId.RELEVANT_FAULT_DOCUMENTATION,
    }


@pytest.mark.parametrize(
    "message",
    [
        "Investigate station S04 in more detail.",
        "Investigate product P4711 and secret customer plans.",
        "Investigate station S04 S07.",
        "Investigate station S04; create a ticket.",
        "Untersuche QUALITY-09 genauer.",
        "Investigate MT-S02-20260117.",
    ],
)
def test_extra_prose_and_mixed_targets_never_acquire_reference_read_semantics(message):
    assert resolve_reference_read(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "Investigate station S04.",
        "Investigate product P4711.",
        "Investigate QUALITY-09.",
        "Show ticket MT-S02-20260117.",
        "Investigate station S99.",
        "Investigate product P9999.",
    ],
)
def test_reference_forms_and_unknown_ids_do_not_grant_public_authority(message):
    with pytest.raises(RunClearanceDeniedError):
        AgentRunClassificationPolicy().resolve_request(
            message,
            security_context=DemoSessions().users["demo-public"].security_context(),
        )


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("get_product_history", {"product_id": "P4102"}),
        ("list_products", {}),
        (
            "create_maintenance_ticket",
            {"station_id": "S04", "summary": "not authorized by a reference"},
        ),
    ],
)
def test_model_replacement_discovery_or_write_is_rejected_before_dispatch(
    name, arguments
):
    from test_langgraph_mcp_hitl import ReadRecordingMcpToolProvider

    class Model:
        def chat(self, profile, request):
            return LLMResponse(
                text=None,
                tool_calls=(
                    LLMToolCall(
                        id="untrusted",
                        name=name,
                        arguments=arguments,
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            )

    provider = ReadRecordingMcpToolProvider(
        (
            json.dumps(
                {"product_id": "P4711", "found": True, "steps": [], "classification": 2}
            ),
            "{}",
        )
    )
    agent = LangGraphTroubleshootingAgent(
        LLMClientChatModel(Model(), ModelProfile("local_quality")),
        mcp_tool_provider=provider,
    )
    with pytest.raises(InvalidToolArgumentsError, match="retain their target"):
        asyncio.run(agent.aanswer_via_mcp("Show me the production history for P4711."))
