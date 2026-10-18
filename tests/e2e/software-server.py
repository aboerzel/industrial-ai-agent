"""Test composition only: production application, scripted provider wire response."""

import asyncio
import os
import secrets
import sys
import traceback
from functools import partial
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn
from fastapi import Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/fixtures"))
from release_provider import scripted_completion

from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)

url = make_url(os.environ["FACTORY_DATABASE_URL"])
assert url.host == "127.0.0.1" and url.database.startswith("verification_")
assert os.environ["AGENT_RUNTIME_DATABASE_URL"] == os.environ["FACTORY_DATABASE_URL"]


def scripted_wire(request):
    try:
        return scripted_completion(request)
    except Exception:
        traceback.print_exc()
        raise


transport = httpx.MockTransport(scripted_wire)
with patch(
    "industrial_ai_agent.infrastructure.troubleshooting_run_composition.OpenAICompatibleLLMClient",
    partial(
        OpenAICompatibleLLMClient,
        http_client_factory=lambda: httpx.Client(transport=transport, trust_env=False),
    ),
):
    from industrial_ai_agent.infrastructure.agent_api import app

    app.mount("/js", StaticFiles(directory=ROOT / "frontend/js"))
    app.mount("/css", StaticFiles(directory=ROOT / "frontend/css"))

    @app.get("/__release_fixture__")
    async def release_fixture(x_release_fixture: str = Header(default="")):
        if not secrets.compare_digest(
            x_release_fixture, os.environ["RELEASE_SOFTWARE_TOKEN"]
        ):
            raise HTTPException(status_code=403)
        return {"mode": "SOFTWARE_DETERMINISTIC"}

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "frontend/index.html")

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=int(sys.argv[1]),
            log_level="warning",
            access_log=False,
        )
    )
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(server.serve())
    else:
        server.run()
