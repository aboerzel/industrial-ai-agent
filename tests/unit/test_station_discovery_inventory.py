"""Station inventory comes from guarded typed observations, not narrative/references."""

import json

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from industrial_ai_agent.agent.agent_run import (
    FinalAgentOutput,
    FinalAgentOutputContractError,
)
from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    _derive_structured_references,
    _with_station_inventory,
)


def inventory_state(count, *, prompt="welche stationen kennst du", language="DE"):
    payload = {
        "stations": [
            {
                "station_id": f"S{index + 1:02}",
                "name": f"Synthetic station {index + 1}",
                "state": "RUNNING" if index % 2 else None,
                "active_error_code": None,
                "classification": 0,
            }
            for index in range(count)
        ],
        "classification": 0,
    }
    return {
        "messages": [
            HumanMessage(prompt),
            ToolMessage(content=json.dumps(payload), tool_call_id="stations"),
        ],
        "executed_tool_calls": (
            {"tool": "list_stations", "arguments": {}, "tool_call_id": "stations"},
        ),
        "response_language": language,
    }


@pytest.mark.parametrize("count", (0, 2, 4, 6, 8, 20))
@pytest.mark.parametrize("language", ("DE", "EN"))
def test_authorized_inventory_survives_omission_invention_and_reference_cap(
    count, language
):
    state = inventory_state(count, language=language)
    result = _with_station_inventory(
        FinalAgentOutput(answer="S01 and invented S99 are FAULTED."), state
    )
    assert [
        line.split(":")[0][2:]
        for line in result.answer.splitlines()
        if line.startswith("- ")
    ] == [f"S{index + 1:02}" for index in range(count)]
    assert "S99" not in result.answer
    assert "FAULTED" not in result.answer
    if count:
        assert "RUNNING" in result.answer
        assert ("unbekannt" if language == "DE" else "unknown") in result.answer
    references, _ = _derive_structured_references(state)
    assert len(references) <= 12
    if count > 12:
        assert len(references) < count


def test_duplicate_stations_are_presented_once():
    state = inventory_state(1)
    payload = json.loads(state["messages"][-1].content)
    payload["stations"] *= 2
    state["messages"][-1].content = json.dumps(payload)
    assert (
        _with_station_inventory(FinalAgentOutput(answer="summary"), state).answer.count(
            "S01"
        )
        == 1
    )


@pytest.mark.parametrize("language", ("DE", "EN"))
def test_existing_answer_bound_marks_large_inventory_partial(language):
    result = _with_station_inventory(
        FinalAgentOutput(answer="summary"), inventory_state(500, language=language)
    )
    assert len(result.answer) <= 8000
    assert (
        "nicht alle autorisierten Stationen"
        if language == "DE"
        else "not all authorized stations"
    ) in result.answer


@pytest.mark.parametrize(
    "prompt",
    (
        "S01",
        "Welche Produkte kennst du?",
        "welche stationen kennst du S07",
        "welche stationen kennst du SECRET CUSTOMER PLAN",
    ),
)
def test_projection_does_not_broaden_neutral_discovery_intent(prompt):
    output = FinalAgentOutput(answer="original")
    assert _with_station_inventory(output, inventory_state(8, prompt=prompt)) is output


def test_only_matching_executed_observation_can_supply_inventory():
    state = inventory_state(8)
    state["messages"][-1].tool_call_id = "unbound"
    with pytest.raises(FinalAgentOutputContractError):
        _with_station_inventory(FinalAgentOutput(answer="S99"), state)
