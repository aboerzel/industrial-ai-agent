"""Run classification is a resource gate independent of MCP service permission."""

import asyncio
import inspect
from types import SimpleNamespace
from uuid import UUID

import pytest

from industrial_ai_agent.application.mcp_access import McpPermission
from industrial_ai_agent.application.rca_analysis import RcaEvidenceCollector
from industrial_ai_agent.application.rca_evidence import RcaRunNotAccessibleError
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.mcp_access_control import (
    DemoBearerTokenAuthenticator,
    McpHttpAccessControl,
    RegisteredMcpClientContextResolver,
    _registration,
)
from industrial_ai_agent.infrastructure.observability_mcp_server import (
    create_observability_mcp_server,
)
from industrial_ai_agent.infrastructure.rca_evidence import (
    StoreBackedRuntimeRcaEvidenceAdapter,
)
from industrial_ai_agent.infrastructure.runtime_mcp_server import (
    create_runtime_mcp_server,
)

INTERNAL_RUN = UUID("123e4567-e89b-12d3-a456-426614174000")
RESTRICTED_RUN = UUID("123e4567-e89b-12d3-a456-426614174001")
INTERNAL_TRACE = "0123456789abcdef0123456789abcdef"
RESTRICTED_TRACE = "1123456789abcdef0123456789abcdef"
UNKNOWN_TRACE = "2123456789abcdef0123456789abcdef"
RUN_TOOLS = (
    ("get_run_trace", "run_id"),
    ("investigate_run", "run_id"),
    ("get_run_metrics", "run_or_trace_id"),
)
TRACE_TOOLS = (
    ("get_trace_logs", "trace_id"),
    ("get_run_metrics", "run_or_trace_id"),
)


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def _model(self, operation):
        self.calls.append(operation)
        return SimpleNamespace(model_dump=lambda **kwargs: {"status": "ok"})

    def get_run_trace(self, run_id):
        return self._model("trace")

    def get_trace_logs(self, trace_id, service_name=None):
        self.calls.append("logs")
        return ()

    def get_run_metrics(self, identifier):
        return self._model("metrics")

    def investigate_run(self, run_id):
        self.calls.append("investigate")
        return {"status": "ok"}

    def get_service_health(self, service_name, time_window):
        return self._model("health")


def _setup(clearance=DataClassification.INTERNAL, permission=True, mapping=True):
    store = InMemoryAgentRunStore()
    asyncio.run(
        store.create(INTERNAL_RUN, data_classification=DataClassification.INTERNAL)
    )
    asyncio.run(
        store.create(RESTRICTED_RUN, data_classification=DataClassification.RESTRICTED)
    )
    backend = RecordingBackend()
    servers = {}
    permissions = {McpPermission.READ_AGENT_RUNTIME, McpPermission.READ_RCA}
    if permission:
        permissions.add(McpPermission.READ_OBSERVABILITY)
    registration = _registration(
        token="visibility-test-token",
        client_id="visibility-test",
        clearance=clearance,
        permissions=frozenset(permissions),
    )

    def access(key, required):
        async def tools():
            return await servers[key].list_tools()

        return McpHttpAccessControl(
            authenticator=DemoBearerTokenAuthenticator((registration,)),
            resolver=RegisteredMcpClientContextResolver((registration,)),
            tools=tools,
            required_permission=lambda name: required,
        )

    context = SimpleNamespace(headers={"authorization": "Bearer visibility-test-token"})
    observed_contexts = []

    def store_for_context(security_context):
        observed_contexts.append(security_context)
        return store

    servers["observability"] = create_observability_mcp_server(
        evidence_service=backend,
        store_for_context=store_for_context,
        trace_run_ids={INTERNAL_TRACE: INTERNAL_RUN, RESTRICTED_TRACE: RESTRICTED_RUN}
        if mapping
        else None,
        access_control=access("observability", McpPermission.READ_OBSERVABILITY),
    )
    servers["runtime"] = create_runtime_mcp_server(
        store_for_context=store_for_context,
        access_control=access("runtime", McpPermission.READ_AGENT_RUNTIME),
    )
    return servers, backend, context, observed_contexts, store


async def _call(server, name, arguments, context):
    # Invoke the registered handler with the real server-resolved auth context;
    # wire-level argument validation and neutral errors have separate HTTP coverage.
    tool = server._tool_manager.get_tool(name)
    result = tool.fn(**arguments, ctx=context)
    return await result if inspect.isawaitable(result) else result


