"""Real PostgreSQL FastAPI -> LangGraph -> MCP HITL restart coverage."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from threading import Lock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from mcp.client.stdio import StdioServerParameters
from sqlalchemy import select

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    CREATE_MAINTENANCE_TICKET_TOOL_NAME,
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    ModelProfile,
)
from industrial_ai_agent.agent.model_egress import DataClassification, ExecutionZone
from industrial_ai_agent.agent.model_routing import (
    CostClass,
    DeterministicModelRouter,
    LLMCapability,
    ModelProfileMetadata,
    QualityClass,
)
from industrial_ai_agent.agent.troubleshooting_run_service import (
    McpBackedTroubleshootingAgent,
    RoutedTroubleshootingAgentFactory,
    TroubleshootingRunService,
)
from industrial_ai_agent.domain.security import SecurityContext
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    DEFAULT_ALLOWED_FACTORY_TOOLS,
    DEFAULT_ALLOWED_KNOWLEDGE_TOOLS,
    McpLangChainToolProvider,
    McpServerConfiguration,
)
from industrial_ai_agent.infrastructure.persistence.langgraph_checkpointer import (
    PostgreSqlCheckpointerFactory,
)
from industrial_ai_agent.infrastructure.persistence.models import (
    MaintenanceTicketRecord,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)

DATABASE_URL = os.getenv("FACTORY_DATABASE_URL")
PROFILE = ModelProfile("local_quality")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="requires FACTORY_DATABASE_URL for the local PostgreSQL integration service",
)


@pytest.fixture(scope="module", autouse=True)
def _windows_selector_event_loop_policy() -> Iterator[None]:
    """Limit the PostgreSQL test-loop workaround to this module."""
    if sys.platform != "win32":
        yield
        return
    previous_policy = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        yield
    finally:
        asyncio.set_event_loop_policy(previous_policy)


_KNOWLEDGE_SERVER_SOURCE = """
from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.infrastructure.knowledge_mcp_server import create_knowledge_mcp_server
from industrial_ai_agent.tools.documentation_search import DocumentationSearchCapability
class Retriever:
    def search(self, query, limit):
        return (KnowledgeRetrievalResult(content='QUALITY-09 requires maintenance review.', document_id='maintenance', source='maintenance.md', chunk_id='maintenance::1', relevance_score=1.0, metadata={'title':'Maintenance'}),)[:limit]
