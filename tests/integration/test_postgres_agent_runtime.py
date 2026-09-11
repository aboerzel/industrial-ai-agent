"""Live PostgreSQL coverage for durable agent runs and LangGraph checkpoints."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from industrial_ai_agent.agent.agent_run import (
    AgentRunResult,
    AgentRunStatus,
    InvestigationStep,
)
from industrial_ai_agent.agent.model_egress import DataClassification
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    AgentRunProfile,
    InternalDiagnosticTarget,
)
from industrial_ai_agent.domain.closed_loop_recovery import RecoveryOutcome
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


def test_recovery_incomplete_run_persists_as_failed_with_its_bounded_code() -> None:
    assert DATABASE_URL is not None
    run_id = uuid4()
    result = AgentRunResult(
        status=AgentRunStatus.RECOVERY_INCOMPLETE,
        final_answer="The requested recovery was not completed.",
        investigation_steps=(
            InvestigationStep(
                step=1,
                action="get_position_reference_status",
                finding="The position reference is invalid.",
            ),
        ),
        tool_call_count=1,
        executed_tool_calls=(
            {
                "tool": "get_position_reference_status",
                "arguments": {"station_id": "S04"},
            },
        ),
        model_profile_name="nvidia_quality",
    )
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    store = PostgreSqlAgentRunStore(factory, _context(DataClassification.CONFIDENTIAL))
    try:
        asyncio.run(
            store.create(
                run_id,
                request_text="Synthetic recovery terminal-state test.",
                data_classification=DataClassification.CONFIDENTIAL,
                run_profile=AgentRunProfile.CONFIDENTIAL_RECOVERY,
            )
        )
        asyncio.run(
            store.bind_execution_context(
                run_id,
                data_classification=DataClassification.CONFIDENTIAL,
                run_profile=AgentRunProfile.CONFIDENTIAL_RECOVERY,
                model_profile="nvidia_quality",
            )
        )
        completed = asyncio.run(store.complete(run_id, result))
        restored = asyncio.run(store.get(run_id))
    finally:
        factory.dispose()

    assert completed.status is RunStatus.FAILED
    assert completed.error_code == "recovery_incomplete"
    assert restored is not None
    assert restored.status is RunStatus.FAILED
    assert restored.error_code == "recovery_incomplete"
    assert restored.result == result


def test_recovery_not_required_persists_as_successful_no_action_outcome() -> None:
    assert DATABASE_URL is not None
    run_id = uuid4()
    result = AgentRunResult(
        status=AgentRunStatus.SUCCESS,
        final_answer="No recovery is required.",
        recovery_outcome=RecoveryOutcome.NOT_REQUIRED,
        tool_call_count=1,
        executed_tool_calls=(
            {
                "tool": "get_position_reference_status",
                "arguments": {"station_id": "S04"},
            },
        ),
        model_profile_name="nvidia_quality",
    )
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    store = PostgreSqlAgentRunStore(factory, _context(DataClassification.CONFIDENTIAL))
    try:
        asyncio.run(
            store.create(
                run_id,
                request_text="Synthetic healthy recovery persistence test.",
                data_classification=DataClassification.CONFIDENTIAL,
                run_profile=AgentRunProfile.CONFIDENTIAL_RECOVERY,
            )
        )
        asyncio.run(
            store.bind_execution_context(
                run_id,
                data_classification=DataClassification.CONFIDENTIAL,
                run_profile=AgentRunProfile.CONFIDENTIAL_RECOVERY,
                model_profile="nvidia_quality",
            )
        )
        completed = asyncio.run(store.complete(run_id, result))
        restored = asyncio.run(store.get(run_id))
    finally:
        factory.dispose()

    assert completed.status is RunStatus.SUCCESS
    assert completed.error_code is None
    assert restored is not None
    assert restored.result == result


def test_confidential_recovery_approval_persists_reloads_and_claims_once() -> None:
    assert DATABASE_URL is not None
    run_id = uuid4()
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    store = PostgreSqlAgentRunStore(factory, _context(DataClassification.CONFIDENTIAL))
    try:
        created = asyncio.run(
            store.create(
                run_id,
                request_text="Synthetic recovery persistence test.",
                data_classification=DataClassification.CONFIDENTIAL,
                run_profile=AgentRunProfile.CONFIDENTIAL_RECOVERY,
            )
        )
        bound = asyncio.run(
            store.bind_execution_context(
                run_id,
                data_classification=DataClassification.CONFIDENTIAL,
                run_profile=AgentRunProfile.CONFIDENTIAL_RECOVERY,
                model_profile="nvidia_quality",
            )
        )
        asyncio.run(
            store.wait_for_approval(
                run_id,
                _reference_calibration_approval_request(),
            )
        )
        pending = asyncio.run(store.get(run_id))
        claimed = asyncio.run(store.claim_resume(run_id, decision="approve"))
        restored = asyncio.run(store.get(run_id))
        approval_claimed = asyncio.run(
            store.claim_reference_calibration_approval(
                run_id,
                action_id="reference-calibration-action-1",
                station_id="S04",
                device_id="POSITION-ENC-02",
            )
        )
        replay_claimed = asyncio.run(
            store.claim_reference_calibration_approval(
                run_id,
                action_id="reference-calibration-action-1",
                station_id="S04",
                device_id="POSITION-ENC-02",
            )
        )
    finally:
        factory.dispose()

    assert created.run_profile is AgentRunProfile.CONFIDENTIAL_RECOVERY
    assert bound.model_profile == "nvidia_quality"
    assert pending is not None
    assert pending.approval_action == "execute_reference_calibration"
    assert pending.approval_request == _reference_calibration_approval_request()
    assert claimed is not None
    assert claimed.run_profile is AgentRunProfile.CONFIDENTIAL_RECOVERY
    assert restored is not None
    assert restored.run_profile is AgentRunProfile.CONFIDENTIAL_RECOVERY
    assert approval_claimed is True
    assert replay_claimed is False


def test_agent_run_profile_constraint_accepts_known_profiles_and_rejects_unknown() -> (
    None
):
    assert DATABASE_URL is not None
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    try:
        for profile in AgentRunProfile:
            policy = AgentRunClassificationPolicy().resolve(profile)
            store = PostgreSqlAgentRunStore(
                factory, _context(policy.data_classification)
            )
            stored = asyncio.run(
                store.create(
                    uuid4(),
                    request_text="Synthetic profile validation test.",
                    data_classification=policy.data_classification,
                    run_profile=profile,
                )
            )
            assert stored.run_profile is profile

        with factory.session(_context(DataClassification.CONFIDENTIAL)) as session:
            with pytest.raises(IntegrityError):
                session.execute(
                    text(
                        """
                        INSERT INTO agent_runtime.agent_runs (
                            run_id, thread_id, investigation_id,
                            investigation_sequence, status, data_classification,
                            run_profile, request_text, response_language,
                            investigation_steps, next_steps, identifiers, documents,
                            tool_call_summary
                        ) VALUES (
                            :run_id, :thread_id, :investigation_id,
                            1, 'running', 2, 'UNSUPPORTED_PROFILE', 'synthetic', 'EN',
                            '[]'::json, '[]'::json, '[]'::json, '[]'::json, '[]'::json
                        )
                        """
                    ),
                    {
                        "run_id": uuid4(),
                        "thread_id": uuid4(),
                        "investigation_id": uuid4(),
                    },
                )
            session.rollback()
    finally:
        factory.dispose()


def test_approval_action_constraint_preserves_ticket_action_and_rejects_unknown() -> (
    None
):
    assert DATABASE_URL is not None
    run_id = uuid4()
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    store = PostgreSqlAgentRunStore(factory, _context(DataClassification.CONFIDENTIAL))
    try:
        asyncio.run(
            store.create(
                run_id,
                request_text="Synthetic approval action validation test.",
                data_classification=DataClassification.CONFIDENTIAL,
            )
        )
        ticket_pending = asyncio.run(
            store.wait_for_approval(
                run_id,
                {"action": "create_maintenance_ticket"},
            )
        )
        with factory.session(_context(DataClassification.CONFIDENTIAL)) as session:
            with pytest.raises(IntegrityError):
                session.execute(
                    text(
                        """
                        UPDATE agent_runtime.agent_runs
                        SET approval_action = 'UNSUPPORTED_ACTION'
                        WHERE run_id = :run_id
                        """
                    ),
                    {"run_id": run_id},
                )
            session.rollback()
    finally:
        factory.dispose()

    assert ticket_pending.approval_action == "create_maintenance_ticket"


def _reference_calibration_approval_request() -> dict[str, object]:
    return {
        "kind": "action_approval",
        "action": "execute_reference_calibration",
        "action_id": "reference-calibration-action-1",
        "arguments": {
            "station_id": "S04",
            "device_id": "POSITION-ENC-02",
            "operation_type": "reference_calibration",
        },
    }


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
