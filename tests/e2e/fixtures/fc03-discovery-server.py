"""Real browser/API/agent/MCP/RLS fixture with an intentionally incomplete fake model."""

import sys
from pathlib import Path

import uvicorn
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests/integration"))
from fc03_discovery_support import fixture_app

app, service, store, factory = fixture_app(durable=True)
app.mount("/js", StaticFiles(directory=ROOT / "frontend/js"))
app.mount("/css", StaticFiles(directory=ROOT / "frontend/css"))


@app.get("/")
async def index():
    return FileResponse(ROOT / "frontend/index.html")


@app.get("/fixture-evidence")
async def evidence():
    return service.traces


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(sys.argv[1]),
        log_level="critical",
        access_log=False,
    )