create_knowledge_mcp_server(documentation_search=DocumentationSearchCapability(Retriever())).run(transport='stdio')
"""


@dataclass
class FakeLLMClient:
    responses: list[LLMResponse]
    requests: list[LLMRequest]

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        assert profile == PROFILE
        self.requests.append(request)
        return self.responses.pop(0)


class SequentialAgentFactory(RoutedTroubleshootingAgentFactory):
    def __init__(self) -> None:
        self._opens = 0
        self._lock = Lock()
        self.clients: list[FakeLLMClient] = []
        self.ticket_request_ids: list[str] = []
        self._provider = McpLangChainToolProvider(
            (
                McpServerConfiguration(
                    server_id="factory",
                    transport=StdioServerParameters(
                        command=sys.executable,
                        args=[
                            "-m",
                            "industrial_ai_agent.infrastructure.factory_mcp_server",
                        ],
                        env={"FACTORY_DATABASE_URL": DATABASE_URL or ""},
                    ),
                    allowed_tool_names=DEFAULT_ALLOWED_FACTORY_TOOLS,
                ),
                McpServerConfiguration(
                    server_id="knowledge",
                    transport=StdioServerParameters(
                        command=sys.executable,
                        args=["-c", _KNOWLEDGE_SERVER_SOURCE],
                    ),
                    allowed_tool_names=DEFAULT_ALLOWED_KNOWLEDGE_TOOLS,
                ),
            )
        )

    def open_agent(
        self,
        *,
        profile: ModelProfile,
        run_policy,
        checkpointer: object | None = None,
    ) -> AbstractContextManager[McpBackedTroubleshootingAgent]:
        assert run_policy.data_classification is DataClassification.CONFIDENTIAL
        with self._lock:
            self._opens += 1
            is_start = self._opens % 2 == 1
        responses = [_final_response()]
        if is_start:
            request_id = f"ticket-{uuid4().hex}"
            self.ticket_request_ids.append(request_id)
            responses = _start_responses(request_id)
        client = FakeLLMClient(responses, [])
        self.clients.append(client)
        return self._open(profile, client, checkpointer)

    @contextmanager
    def _open(
        self,
        profile: ModelProfile,
        client: FakeLLMClient,
        checkpointer: object | None,
    ) -> Iterator[McpBackedTroubleshootingAgent]:
        assert checkpointer is not None
        yield LangGraphTroubleshootingAgent(
            LLMClientChatModel(client, profile),
            mcp_tool_provider=self._provider,
            checkpointer=checkpointer,
            run_classification=DataClassification.CONFIDENTIAL,
        )


def _service(factory: SequentialAgentFactory) -> TroubleshootingRunService:
    assert DATABASE_URL is not None
    return TroubleshootingRunService(
        router=DeterministicModelRouter(),
        profiles=(
            ModelProfileMetadata(
                profile=PROFILE,
                capabilities=frozenset(
                    {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
                ),
                quality_class=QualityClass.HIGH,
                cost_class=CostClass.LOW,
                execution_zone=ExecutionZone.LOCAL,
                max_data_classification=DataClassification.RESTRICTED,
            ),
        ),
        agent_factory=factory,
        checkpointer_factory=PostgreSqlCheckpointerFactory(DATABASE_URL),
    )


def _application(
    factory: SequentialAgentFactory,
) -> tuple[TestClient, PostgreSqlSessionFactory]:
    assert DATABASE_URL is not None
    session_factory = PostgreSqlSessionFactory(DATABASE_URL)
    context = SecurityContext(
        subject_id="persistent-hitl-api-test",
        roles=("test-engineer",),
        clearance=DataClassification.CONFIDENTIAL,
        authenticated=False,
    )
    return (
        TestClient(
            create_app(
                _service(factory),
                run_store=PostgreSqlAgentRunStore(session_factory, context),
            )
        ),
        session_factory,
    )


def test_fastapi_hitl_approval_survives_full_runtime_recreation() -> None:
    factory = SequentialAgentFactory()
    first_client, first_sessions = _application(factory)
    try:
        started = first_client.post(
            "/api/v1/runs",
            json={
                "message": (
                    "Investigate the recurring quality problem for product P4711 at "
                    "station S04. Use factory and documentation information and "
                    "create a maintenance ticket if justified."
                ),
                "user_clearance": "CONFIDENTIAL",
            },
        )
    finally:
        first_client.close()
        first_sessions.dispose()

    assert started.status_code == 200
    waiting = started.json()
    assert waiting["status"] == "waiting_for_approval"
    assert waiting["approval_request"]["action"] == CREATE_MAINTENANCE_TICKET_TOOL_NAME
    assert waiting["approval_request"]["classification"] == "CONFIDENTIAL"
    assert waiting["approval_request"]["model_profile"] == "local_quality"
    run_id = UUID(waiting["run_id"])
    request_id = factory.ticket_request_ids[0]
    assert _ticket_count(request_id) == 0

    second_client, second_sessions = _application(factory)
    try:
        restored = second_client.get(f"/api/v1/runs/{run_id}")
        approved = second_client.post(
            f"/api/v1/runs/{run_id}/resume", json={"decision": "approve"}
        )
        duplicate = second_client.post(
            f"/api/v1/runs/{run_id}/resume", json={"decision": "approve"}
        )
    finally:
        second_client.close()
        second_sessions.dispose()

    assert restored.status_code == 200
    assert restored.json()["status"] == "waiting_for_approval"
    assert approved.status_code == 200
    assert approved.json()["status"] == "success"
    assert [call["tool"] for call in approved.json()["tool_calls"]] == [
        "get_product_history",
        "get_machine_status",
        "search_documentation",
        CREATE_MAINTENANCE_TICKET_TOOL_NAME,
    ]
    assert duplicate.status_code == 409
    assert _ticket_count(request_id) == 1

    third_client, third_sessions = _application(factory)
    try:
        persisted = third_client.get(f"/api/v1/runs/{run_id}")
    finally:
        third_client.close()
        third_sessions.dispose()

    assert persisted.status_code == 200
    assert persisted.json()["status"] == "success"
    assert persisted.json()["approval_request"] is None


def test_fastapi_hitl_reject_survives_runtime_recreation_without_ticket() -> None:
    factory = SequentialAgentFactory()
    first_client, first_sessions = _application(factory)
    try:
        started = first_client.post(
            "/api/v1/runs",
            json={"message": "Investigate S04.", "user_clearance": "CONFIDENTIAL"},
        )
    finally:
        first_client.close()
        first_sessions.dispose()

    assert started.status_code == 200
    run_id = UUID(started.json()["run_id"])
    request_id = factory.ticket_request_ids[0]

    second_client, second_sessions = _application(factory)
    try:
        rejected = second_client.post(
            f"/api/v1/runs/{run_id}/resume", json={"decision": "reject"}
        )
    finally:
        second_client.close()
        second_sessions.dispose()

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "success"
    assert _ticket_count(request_id) == 0

    third_client, third_sessions = _application(factory)
    try:
        persisted = third_client.get(f"/api/v1/runs/{run_id}")
    finally:
        third_client.close()
        third_sessions.dispose()

    assert persisted.status_code == 200
    assert persisted.json()["status"] == "success"
    assert persisted.json()["approval_request"] is None


def test_fastapi_hitl_concurrent_approvals_claim_one_postgres_resume() -> None:
    factory = SequentialAgentFactory()
    starter, starter_sessions = _application(factory)
    try:
        started = starter.post(
            "/api/v1/runs",
            json={"message": "Investigate S04.", "user_clearance": "CONFIDENTIAL"},
        )
    finally:
        starter.close()
        starter_sessions.dispose()

    assert started.status_code == 200
    run_id = UUID(started.json()["run_id"])
    request_id = factory.ticket_request_ids[0]

    def approve_once() -> int:
        client, sessions = _application(factory)
        try:
            return client.post(
                f"/api/v1/runs/{run_id}/resume", json={"decision": "approve"}
            ).status_code
        finally:
            client.close()
            sessions.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        status_codes = tuple(executor.map(lambda _: approve_once(), range(2)))

    assert sorted(status_codes) == [200, 409]
    assert _ticket_count(request_id) == 1


def test_fastapi_resume_contract_rejects_unknown_invalid_and_client_context() -> None:
    factory = SequentialAgentFactory()
    client, sessions = _application(factory)
    try:
        unknown = client.post(
            f"/api/v1/runs/{uuid4()}/resume", json={"decision": "approve"}
        )
        invalid = client.post(
            f"/api/v1/runs/{uuid4()}/resume", json={"decision": "later"}
        )
        manipulated = client.post(
            f"/api/v1/runs/{uuid4()}/resume",
            json={"decision": "approve", "model_profile": "public_fast"},
        )
    finally:
        client.close()
        sessions.dispose()

    assert unknown.status_code == 404
    assert invalid.status_code == 422
    assert manipulated.status_code == 422


def _ticket_count(request_id_fragment: str) -> int:
    assert DATABASE_URL is not None
    sessions = PostgreSqlSessionFactory(DATABASE_URL)
    context = SecurityContext(
        subject_id="persistent-hitl-ticket-check",
        roles=("test-engineer",),
        clearance=DataClassification.CONFIDENTIAL,
        authenticated=False,
    )
    try:
        with sessions.session(context) as session:
            return len(
                tuple(
                    session.scalars(
                        select(MaintenanceTicketRecord).where(
                            MaintenanceTicketRecord.request_id.contains(
                                request_id_fragment
                            )
                        )
                    )
                )
            )
    finally:
        sessions.dispose()


def _start_responses(ticket_request_id: str) -> list[LLMResponse]:
    return [
        _tool("get_product_history", {"product_id": "P4711"}, "history"),
        _tool("get_machine_status", {"station_id": "S04"}, "status"),
        _tool("search_documentation", {"query": "QUALITY-09 S04", "top_k": 1}, "docs"),
        _tool(
            CREATE_MAINTENANCE_TICKET_TOOL_NAME,
            {"station_id": "S04", "summary": "Inspect recurring QUALITY-09."},
            ticket_request_id,
        ),
    ]


def _tool(name: str, arguments: dict[str, object], call_id: str) -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=(LLMToolCall(id=call_id, name=name, arguments=arguments),),
        finish_reason=FinishReason.TOOL_CALLS,
    )


def _final_response() -> LLMResponse:
    return LLMResponse(
        text="Maintenance ticket created.", finish_reason=FinishReason.STOP
    )
