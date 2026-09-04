"""FastAPI development entry point for the local Industrial AI Agent API."""

import os
from pathlib import Path

import uvicorn

from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.local_environment import load_local_environment
from industrial_ai_agent.infrastructure.troubleshooting_run_composition import (
    create_default_troubleshooting_run_service,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FRONTEND_ORIGIN = "http://localhost:8080"


def create_default_app():
    """Compose the local/demo FastAPI application without embedding deployment details."""
    load_local_environment(PROJECT_ROOT / ".env")
    frontend_origin = os.getenv("AGENT_FRONTEND_ORIGIN", DEFAULT_FRONTEND_ORIGIN)
    return create_app(
        create_default_troubleshooting_run_service(),
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
