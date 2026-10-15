"""Synthetic browser fixture using the real API/session/authorization implementation."""

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import uvicorn
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from industrial_ai_agent.agent.agent_run import (
    AgentRunResult,
    AgentRunStatus,
    DocumentReference,
    IdentifierReference,
)
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
sys.path.insert(0, str(ROOT / "tests/integration"))
from test_demo_discovery_rls import DiscoveryRunService
from test_frontend_gateway_security import Assignments, Catalog, Documents

from industrial_ai_agent.agent.model_egress import (
    ModelExecutionAuthorizer,
)
from industrial_ai_agent.agent.model_selection import (
    AGENT_CONSUMER,
    CURRENT_MODEL_CONSUMERS,
)
from industrial_ai_agent.agent.run_classification_policy import (
    resolve_demo_discovery_tool,
)
from industrial_ai_agent.application.model_configuration import (
    ModelConfigurationService,
)
from industrial_ai_agent.domain.factory_discovery import StationDiscovery
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.in_memory_factory_discovery_repository import (
    InMemoryFactoryDiscoveryRepository,
)
from industrial_ai_agent.infrastructure.persistence.demo_seed import (
    STATION_CLASSIFICATIONS,
)


class SyntheticRunService:
    persistent_hitl_enabled = True

    async def start(self, message, *, run_id, **kwargs):
        if message == "Investigate S04.":
            return SimpleNamespace(name="local_quality"), RunExecution(
                approval=PendingApproval(
                    action="create_maintenance_ticket",
                    action_id="synthetic-r04-action",
                    approval_execution_id=str(uuid4()),
                    arguments={"station_id": "S04", "summary": "Synthetic R04 action"},
                    summary="SYNTHETIC CONFIDENTIAL PENDING APPROVAL",
                )
            )
        return SimpleNamespace(name="local_quality"), RunExecution(
            result=await self.run_with_policy(message, **kwargs)
        )

    async def resume(self, **kwargs):
        return RunExecution(
            result=AgentRunResult(
                status=AgentRunStatus.SUCCESS,
                final_answer="Synthetic decision; no action executed.",
                tool_call_count=0,
            )
        )

    async def run_with_policy(self, message, **kwargs):
        if resolve_demo_discovery_tool(message):
            # Browser-only recording repository; real PostgreSQL RLS is covered by
            # test_demo_discovery_rls using the same API/graph/capability path.
            service = DiscoveryRunService(
                lambda context: InMemoryFactoryDiscoveryRepository(
                    stations=tuple(
                        StationDiscovery(
                            station_id=StationId(code),
                            name=f"Synthetic {code}",
                            state=None,
                            active_error_code=None,
                            classification=DataClassification(level),
                        )
                        for code, level in STATION_CLASSIFICATIONS.items()
                        if level <= context.clearance
                    )
                )
            )
            return await service.run_with_policy(message, **kwargs)
        references = message == "Investigate P4711."
        return AgentRunResult(
            status=AgentRunStatus.SUCCESS,
            final_answer=(
                "R04 SYNTHETIC RESTRICTED CONTEXT"
                if message == "Investigate S07."
                else "SYNTHETIC CONFIDENTIAL CONVERSATION"
            ),
            identifiers=(IdentifierReference(type="station", value="S04"),)
            if references
            else (),
            documents=(
                DocumentReference(
                    document_id="CONFIDENTIAL",
                    title="SYNTHETIC CONFIDENTIAL REFERENCE",
                    format="text",
                ),
            )
            if references
            else (),
            tool_call_count=0,
        )


app = create_app(
    SyntheticRunService(),
    run_store=InMemoryAgentRunStore(),
    security_context_resolver=BearerTokenSecurityContextResolver.from_environment(
        {
            "MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN": "synthetic-no-service-calls",
        }
    ),
    demo_sessions=DemoSessions() if "--disabled" not in sys.argv else None,
    document_content_reader=Documents(),
    model_configuration_service=ModelConfigurationService(
        catalog=Catalog(),
        assignments=Assignments(),
        supported_consumers=(AGENT_CONSUMER,),
        consumer_definitions=CURRENT_MODEL_CONSUMERS,
        authorizer=ModelExecutionAuthorizer(),
    ),
)
app.mount("/js", StaticFiles(directory=ROOT / "frontend/js"))
app.mount("/css", StaticFiles(directory=ROOT / "frontend/css"))


@app.get("/")
async def index():
    return FileResponse(ROOT / "frontend/index.html")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(sys.argv[1]),
        log_level="critical",
        access_log=False,
    )
