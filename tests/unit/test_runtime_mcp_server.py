from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from industrial_ai_agent.agent.run_classification_policy import AgentRunProfile
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.run_store import (
    RecentRuntimeRunsQuery,
    RuntimeRunInspection,
)
from industrial_ai_agent.infrastructure.api.schemas import RunStatus
from industrial_ai_agent.infrastructure.runtime_mcp_server import (
    RUNTIME_MCP_SERVER_NAME,
    create_runtime_mcp_server,
)

RUN_ID = UUID("123e4567-e89b-12d3-a456-426614174000")
NOW = datetime(2026, 9, 5, tzinfo=UTC)


def test_runtime_mcp_exposes_only_bounded_read_only_tools() -> None:
    server = _server(_FakeRuntimeStore())
    tools = asyncio.run(server.list_tools())

    assert RUNTIME_MCP_SERVER_NAME == "runtime_mcp"
    assert {tool.name for tool in tools} == {
        "get_agent_run",
        "get_run_tool_trajectory",
        "get_run_approval",
        "get_run_failure",
        "list_recent_agent_runs",
    }
    assert all(tool.annotations.read_only_hint for tool in tools)
    assert all(tool.input_schema["additionalProperties"] is False for tool in tools)
    assert all(
        forbidden not in {name.casefold() for name in tool.input_schema["properties"]}
        for tool in tools
        for forbidden in ("prompt", "answer", "arguments", "results", "checkpoint")
    )


def test_runtime_mcp_projects_a_successful_run_without_internal_payloads() -> None:
    result = asyncio.run(_call("get_agent_run", {"run_id": str(RUN_ID)}))

    assert result == {
        "run_id": str(RUN_ID),
        "status": "success",
        "created_at": "2026-09-05T00:00:00Z",
        "updated_at": "2026-09-05T00:01:00Z",
        "classification": "INTERNAL",
        "run_profile": "INTERNAL_DIAGNOSTIC",
        "model_profile": "local_quality",
        "thread_id": str(RUN_ID),
        "tool_call_count": 2,
        "approval_state": "none",
        "error_code": None,
        "terminal": True,
    }
    rendered = repr(result).casefold()
    for secret in (
        "request_text",
        "raw prompt",
        "final answer",
        "tool arguments",
        "tool result",
        "approval free text",
        "stacktrace",
        "checkpoint",
    ):
        assert secret not in rendered


@pytest.mark.parametrize(
    ("status", "decision", "expected"),
    [
        (RunStatus.WAITING_FOR_APPROVAL, None, "waiting"),
        (RunStatus.SUCCESS, "approve", "approved"),
        (RunStatus.SUCCESS, "reject", "rejected"),
    ],
)
def test_runtime_mcp_projects_only_safe_approval_history(
    status: RunStatus, decision: str | None, expected: str
) -> None:
    record = _inspection(status=status, approval_decision=decision)
    server = _server(_FakeRuntimeStore(records=(record,)))

    async def call() -> dict[str, object]:
        result = await server.call_tool("get_run_approval", {"run_id": str(RUN_ID)})
        return result.structured_content

    result = asyncio.run(call())

    assert result["current_state"] == expected
    assert result["action"] == "create_maintenance_ticket"
    assert "arguments" not in result
    assert "summary" not in result


def test_runtime_mcp_returns_safe_failure_and_ordered_trajectory() -> None:
    record = _inspection(
        status=RunStatus.FAILED,
        tool_names=("get_product_history", "create_maintenance_ticket"),
        error_code="mcp_service_unavailable",
    )
    server = _server(_FakeRuntimeStore(records=(record,)))

    async def call() -> tuple[dict[str, object], dict[str, object]]:
        failure = await server.call_tool("get_run_failure", {"run_id": str(RUN_ID)})
        trajectory = await server.call_tool(
            "get_run_tool_trajectory", {"run_id": str(RUN_ID)}
        )
        return failure.structured_content, trajectory.structured_content

    failure, trajectory = asyncio.run(call())

    assert failure == {
        "run_id": str(RUN_ID),
        "failed": True,
        "failure_status": "failed",
        "error_code": "mcp_service_unavailable",
    }
    assert trajectory["tool_call_count"] == 2
    assert trajectory["trajectory"] == [
        {
            "sequence": 1,
            "tool_name": "get_product_history",
            "mcp_server": "factory-mcp",
            "operation": "read",
            "approval_required": False,
        },
        {
            "sequence": 2,
            "tool_name": "create_maintenance_ticket",
            "mcp_server": "factory-mcp",
            "operation": "write",
            "approval_required": True,
        },
    ]


