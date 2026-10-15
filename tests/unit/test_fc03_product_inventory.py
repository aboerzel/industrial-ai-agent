"""Primary discovery inventory is independent of model prose and reference slots."""

import json

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from industrial_ai_agent.agent.agent_run import (
    FinalAgentOutput,
    FinalAgentOutputContractError,
)
from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    _derive_structured_references,
    _with_product_inventory,
)


def inventory_state(count, *, prompt="Welche Produkte kennst du?", language="DE"):
    products = [
        {
            "product_id": f"P{2000 + index}",
            "latest_station_id": f"S{index % 8 + 1:02}",
            "latest_status": "FAILED" if index % 2 else None,
            "latest_error_code": f"FAULT-{index}",
            "classification": 0,
        }
        for index in range(count)
    ]
    return {
        "messages": [
            HumanMessage(prompt),
            ToolMessage(
                content=json.dumps({"products": products, "classification": 0}),
                tool_call_id="inventory",
            ),
        ],
        "executed_tool_calls": (
            {"tool": "list_products", "arguments": {}, "tool_call_id": "inventory"},
        ),
        "response_language": language,
    }


@pytest.mark.parametrize("count", (0, 9, 11))
@pytest.mark.parametrize("language", ("DE", "EN"))
def test_complete_typed_inventory_survives_sparse_or_invented_model_prose(
    count, language
):
    state = inventory_state(count, language=language)
    result = _with_product_inventory(FinalAgentOutput(answer="P2000. P9999."), state)
    assert [
        line.split(":")[0][2:]
        for line in result.answer.splitlines()
        if line.startswith("- ")
    ] == [f"P{2000 + index}" for index in range(count)]
    assert "P9999" not in result.answer
    if count:
        assert "FAILED" in result.answer
        assert ("unbekannt" if language == "DE" else "unknown") in result.answer
    identifiers, _ = _derive_structured_references(state)
    assert len(identifiers) <= 12
    assert all(reference.value != "P9999" for reference in identifiers)
    if count > 6:
        assert (
            len(
                [
                    reference
                    for reference in identifiers
                    if reference.type.value == "product"
                ]
            )
            < count
        )


@pytest.mark.parametrize("language", ("DE", "EN"))
def test_existing_answer_size_bound_reports_partial_inventory_explicitly(language):
    result = _with_product_inventory(
        FinalAgentOutput(answer="summary"), inventory_state(1000, language=language)
    )
    assert len(result.answer) <= 8000
    assert (
        "nicht alle autorisierten Produkte"
        if language == "DE"
        else "not all authorized products"
    ) in result.answer
    assert "P2999" not in result.answer


@pytest.mark.parametrize(
    "prompt",
    (
        "Investigate P2000.",
        "Welche Produkte kennst du? P9001 unknown text",
        "Welche Stationen kennst du?",
    ),
)
def test_projection_does_not_broaden_discovery_intent(prompt):
    output = FinalAgentOutput(answer="original response")
    assert _with_product_inventory(output, inventory_state(11, prompt=prompt)) is output


def test_projection_uses_only_matching_executed_call_and_not_unbound_messages():
    state = inventory_state(11)
    state["messages"][-1].tool_call_id = "unmatched"
    with pytest.raises(FinalAgentOutputContractError):
        _with_product_inventory(FinalAgentOutput(answer="P9999"), state)


def test_no_inventory_observation_does_not_invent_products():
    state = inventory_state(11)
    state["executed_tool_calls"] = ()
    output = FinalAgentOutput(answer="original response")
    assert _with_product_inventory(output, state) is output


def test_duplicate_rows_do_not_duplicate_visible_products():
    state = inventory_state(1)
    payload = json.loads(state["messages"][-1].content)
    payload["products"] *= 2
    state["messages"][-1].content = json.dumps(payload)
    result = _with_product_inventory(FinalAgentOutput(answer="summary"), state)
    assert result.answer.count("P2000") == 1
