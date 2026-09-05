"""FastAPI development entry point for the local Industrial AI Agent API."""

import asyncio
import os
import sys
from pathlib import Path

import uvicorn

from industrial_ai_agent.domain.security import DEMO_ENGINEER_SECURITY_CONTEXT
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.local_environment import load_local_environment
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.infrastructure.troubleshooting_run_composition import (
    create_default_troubleshooting_run_service,
)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FRONTEND_ORIGIN = "http://localhost:8080"


def create_default_app():
    """Compose the local/demo FastAPI application without embedding deployment details."""
    load_local_environment(PROJECT_ROOT / ".env")
    frontend_origin = os.getenv("AGENT_FRONTEND_ORIGIN", DEFAULT_FRONTEND_ORIGIN)
    database_url = os.getenv("AGENT_RUNTIME_DATABASE_URL") or os.getenv(
        "FACTORY_DATABASE_URL"
    )
    if not database_url:
        raise RuntimeError(
            "AGENT_RUNTIME_DATABASE_URL or FACTORY_DATABASE_URL is required"
        )
    return create_app(
        create_default_troubleshooting_run_service(runtime_database_url=database_url),
        run_store=PostgreSqlAgentRunStore(
            PostgreSqlSessionFactory(database_url), DEMO_ENGINEER_SECURITY_CONTEXT
        ),
        allowed_origins=(frontend_origin,),
    )


app = create_default_app()


def main() -> None:
    """Run the local FastAPI development server."""
    uvicorn.run(
        "industrial_ai_agent.infrastructure.agent_api:app",
        host=os.getenv("AGENT_API_HOST", "127.0.0.1"),
        port=int(os.getenv("AGENT_API_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
