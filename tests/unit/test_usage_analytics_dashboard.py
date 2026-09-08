"""Static guarantees for the provisioned Usage Analytics dashboard."""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PATH = (
    PROJECT_ROOT
    / "observability"
    / "grafana"
    / "dashboards"
    / "industrial-ai-agent-usage-analytics.json"
)


def test_tool_count_and_duration_panels_share_selected_range_and_layout() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    tool_calls = panels["Tool Calls"]
    duration = panels["Average Tool Call Duration"]

    assert tool_calls["type"] == duration["type"] == "barchart"
    assert tool_calls["gridPos"] == {"h": 9, "w": 12, "x": 0, "y": 15}
    assert duration["gridPos"] == {"h": 9, "w": 12, "x": 12, "y": 15}
    assert tool_calls["options"]["orientation"] == "horizontal"
    assert duration["options"]["orientation"] == "horizontal"

    count_query = tool_calls["targets"][0]["expr"]
    assert "mcp_tool_calls_total[$__range]" in count_query
    assert "$__rate_interval" not in count_query

    duration_query = duration["targets"][0]["expr"]
    assert "mcp_tool_duration_seconds_sum[$__range]" in duration_query
    assert "mcp_tool_duration_seconds_count[$__range]" in duration_query
    assert "and on (mcp_tool)" in duration_query
    assert "> 0" in duration_query
    assert duration_query.startswith("sort_desc(")
    assert duration["fieldConfig"]["defaults"]["unit"] == "s"
