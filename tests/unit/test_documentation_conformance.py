"""Cheap checks for the documented current-state application boundary."""

import json
import re
import tomllib
from pathlib import Path

from industrial_ai_agent.agent.agent_run import MAX_TOOL_CALLS
from industrial_ai_agent.agent.model_selection import (
    ModelSelectionMode,
    ModelSelectionPolicy,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_current_architecture_fact_table_matches_core_selection_and_budget() -> None:
    documentation = (PROJECT_ROOT / "docs/architecture/overview.md").read_text(
        encoding="utf-8"
    )
    facts = {
        columns[0].strip(): re.findall(r"`([^`]+)`", columns[1])
        for line in documentation.splitlines()
        if line.startswith("| ") and len(columns := line.strip("|").split("|")) == 3
    }

    assert set(facts["Model selection modes"]) == {
        mode.value for mode in ModelSelectionMode
    }
    assert set(facts["Automatic selection policies"]) == {
        policy.value for policy in ModelSelectionPolicy
    }
    assert facts["Executed tool-call budget"] == [str(MAX_TOOL_CALLS)]
    for relative_path in (
        "docs/architecture/overview.md",
        "docs/decisions/ADR-004-agent-orchestration-strategy.md",
        "docs/learning/langgraph-langchain-orchestration.md",
    ):
        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        budgets = re.findall(r"MAX_TOOL_CALLS\s*=\s*(\d+)", text)
        assert budgets and {int(budget) for budget in budgets} == {MAX_TOOL_CALLS}


def test_documented_credential_variables_exist_in_configuration_example() -> None:
    documentation = (PROJECT_ROOT / "docs/learning/browser-frontend.md").read_text(
        encoding="utf-8"
    )
    credentials = documentation.split("## Credential Ownership", maxsplit=1)[1].split(
        "## Run Lifecycle", maxsplit=1
    )[0]
    documented_variables = set(re.findall(r"`([A-Z][A-Z_]+)`", credentials))
    configured_variables = set(
        re.findall(
            r"^([A-Z][A-Z_]+)=",
            (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    )

    assert documented_variables
    assert documented_variables <= configured_variables


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


def test_current_overview_describes_the_browser_session_proxy_boundary() -> None:
    overview = (PROJECT_ROOT / "docs/architecture/overview.md").read_text(
        encoding="utf-8"
    )
    nginx = (PROJECT_ROOT / "frontend/nginx.conf").read_text(encoding="utf-8")
    gateway = re.search(r'Gateway\["([^"\n]+)"\]', overview).group(1)

    assert "cookie" in gateway.lower()
    assert "Authorization" in gateway
    assert not re.search(r"API[- ]token|Basic", gateway, re.IGNORECASE)
    for marker in (
        "DemoSessions",
        "industrial_demo_session",
        "HttpOnly",
        "SameSite=Strict",
        "SESSION_INVALIDATED",
    ):
        assert marker in overview
    assert 'proxy_set_header Authorization "";' in nginx
    assert "auth_basic" not in nginx


def test_documented_demo_switch_coverage_uses_the_registered_fixture_suite() -> None:
    documentation = (PROJECT_ROOT / "docs/learning/browser-e2e-journeys.md").read_text(
        encoding="utf-8"
    )
    package = json.loads(
        (PROJECT_ROOT / "frontend/package.json").read_text(encoding="utf-8")
    )
    configuration = (
        PROJECT_ROOT / "frontend/playwright.fixtures.config.mjs"
    ).read_text(encoding="utf-8")
    users = tomllib.loads(
        (PROJECT_ROOT / "config/demo-users.toml").read_text(encoding="utf-8")
    )["users"]

    assert "playwright.fixtures.config.mjs" in package["scripts"]["test:e2e:fixtures"]
    assert 'testDir: "../tests/e2e/fixtures"' in configuration
    assert not re.search(r"\b(?:testIgnore|testMatch)\s*:", configuration)
    assert "--grep" not in package["scripts"]["test:e2e:fixtures"]
    for filename in ("demo-auth.spec.mjs", "r03-approval.spec.mjs"):
        assert filename in documentation
        assert (PROJECT_ROOT / "tests/e2e/fixtures" / filename).is_file()
    for user in users:
        assert f"`{user['username']}`" in documentation
    assert "R04" in documentation and "BFCache" in documentation
    assert "second ordinary" not in documentation
    assert "identity switching is not an automated claim" not in documentation
