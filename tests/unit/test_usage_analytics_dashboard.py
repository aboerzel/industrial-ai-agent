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
COST_DASHBOARD_PATH = DASHBOARD_PATH.with_name(
    "industrial-ai-agent-cost-analytics.json"
)

TOOL_COLORS = {
    "analyze_run": "#C15C17",
    "create_maintenance_ticket": "#FF7383",
    "get_agent_run": "#8AB8FF",
    "get_machine_status": "#73BF69",
    "get_maintenance_ticket": "#5DADE2",
    "get_position_reference_status": "#F2A65A",
    "list_stations": "#5794F2",
    "prepare_reference_calibration": "#56D2B9",
    "execute_reference_calibration": "#FF5C93",
    "list_products": "#FF9830",
    "search_documentation": "#B877D9",
    "get_product_history": "#F2CC0C",
    "get_station_overview": "#E24D42",
    "get_product_overview": "#70DBED",
    "get_run_approval": "#FFB357",
    "get_run_failure": "#E02F44",
    "get_run_metrics": "#1F78C1",
    "get_run_tool_trajectory": "#A3BE8C",
    "get_run_trace": "#6ED0E0",
    "get_service_health": "#508642",
    "get_trace_logs": "#CCA300",
    "investigate_run": "#BA43A9",
    "list_recent_agent_runs": "#B48EAD",
    "runtime.approval.lookup": "#9E77ED",
    "runtime.failure.lookup": "#F2495C",
    "runtime.run.list": "#A1C181",
    "runtime.run.lookup": "#D683CE",
    "runtime.trajectory.lookup": "#4C78A8",
}


def test_tool_count_and_duration_panels_share_selected_range_and_layout() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    tool_calls = panels["Tool Calls"]
    duration = panels["Average Tool Call Duration"]

    assert len(TOOL_COLORS) == 28
    assert tool_calls["type"] == duration["type"] == "barchart"
    assert tool_calls["description"] == (
        "Number of instrumented tool calls within the selected time range. "
        "Client and server boundaries may both contribute."
    )
    assert duration["description"] == (
        "Average duration per individual tool call within the selected time range. "
        "Tools without calls in that range are omitted."
    )
    assert tool_calls["gridPos"] == {"h": 9, "w": 12, "x": 0, "y": 15}
    assert duration["gridPos"] == {"h": 9, "w": 12, "x": 12, "y": 15}
    assert tool_calls["options"]["orientation"] == "horizontal"
    assert duration["options"]["orientation"] == "horizontal"

    count_query = tool_calls["targets"][0]["expr"]
    assert "mcp_tool_calls_total[$__range]" in count_query
    assert "$__rate_interval" not in count_query
    assert count_query.endswith("> 0)")
    assert tool_calls["targets"][0]["instant"] is True
    assert tool_calls["targets"][0]["range"] is False
    assert tool_calls["targets"][0]["legendFormat"] == "{{mcp_tool}}"

    duration_query = duration["targets"][0]["expr"]
    assert "mcp_tool_duration_seconds_sum[$__range]" in duration_query
    assert "mcp_tool_duration_seconds_count[$__range]" in duration_query
    assert "and on (mcp_tool)" in duration_query
    assert "> 0" in duration_query
    assert duration_query.startswith("sort_desc(")
    assert duration["targets"][0]["instant"] is True
    assert duration["targets"][0]["range"] is False
    assert duration["targets"][0]["legendFormat"] == "{{mcp_tool}}"
    assert duration["fieldConfig"]["defaults"]["unit"] == "s"

    for panel in (tool_calls, duration):
        assert panel["options"]["orientation"] == "horizontal"
        assert panel["options"]["xField"] == "Tool"
        assert panel["options"]["colorByField"] == "Tool"
        assert panel["options"]["showValue"] == "always"
        assert panel["options"]["tooltip"] == {
            "mode": "single",
            "sort": "desc",
            "maxWidth": 600,
        }
        assert panel["transformations"] == [
            {"id": "seriesToRows", "options": {}},
            {
                "id": "organize",
                "options": {
                    "excludeByName": {"Time": True},
                    "indexByName": {"Metric": 0, "Value": 1, "Time": 2},
                    "renameByName": {
                        "Metric": "Tool",
                        "Value": (
                            "Calls"
                            if panel["title"] == "Tool Calls"
                            else "Average Duration"
                        ),
                    },
                },
            },
        ]

        color_mapping = panel["fieldConfig"]["overrides"][0]
        assert color_mapping["matcher"] == {"id": "byName", "options": "Tool"}
        values = color_mapping["properties"][0]["value"]
        assert values[0]["type"] == "value"
        assert {
            tool_name: value["color"]
            for tool_name, value in values[0]["options"].items()
        } == TOOL_COLORS
        assert {
            tool_name: value["text"]
            for tool_name, value in values[0]["options"].items()
        } == {tool_name: tool_name for tool_name in TOOL_COLORS}


def test_usage_counters_are_fixed_green() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    panels = {panel["title"]: panel for panel in dashboard["panels"]}

    for title in (
        "Agent Runs",
        "LLM Calls",
        "MCP Tool Operations",
        "Retrieval Operations",
    ):
        defaults = panels[title]["fieldConfig"]["defaults"]
        assert defaults["color"] == {"mode": "fixed", "fixedColor": "#73BF69"}
        assert defaults["thresholds"] == {
            "mode": "absolute",
            "steps": [{"color": "green", "value": None}],
        }

    for title, panel in panels.items():
        if title not in {
            "Agent Runs",
            "LLM Calls",
            "MCP Tool Operations",
            "Retrieval Operations",
        }:
            assert "thresholds" not in panel["fieldConfig"]["defaults"]


def test_run_classification_uses_distinct_semantic_colors() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    panel = next(
        panel
        for panel in dashboard["panels"]
        if panel["title"] == "Runs by Classification"
    )

    colors = {
        override["matcher"]["options"]: override["properties"][0]["value"]["fixedColor"]
        for override in panel["fieldConfig"]["overrides"]
    }
    assert colors == {
        "PUBLIC": "#73BF69",
        "INTERNAL": "#5794F2",
        "CONFIDENTIAL": "#FF9830",
        "RESTRICTED": "#E02F44",
    }
    assert len(set(colors.values())) == len(colors)


def test_cost_tool_colors_are_name_based_and_shared() -> None:
    dashboard = json.loads(COST_DASHBOARD_PATH.read_text(encoding="utf-8"))
    panels = {
        panel["title"]: panel
        for panel in dashboard["panels"]
        if panel["title"]
        in {
            "Tool Decisions by Tool",
            "Attributed Tokens by Tool",
            "Average Total Tokens per Tool Decision",
        }
    }
    assert len(panels) == 3

    mappings = []
    for panel in panels.values():
        assert panel["options"]["xField"] == "Tool"
        assert panel["options"]["colorByField"] == "Tool"
        override = panel["fieldConfig"]["overrides"][0]
        assert override["matcher"] == {"id": "byName", "options": "Tool"}
        mappings.append(override["properties"][0]["value"][0]["options"])

    assert all(mapping == mappings[0] for mapping in mappings[1:])
    colors = {name: value["color"] for name, value in mappings[0].items()}
    assert colors == TOOL_COLORS
    assert len(set(colors.values())) == len(colors)
