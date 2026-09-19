"""Static guarantees for catalog-backed model execution dashboards."""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIRECTORY = PROJECT_ROOT / "observability" / "grafana" / "dashboards"
EXECUTION_DASHBOARD = DASHBOARD_DIRECTORY / "industrial-ai-agent-model-execution.json"
POLICY_DASHBOARD = DASHBOARD_DIRECTORY / "industrial-ai-agent-model-policy.json"


def test_model_execution_dashboard_uses_catalog_display_names_and_stable_identity() -> (
    None
):
    dashboard = json.loads(EXECUTION_DASHBOARD.read_text(encoding="utf-8"))
    rendered = json.dumps(dashboard)

    assert dashboard["uid"] == "industrial-ai-agent-model-execution"
    assert "model_display_name" in rendered
    assert "{{model_id}}" not in rendered
    assert "model_profile" not in rendered
    assert "Run-Level Execution Path" in {
        panel["title"] for panel in dashboard["panels"]
    }


def test_model_execution_dashboard_distinguishes_all_policy_outcomes() -> None:
    dashboard = json.loads(EXECUTION_DASHBOARD.read_text(encoding="utf-8"))
    panel = next(
        item
        for item in dashboard["panels"]
        if item["title"] == "Model Decision Outcomes"
    )
    rendered = json.dumps(panel)

    for outcome in (
        "EXECUTED",
        "EGRESS_DENIED",
        "CAPABILITY_MISMATCH",
        "MODEL_NOT_CONFIGURED",
    ):
        assert outcome in rendered
    assert "#73BF69" in rendered
    assert "#E02F44" in rendered
    assert "#FF9830" in rendered
    assert "#5794F2" in rendered


def test_model_policy_dashboard_keeps_security_signals_separate_from_provider_failures() -> (
    None
):
    dashboard = json.loads(POLICY_DASHBOARD.read_text(encoding="utf-8"))
    titles = {panel["title"] for panel in dashboard["panels"]}
    rendered = json.dumps(dashboard)

    assert dashboard["uid"] == "industrial-ai-agent-model-policy"
    assert {
        "Allowed and Executed Decisions",
        "Egress Denied",
        "Capability Mismatch",
        "Model Not Configured",
        "Denied Decision Details",
    } <= titles
    assert "model_display_name" in rendered
    assert "{{model_id}}" not in rendered
