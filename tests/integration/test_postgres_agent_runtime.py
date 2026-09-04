"""Live PostgreSQL coverage for durable agent runs and LangGraph checkpoints."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from industrial_ai_agent.agent.agent_run import AgentRunResult, AgentRunStatus
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
from industrial_ai_agent.agent.model_egress import DataClassification
from industrial_ai_agent.domain.security import SecurityContext
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.api.schemas import RunStatus
from industrial_ai_agent.infrastructure.in_memory_maintenance_ticket_repository import (
    InMemoryMaintenanceTicketRepository,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.persistence.langgraph_checkpointer import (
    open_langgraph_postgres_checkpointer,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability

DATABASE_URL = os.getenv("FACTORY_DATABASE_URL")
DEFAULT_PROFILE = ModelProfile("local_quality")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="requires FACTORY_DATABASE_URL for the local PostgreSQL integration service",
)


@dataclass
class FakeLLMClient:
    responses: list[LLMResponse]

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        del profile, request
        if not self.responses:
            raise AssertionError("Unexpected LLM call")
        return self.responses.pop(0)


class FixedRunService:
    async def run(self, message: str) -> AgentRunResult:
        del message
        return _result()


def _context(clearance: DataClassification) -> SecurityContext:
    return SecurityContext(
        subject_id=f"agent-runtime-{clearance.name.lower()}",
        roles=("test-engineer",),
        clearance=clearance,
        authenticated=False,
    )


def _result() -> AgentRunResult:
    return AgentRunResult(
        status=AgentRunStatus.SUCCESS,
        final_answer="Persisted diagnosis.",
        tool_call_count=1,
        executed_tool_calls=(
            {"tool": "get_product_history", "arguments": {"product_id": "P4711"}},
        ),
        model_profile_name="local_quality",
    )


def test_agent_run_store_survives_store_recreation_and_rls() -> None:
    assert DATABASE_URL is not None
    run_id = uuid4()

    first_factory = PostgreSqlSessionFactory(DATABASE_URL)
    first_store = PostgreSqlAgentRunStore(
        first_factory, _context(DataClassification.CONFIDENTIAL)
    )
    try:
        asyncio.run(
            first_store.create(
                run_id,
                request_text="Investigate P4711.",
                data_classification=DataClassification.CONFIDENTIAL,
            )
        )
        asyncio.run(
            first_store.bind_execution_context(
                run_id,
                data_classification=DataClassification.CONFIDENTIAL,
                model_profile="local_quality",
            )
        )
        completed = asyncio.run(first_store.complete(run_id, _result()))
    finally:
        first_factory.dispose()

    second_factory = PostgreSqlSessionFactory(DATABASE_URL)
    try:
        second_store = PostgreSqlAgentRunStore(
            second_factory, _context(DataClassification.CONFIDENTIAL)
        )
        restored = asyncio.run(second_store.get(run_id))
        public_store = PostgreSqlAgentRunStore(
            second_factory, _context(DataClassification.PUBLIC)
        )
        hidden_from_public = asyncio.run(public_store.get(run_id))
    finally:
        second_factory.dispose()

    assert completed.status is RunStatus.SUCCESS
    assert restored is not None
    assert restored.thread_id == run_id
    assert restored.request_text == "Investigate P4711."
    assert restored.data_classification is DataClassification.CONFIDENTIAL
    assert restored.model_profile == "local_quality"
    assert restored.result == _result()
    assert hidden_from_public is None


def test_agent_runtime_rls_and_framework_checkpoint_schema_exist() -> None:
    assert DATABASE_URL is not None
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    try:
        with factory.connection(
            _context(DataClassification.CONFIDENTIAL)
        ) as connection:
            rls_enabled = connection.execute(
                text(
                    "SELECT relrowsecurity AND relforcerowsecurity "
                    "FROM pg_class WHERE oid = 'agent_runtime.agent_runs'::regclass"
                )
            ).scalar_one()
            bypass_rls = connection.execute(
                text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).scalar_one()
    finally:
        factory.dispose()

    assert rls_enabled is True
    assert bypass_rls is False


def test_agent_runtime_rls_filters_each_clearance_level() -> None:
    assert DATABASE_URL is not None
    run_ids = {classification: uuid4() for classification in DataClassification}
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    try:
        for classification, run_id in run_ids.items():
            store = PostgreSqlAgentRunStore(factory, _context(classification))
            asyncio.run(
                store.create(
                    run_id,
                    request_text=f"{classification.name} run",
                    data_classification=classification,
                )
            )
        visible_counts: dict[DataClassification, int] = {}
        for clearance in DataClassification:
            with factory.connection(_context(clearance)) as connection:
                visible_counts[clearance] = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM agent_runtime.agent_runs "
                            "WHERE run_id = ANY(:run_ids)"
                        ),
                        {"run_ids": list(run_ids.values())},
                    ).scalar_one()
                )
    finally:
        factory.dispose()

    assert visible_counts == {
        DataClassification.PUBLIC: 1,
        DataClassification.INTERNAL: 2,
        DataClassification.CONFIDENTIAL: 3,
        DataClassification.RESTRICTED: 4,
    }


def test_fastapi_run_survives_application_recreation() -> None:
    assert DATABASE_URL is not None
    first_factory = PostgreSqlSessionFactory(DATABASE_URL)
    try:
        first_app = create_app(
            FixedRunService(),
            run_store=PostgreSqlAgentRunStore(
                first_factory, _context(DataClassification.CONFIDENTIAL)
            ),
        )
        created = TestClient(first_app).post(
            "/api/v1/runs", json={"message": "Investigate P4711."}
        )
    finally:
        first_factory.dispose()

    run_id = created.json()["run_id"]
    second_factory = PostgreSqlSessionFactory(DATABASE_URL)
    try:
        second_app = create_app(
            FixedRunService(),
            run_store=PostgreSqlAgentRunStore(
                second_factory, _context(DataClassification.CONFIDENTIAL)
            ),
        )
        restored = TestClient(second_app).get(f"/api/v1/runs/{run_id}")
    finally:
        second_factory.dispose()

    assert created.status_code == 200
    assert restored.status_code == 200
    assert restored.json() == created.json()


def test_postgres_checkpoint_survives_restart_approve_and_repeat() -> None:
    _run_async(_checkpoint_restart_scenario("approve"))


def test_postgres_checkpoint_survives_restart_reject() -> None:
    _run_async(_checkpoint_restart_scenario("reject"))


def test_postgres_checkpoint_rejects_profile_and_classification_downgrade() -> None:
    _run_async(_checkpoint_context_mismatch_scenario())


def _run_async(awaitable: object) -> None:
    """Use psycopg's Windows-compatible event loop for local integration coverage."""
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(awaitable)
        return
    asyncio.run(awaitable)


