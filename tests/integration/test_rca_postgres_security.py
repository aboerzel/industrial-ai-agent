"""Live RLS verification for the RCA runtime-before-telemetry invariant."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.application.rca_analysis import RcaEvidenceCollector
from industrial_ai_agent.application.rca_evidence import RcaRunNotAccessibleError
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.mcp_access_control import (
    DemoBearerTokenAuthenticator,
    McpHttpAccessControl,
    RegisteredMcpClientContextResolver,
    _registration,
)
from industrial_ai_agent.infrastructure.observability_mcp_server import (
    create_observability_mcp_server,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.infrastructure.rca_evidence import (
    StoreBackedRuntimeRcaEvidenceAdapter,
)
from industrial_ai_agent.infrastructure.runtime_mcp_server import (
    create_runtime_mcp_server,
)

DATABASE_URL = os.getenv("FACTORY_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="requires FACTORY_DATABASE_URL for the local PostgreSQL integration service",
)


class TraceMustNotBeCalled:
    def __init__(self) -> None:
        self.calls = 0

    def get_run_trace(self, run_id: UUID) -> object:
        self.calls += 1
        raise AssertionError(f"Telemetry lookup must not occur for {run_id}")


class UnusedLogs:
    def get_trace_logs(self, trace: object) -> tuple[object, ...]:
        raise AssertionError("Log lookup must not occur")


class UnusedMetrics:
    def get_trace_metrics(self, trace: object) -> tuple[object, ...]:
        raise AssertionError("Metric lookup must not occur")


def test_rca_denies_telemetry_before_trace_correlation_for_hidden_run() -> None:
    assert DATABASE_URL is not None
    run_id = uuid4()
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    confidential_context = _context(DataClassification.CONFIDENTIAL)
    public_context = _context(DataClassification.PUBLIC)
    trace = TraceMustNotBeCalled()
    try:
        asyncio.run(
            PostgreSqlAgentRunStore(factory, confidential_context).create(
                run_id,
                request_text="RCA RLS verification record",
                data_classification=DataClassification.CONFIDENTIAL,
            )
        )
        collector = RcaEvidenceCollector(
            runtime=StoreBackedRuntimeRcaEvidenceAdapter(
                lambda context: PostgreSqlAgentRunStore(factory, context)
            ),
            trace=trace,  # type: ignore[arg-type]
            logs=UnusedLogs(),  # type: ignore[arg-type]
            metrics=UnusedMetrics(),  # type: ignore[arg-type]
        )

        with pytest.raises(RcaRunNotAccessibleError):
            asyncio.run(collector.collect(run_id, public_context))
    finally:
        factory.dispose()

    assert trace.calls == 0


@pytest.mark.parametrize(
    "clearance,classification,allowed",
    [
        (DataClassification.INTERNAL, DataClassification.INTERNAL, True),
        (DataClassification.INTERNAL, DataClassification.RESTRICTED, False),
        (DataClassification.RESTRICTED, DataClassification.RESTRICTED, True),
    ],
)
def test_runtime_and_observability_share_authoritative_rls_visibility(
    clearance, classification, allowed
):
    assert DATABASE_URL is not None
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    run_id = uuid4()
    trace_id = uuid4().hex
    trace = _RecordingTrace()
    registration = _registration(
        token="rls-visibility-test",
        client_id="rls-visibility-test",
        clearance=clearance,
        permissions=frozenset(
            {McpPermission.READ_AGENT_RUNTIME, McpPermission.READ_OBSERVABILITY}
        ),
    )
    context = SimpleNamespace(headers={"authorization": "Bearer rls-visibility-test"})
    servers = {}

    def access(key, permission):
        async def tools():
            return await servers[key].list_tools()

        return McpHttpAccessControl(
            authenticator=DemoBearerTokenAuthenticator((registration,)),
            resolver=RegisteredMcpClientContextResolver((registration,)),
            tools=tools,
            required_permission=lambda name: permission,
        )

    def store_for_context(security_context):
        return PostgreSqlAgentRunStore(factory, security_context)

    servers["runtime"] = create_runtime_mcp_server(
        store_for_context=store_for_context,
        access_control=access("runtime", McpPermission.READ_AGENT_RUNTIME),
    )
    servers["observability"] = create_observability_mcp_server(
        evidence_service=trace,
        store_for_context=store_for_context,
        trace_run_ids={trace_id: run_id},
        access_control=access("observability", McpPermission.READ_OBSERVABILITY),
    )

    async def verify():
        await store_for_context(_context(DataClassification.RESTRICTED)).create(
            run_id,
            data_classification=classification,
        )
        # Check actual RLS behavior, separately from the Python defense in depth.
        persisted = await store_for_context(
            registration.access_context.security_context
        ).inspect(run_id)
        assert (persisted is not None) is allowed
        for key, tool, arguments in (
            ("runtime", "get_agent_run", {"run_id": str(run_id)}),
            ("observability", "get_run_trace", {"run_id": str(run_id)}),
            ("observability", "get_trace_logs", {"trace_id": trace_id}),
        ):
            handler = servers[key]._tool_manager.get_tool(tool).fn
            if allowed:
                await handler(**arguments, ctx=context)
            else:
                with pytest.raises(LookupError, match="^Agent run was not found$"):
                    await handler(**arguments, ctx=context)

    try:
        asyncio.run(verify())
    finally:
        factory.dispose()
    assert trace.calls == (2 if allowed else 0)


class _RecordingTrace:
    def __init__(self):
        self.calls = 0

    def get_run_trace(self, run_id):
        self.calls += 1
        return SimpleNamespace(model_dump=lambda **kwargs: {"run_id": run_id})

    def get_trace_logs(self, trace_id, service_name=None):
        self.calls += 1
        return ()


def _context(clearance: DataClassification) -> SecurityContext:
    return SecurityContext(
        subject_id=f"rca-security-{clearance.name.lower()}",
        roles=("test-engineer",),
        clearance=clearance,
        authenticated=False,
    )
