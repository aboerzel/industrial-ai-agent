"""Loopback-only real API with two synthetic approvals and no action capability."""

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import uvicorn
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from industrial_ai_agent.agent.agent_run import AgentRunResult, AgentRunStatus
from industrial_ai_agent.agent.troubleshooting_run_service import (
    PendingApproval,
    RunExecution,
)
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.demo_security import (
    BearerTokenSecurityContextResolver,
)
from industrial_ai_agent.infrastructure.api.demo_sessions import DemoSessions
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore

ROOT = Path(__file__).resolve().parents[3]


def approval(station):
    return RunExecution(
        approval=PendingApproval(
            action="create_maintenance_ticket",
            action_id="reused-model-action-id",
            approval_execution_id=str(uuid4()),
            arguments={
                "station_id": station,
                "summary": "Synthetic no-action approval",
            },
            summary=f"Synthetic review for {station}",
        )
    )


class SyntheticResume:
    persistent_hitl_enabled = True

    def __init__(self):
        self.resumes = {}

    async def start(self, message, *, run_id, **kwargs):
        self.resumes[run_id] = 0
        return SimpleNamespace(name="local_quality"), approval("S04")

    async def resume(self, *, run_id, **kwargs):
        self.resumes[run_id] += 1
        if self.resumes[run_id] == 1:
            return approval("S02")
        return RunExecution(
            result=AgentRunResult(
                status=AgentRunStatus.SUCCESS,
                final_answer="Synthetic completion; no action executed.",
                tool_call_count=0,
            )
        )


app = create_app(
    SyntheticResume(),
    run_store=InMemoryAgentRunStore(),
    demo_sessions=DemoSessions(),
    security_context_resolver=BearerTokenSecurityContextResolver.from_environment(
        {"MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN": "synthetic-r03-no-service-calls"}
    ),
)
app.mount("/js", StaticFiles(directory=ROOT / "frontend/js"))
app.mount("/css", StaticFiles(directory=ROOT / "frontend/css"))


@app.get("/")
async def index():
    return FileResponse(ROOT / "frontend/index.html")


@app.get("/away")
async def away():
    return HTMLResponse("<p>Synthetic navigation destination</p>")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(sys.argv[1]),
        log_level="critical",
        access_log=False,
    )