async def _checkpoint_restart_scenario(approval: str) -> None:
    assert DATABASE_URL is not None
    thread_id = str(uuid4())
    ticket_repository = InMemoryMaintenanceTicketRepository()

    async with open_langgraph_postgres_checkpointer(DATABASE_URL) as first_saver:
        first_agent = _agent(
            first_saver,
            FakeLLMClient([_action_response()]),
            ticket_repository,
        )
        paused = await first_agent.astart(
            "Create a maintenance ticket for S04.", thread_id=thread_id
        )
        assert paused["pending_action"] is not None
        assert paused["run_status"] is None
        assert ticket_repository.tickets == ()

    async with open_langgraph_postgres_checkpointer(DATABASE_URL) as second_saver:
        second_agent = _agent(
            second_saver,
            FakeLLMClient([_final_response("Ticket flow completed.")]),
            ticket_repository,
        )
        completed = await second_agent.aresume(thread_id=thread_id, approval=approval)
        assert completed["run_status"] is AgentRunStatus.SUCCESS
        if approval == "approve":
            assert len(ticket_repository.tickets) == 1
            repeated = await second_agent.aresume(
                thread_id=thread_id, approval="approve"
            )
            assert repeated["run_status"] is AgentRunStatus.SUCCESS
            assert len(ticket_repository.tickets) == 1
        else:
            assert ticket_repository.tickets == ()


async def _checkpoint_context_mismatch_scenario() -> None:
    assert DATABASE_URL is not None
    thread_id = str(uuid4())
    tickets = InMemoryMaintenanceTicketRepository()
    async with open_langgraph_postgres_checkpointer(DATABASE_URL) as first_saver:
        await _agent(
            first_saver,
            FakeLLMClient([_action_response()]),
            tickets,
        ).astart("Create a maintenance ticket for S04.", thread_id=thread_id)

    async with open_langgraph_postgres_checkpointer(DATABASE_URL) as second_saver:
        profile_mismatch = _agent(
            second_saver,
            FakeLLMClient([_final_response("Unexpected")]),
            tickets,
            profile=ModelProfile("public_fast"),
        )
        with pytest.raises(RuntimeError, match="model profile does not match"):
            await profile_mismatch.aresume(thread_id=thread_id, approval="approve")

        classification_mismatch = _agent(
            second_saver,
            FakeLLMClient([_final_response("Unexpected")]),
            tickets,
            classification=DataClassification.PUBLIC,
        )
        with pytest.raises(RuntimeError, match="data classification does not match"):
            await classification_mismatch.aresume(
                thread_id=thread_id, approval="approve"
            )

    assert tickets.tickets == ()


def _agent(
    checkpointer,
    client: FakeLLMClient,
    ticket_repository: InMemoryMaintenanceTicketRepository,
    *,
    profile: ModelProfile = DEFAULT_PROFILE,
    classification: DataClassification = DataClassification.CONFIDENTIAL,
) -> LangGraphTroubleshootingAgent:
    return LangGraphTroubleshootingAgent(
        LLMClientChatModel(client, profile),
        maintenance_ticket=MaintenanceTicketCapability(ticket_repository),
        checkpointer=checkpointer,
        run_classification=classification,
    )


def _action_response() -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=(
            LLMToolCall(
                id="persistent-ticket-call",
                name=CREATE_MAINTENANCE_TICKET_TOOL_NAME,
                arguments={"station_id": "S04", "summary": "Investigate E-STOP-17"},
            ),
        ),
        finish_reason=FinishReason.TOOL_CALLS,
    )


def _final_response(text: str) -> LLMResponse:
    return LLMResponse(text=text, finish_reason=FinishReason.STOP)