def test_runtime_mcp_returns_empty_trajectory_and_not_found_for_unknown_run() -> None:
    server = _server(_FakeRuntimeStore(records=(_inspection(tool_names=()),)))

    async def call() -> None:
        empty = await server.call_tool("get_run_tool_trajectory", {"run_id": str(RUN_ID)})
        assert empty.structured_content["trajectory"] == []
        with pytest.raises(ToolError, match="Error executing tool"):
            await server.call_tool(
                "get_agent_run", {"run_id": "123e4567-e89b-12d3-a456-426614174999"}
            )

    asyncio.run(call())


def test_runtime_mcp_validates_run_ids_and_bounded_recent_filters() -> None:
    store = _FakeRuntimeStore()
    server = _server(store)

    async def call() -> dict[str, object]:
        with pytest.raises(ToolError, match="Error executing tool"):
            await server.call_tool("get_agent_run", {"run_id": "not-a-uuid"})
        with pytest.raises(ToolError, match="Error executing tool"):
            await server.call_tool("list_recent_agent_runs", {"limit": 51})
        with pytest.raises(ToolError, match="Error executing tool"):
            await server.call_tool("list_recent_agent_runs", {"lookback": "90d"})
        result = await server.call_tool(
            "list_recent_agent_runs",
            {"status": "success", "classification": "INTERNAL", "limit": 1, "lookback": "1h"},
        )
        return result.structured_content

    result = asyncio.run(call())

    assert result["limit"] == 1
    assert len(result["runs"]) == 1
    assert store.last_query is not None
    assert store.last_query.limit == 1
    assert store.last_query.status is RunStatus.SUCCESS
    assert store.last_query.data_classification is DataClassification.INTERNAL
    assert NOW - timedelta(hours=1, seconds=2) <= store.last_query.created_after <= NOW + timedelta(days=1)


async def _call(name: str, arguments: dict[str, object]) -> dict[str, object]:
    result = await _server(_FakeRuntimeStore()).call_tool(name, arguments)
    return result.structured_content


def _server(store: _FakeRuntimeStore):
    return create_runtime_mcp_server(store_for_context=lambda _: store)


def _inspection(
    *,
    status: RunStatus = RunStatus.SUCCESS,
    tool_names: tuple[str, ...] = ("get_product_history", "search_documentation"),
    error_code: str | None = None,
    approval_decision: str | None = None,
) -> RuntimeRunInspection:
    return RuntimeRunInspection(
        run_id=RUN_ID,
        thread_id=RUN_ID,
        status=status,
        data_classification=DataClassification.INTERNAL,
        run_profile=AgentRunProfile.INTERNAL_DIAGNOSTIC,
        model_profile="local_quality",
        tool_call_count=len(tool_names),
        tool_names=tool_names,
        error_code=error_code,
        approval_action="create_maintenance_ticket" if status is RunStatus.WAITING_FOR_APPROVAL or approval_decision else None,
        approval_decision=approval_decision,
        approval_requested_at=NOW if approval_decision or status is RunStatus.WAITING_FOR_APPROVAL else None,
        approval_decided_at=NOW + timedelta(minutes=1) if approval_decision else None,
        created_at=NOW,
        updated_at=NOW + timedelta(minutes=1),
    )


class _FakeRuntimeStore:
    def __init__(self, records: tuple[RuntimeRunInspection, ...] | None = None) -> None:
        self.records = records or (_inspection(),)
        self.last_query: RecentRuntimeRunsQuery | None = None

    async def inspect(self, run_id: UUID) -> RuntimeRunInspection | None:
        return next((record for record in self.records if record.run_id == run_id), None)

    async def list_recent(
        self, query: RecentRuntimeRunsQuery
    ) -> tuple[RuntimeRunInspection, ...]:
        self.last_query = query
        return tuple(
            record
            for record in self.records
            if (query.status is None or record.status is query.status)
            and (
                query.data_classification is None
                or record.data_classification is query.data_classification
            )
        )[: query.limit]
