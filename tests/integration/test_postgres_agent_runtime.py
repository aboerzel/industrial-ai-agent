"""Live PostgreSQL coverage for durable agent runs and LangGraph checkpoints."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from industrial_ai_agent.agent.agent_run import (
    AgentRunResult,
    AgentRunStatus,
    InvestigationStep,
)
from industrial_ai_agent.agent.model_egress import DataClassification
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunProfile,
    InternalDiagnosticTarget,
)
from industrial_ai_agent.domain.security import SecurityContext
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
    _safe_tool_names,
)
from industrial_ai_agent.infrastructure.api.schemas import RunStatus
from industrial_ai_agent.infrastructure.internal_diagnostic_scope import (
    PostgreSqlInternalDiagnosticScopeValidator,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)

DATABASE_URL = os.getenv("FACTORY_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="requires FACTORY_DATABASE_URL for the local PostgreSQL integration service",
)


class FixedRunService:
    async def run(self, message: str) -> AgentRunResult:
        del message
        return _result()

    async def run_with_policy(self, message: str, **_: object) -> AgentRunResult:
        return await self.run(message)


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
        investigation_steps=(
            InvestigationStep(
                step=1,
                action="get_product_history",
                finding="P4711 has a recorded failure at S04.",
            ),
        ),
        next_steps=("Check station S04.", "Search documentation for QUALITY-09."),
        tool_call_count=1,
        executed_tool_calls=(
            {"tool": "get_product_history", "arguments": {"product_id": "P4711"}},
        ),
        model_profile_name="local_quality",
    )


def test_runtime_projection_retains_discovery_tool_names_only() -> None:
    assert _safe_tool_names(
        [
            {"tool": "list_stations"},
            {"tool": "get_product_overview"},
            {"tool": "unknown_tool"},
        ]
    ) == ("list_stations", "get_product_overview")


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
                run_profile=AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING,
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
    assert restored.result.next_steps == (
        "Check station S04.",
        "Search documentation for QUALITY-09.",
    )
    assert restored.result.investigation_steps == (
        InvestigationStep(
            step=1,
            action="get_product_history",
            finding="P4711 has a recorded failure at S04.",
        ),
    )
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


def test_internal_diagnostic_preflight_uses_internal_rls_before_agent_execution() -> (
    None
):
    assert DATABASE_URL is not None
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    validator = PostgreSqlInternalDiagnosticScopeValidator(factory)
    try:
        internal_target = asyncio.run(
            validator.is_available(
                InternalDiagnosticTarget(product_id="P4900", station_id="S02")
            )
        )
        confidential_target = asyncio.run(
            validator.is_available(
                InternalDiagnosticTarget(product_id="P4711", station_id="S04")
            )
        )
    finally:
        factory.dispose()

    assert internal_target is True
    assert confidential_target is False


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
            "/api/v1/runs",
            json={
                "message": "Investigate P4711.",
                "user_clearance": "CONFIDENTIAL",
            },
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