@pytest.mark.parametrize("tool,key", RUN_TOOLS)
@pytest.mark.parametrize(
    "clearance,run_id,allowed",
    [
        (DataClassification.INTERNAL, INTERNAL_RUN, True),
        (DataClassification.INTERNAL, RESTRICTED_RUN, False),
        (DataClassification.RESTRICTED, RESTRICTED_RUN, True),
    ],
)
def test_run_visibility_matrix(tool, key, clearance, run_id, allowed):
    servers, backend, context, seen, _ = _setup(clearance)

    async def verify():
        if allowed:
            await _call(
                servers["runtime"], "get_agent_run", {"run_id": str(run_id)}, context
            )
            await _call(servers["observability"], tool, {key: str(run_id)}, context)
        else:
            for service, name, args in (
                ("runtime", "get_agent_run", {"run_id": str(run_id)}),
                ("observability", tool, {key: str(run_id)}),
            ):
                with pytest.raises(LookupError, match="^Agent run was not found$"):
                    await _call(servers[service], name, args, context)

    asyncio.run(verify())
    assert len(backend.calls) == int(allowed)
    assert all(item.clearance == clearance for item in seen)


@pytest.mark.parametrize("tool,key", TRACE_TOOLS)
@pytest.mark.parametrize(
    "trace_id,allowed",
    [(INTERNAL_TRACE, True), (RESTRICTED_TRACE, False), (UNKNOWN_TRACE, False)],
)
def test_direct_trace_visibility_and_neutral_absence(tool, key, trace_id, allowed):
    servers, backend, context, _, _ = _setup()

    async def verify():
        if allowed:
            await _call(
                servers["observability"], tool, {key: trace_id.upper()}, context
            )
        else:
            with pytest.raises(LookupError, match="^Agent run was not found$"):
                await _call(servers["observability"], tool, {key: trace_id}, context)

    asyncio.run(verify())
    assert len(backend.calls) == int(allowed)


@pytest.mark.parametrize("tool,key", (*RUN_TOOLS, *TRACE_TOOLS))
def test_clearance_does_not_replace_service_permission(tool, key):
    servers, backend, context, seen, _ = _setup(
        DataClassification.RESTRICTED, permission=False
    )
    identifier = RESTRICTED_TRACE if key == "trace_id" else str(RESTRICTED_RUN)
    with pytest.raises(PermissionError, match="^MCP tool is not authorized$"):
        asyncio.run(_call(servers["observability"], tool, {key: identifier}, context))
    assert backend.calls == []
    assert seen == []


@pytest.mark.parametrize("tool,key", TRACE_TOOLS)
def test_unmapped_trace_fails_closed_even_with_maximum_clearance(tool, key):
    servers, backend, context, _, _ = _setup(
        DataClassification.RESTRICTED, mapping=False
    )
    with pytest.raises(LookupError, match="^Agent run was not found$"):
        asyncio.run(
            _call(servers["observability"], tool, {key: RESTRICTED_TRACE}, context)
        )
    assert backend.calls == []


def test_service_health_does_not_require_a_visible_run():
    servers, backend, context, seen, _ = _setup(DataClassification.PUBLIC)
    result = asyncio.run(
        _call(
            servers["observability"],
            "get_service_health",
            {"service_name": "runtime-mcp"},
            context,
        )
    )
    assert result["status"] == "ok"
    assert backend.calls == ["health"]
    assert seen == []


def test_service_health_still_requires_observability_permission():
    servers, backend, context, seen, _ = _setup(
        DataClassification.RESTRICTED, permission=False
    )
    with pytest.raises(PermissionError, match="^MCP tool is not authorized$"):
        asyncio.run(
            _call(
                servers["observability"],
                "get_service_health",
                {"service_name": "runtime-mcp"},
                context,
            )
        )
    assert backend.calls == []
    assert seen == []


def test_authorized_projection_preserves_derived_metadata_classification():
    servers, backend, context, _, _ = _setup(DataClassification.RESTRICTED)
    metadata = {"spans": [{"attributes": {"data.classification": "RESTRICTED"}}]}

    def classified_trace(run_id):
        backend.calls.append("trace")
        return SimpleNamespace(model_dump=lambda **kwargs: metadata)

    backend.get_run_trace = classified_trace
    result = asyncio.run(
        _call(
            servers["observability"],
            "get_run_trace",
            {"run_id": str(RESTRICTED_RUN)},
            context,
        )
    )
    assert result["spans"][0]["attributes"]["data.classification"] == "RESTRICTED"


def test_rca_cannot_bypass_the_same_restricted_run_boundary():
    _, backend, _, _, store = _setup()
    registration = _registration(
        token="rca-test",
        client_id="rca-test",
        clearance=DataClassification.INTERNAL,
        permissions=frozenset({McpPermission.READ_RCA}),
    )
    collector = RcaEvidenceCollector(
        runtime=StoreBackedRuntimeRcaEvidenceAdapter(lambda context: store),
        trace=backend,
        logs=backend,
        metrics=backend,
    )
    with pytest.raises(RcaRunNotAccessibleError):
        asyncio.run(
            collector.collect(
                RESTRICTED_RUN, registration.access_context.security_context
            )
        )
    assert backend.calls == []
