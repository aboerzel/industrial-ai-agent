"""Cheap checks for the documented current-state application boundary."""

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_fastapi_boundary_documented_routes_exist_in_api_source() -> None:
    api_source = (
        PROJECT_ROOT / "src/industrial_ai_agent/infrastructure/api/app.py"
    ).read_text(encoding="utf-8")
    documentation = (
        PROJECT_ROOT / "docs/learning/fastapi-application-boundary.md"
    ).read_text(encoding="utf-8")

    routes = {
        "/health": '"/health"',
        "/ready": '"/ready"',
        "/api/v1/runs": 'f"{API_PREFIX}/runs"',
        "/api/v1/diagnostics": 'f"{API_PREFIX}/diagnostics"',
        "/api/v1/runs/{run_id}": 'f"{API_PREFIX}/runs/{{run_id}}"',
        "/api/v1/investigations/{investigation_id}": (
            'f"{API_PREFIX}/investigations/{{investigation_id}}"'
        ),
        "/api/v1/investigations/{investigation_id}/pdf": (
            'f"{API_PREFIX}/investigations/{{investigation_id}}/pdf"'
        ),
        "/api/v1/documents/{document_id}": 'f"{API_PREFIX}/documents/{{document_id}}"',
        "/api/v1/runs/{run_id}/resume": 'f"{API_PREFIX}/runs/{{run_id}}/resume"',
        "/api/v1/models": 'f"{API_PREFIX}/models"',
        "/api/v1/model-assignments": 'f"{API_PREFIX}/model-assignments"',
    }
    for route, source_route in routes.items():
        assert route in documentation
        assert source_route in api_source


def test_documented_manual_e2e_commands_are_declared_by_frontend_package() -> None:
    package = json.loads(
        (PROJECT_ROOT / "frontend/package.json").read_text(encoding="utf-8")
    )
    scripts = package["scripts"]
    documentation = (PROJECT_ROOT / "docs/learning/browser-e2e-journeys.md").read_text(
        encoding="utf-8"
    )

    for script in (
        "test",
        "e2e:journey",
        "e2e:manual:preflight",
        "e2e:manual",
        "e2e:manual:aggregate",
    ):
        assert script in scripts
        assert f"npm run {script}" in documentation or script == "test"


def test_current_fastapi_adr_marks_legacy_router_as_historical() -> None:
    adr = (
        PROJECT_ROOT / "docs/decisions/ADR-013-fastapi-application-boundary.md"
    ).read_text(encoding="utf-8")

    assert (
        "The historical `TaskRequirements -> DeterministicModelRouter` path is not the active"
        in adr
    )
    assert "-> ModelResolutionService and catalog lookup" in adr
    assert "ADR-019 supersedes the routing-oriented selection design of ADR-008" in adr


def test_quality_gates_are_documented_and_manual_e2e_is_not_fast() -> None:
    quality_gates = (PROJECT_ROOT / "docs/quality/quality-gates.md").read_text(
        encoding="utf-8"
    )
    gate_script = (PROJECT_ROOT / "scripts/run-quality-gate.ps1").read_text(
        encoding="utf-8"
    )
    package = json.loads(
        (PROJECT_ROOT / "frontend/package.json").read_text(encoding="utf-8")
    )

    for tier in ("FAST", "INTEGRATION", "MANUAL_REAL_MODEL"):
        assert tier in quality_gates
    assert ".\\scripts\\run-quality-gate.ps1 FAST" in quality_gates
    assert ".\\scripts\\run-quality-gate.ps1 INTEGRATION" in quality_gates
    assert "npm run e2e:manual" in quality_gates
    assert "e2e:manual" in package["scripts"]
    fast_section = gate_script.split('if ($Tier -eq "FAST")', maxsplit=1)[1].split(
        "if (-not $env:FACTORY_DATABASE_ADMIN_URL)", maxsplit=1
    )[0]
    assert "e2e:manual" not in fast_section
    assert "ollama" not in fast_section.lower()


def test_manual_real_model_registry_retains_the_twelve_baseline_journeys() -> None:
    runner_source = (PROJECT_ROOT / "frontend/scripts/run-e2e-journey.mjs").read_text(
        encoding="utf-8"
    )
    registry_source = runner_source.split("const command =", maxsplit=1)[0]
    journey_keys = re.findall(
        r'^  (?:"[^"]+"|[a-z][a-z-]*): \{', registry_source, flags=re.MULTILINE
    )

    assert len(journey_keys) == 12
