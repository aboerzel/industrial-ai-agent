import json
from pathlib import Path

import pytest

from evals.run_tool_selection import (
    ToolSelectionEvalCase,
    aggregate_results,
    load_eval_cases,
    run_tool_selection_eval,
    score_tool_selection,
)
from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMResponse,
    LLMToolCall,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = (
    PROJECT_ROOT / "evals" / "datasets" / "troubleshooting_tool_selection_v1.jsonl"
)


def eval_case(
    *,
    case_id: str = "case-1",
    expected_tool: str = "get_product_history",
    expected_arguments: dict[str, object] | None = None,
) -> ToolSelectionEvalCase:
    return ToolSelectionEvalCase(
        case_id=case_id,
        user_input=f"Request for {case_id}",
        expected_tool=expected_tool,
        expected_arguments=(
            expected_arguments
            if expected_arguments is not None
            else {"product_id": "P4711"}
        ),
    )


def llm_response(*tool_calls: LLMToolCall) -> LLMResponse:
    return LLMResponse(
        text=None if tool_calls else "No tool selected.",
        tool_calls=tool_calls,
        finish_reason=(FinishReason.TOOL_CALLS if tool_calls else FinishReason.STOP),
    )


def call(
    name: str, arguments: dict[str, object], call_id: str = "call-1"
) -> LLMToolCall:
    return LLMToolCall(id=call_id, name=name, arguments=arguments)


def test_load_eval_cases_parses_jsonl(tmp_path: Path) -> None:
    dataset_path = tmp_path / "cases.jsonl"
    dataset_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "case_id": "product-case",
                        "user_input": "Show P4711 history",
                        "expected_tool": "get_product_history",
                        "expected_arguments": {"product_id": "P4711"},
                    }
                ),
                "",
                json.dumps(
                    {
                        "case_id": "machine-case",
                        "user_input": "Show S04 status",
                        "expected_tool": "get_machine_status",
                        "expected_arguments": {"station_id": "S04"},
                    }
                ),
            )
        ),
        encoding="utf-8",
    )

    cases = load_eval_cases(dataset_path)

    assert [case.case_id for case in cases] == ["product-case", "machine-case"]
    assert cases[1].expected_arguments == {"station_id": "S04"}


def test_load_eval_cases_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    dataset_path = tmp_path / "cases.jsonl"
    raw_case = {
        "case_id": "duplicate",
        "user_input": "Show P4711 history",
        "expected_tool": "get_product_history",
        "expected_arguments": {"product_id": "P4711"},
    }
    dataset_path.write_text(
        f"{json.dumps(raw_case)}\n{json.dumps(raw_case)}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate eval case_id: duplicate"):
        load_eval_cases(dataset_path)


def test_versioned_dataset_contains_balanced_representative_cases() -> None:
    cases = load_eval_cases(DATASET_PATH)

    assert len(cases) == 12
    assert len({case.case_id for case in cases}) == 12
    assert sum(case.expected_tool == "get_product_history" for case in cases) == 6
    assert sum(case.expected_tool == "get_machine_status" for case in cases) == 6
    assert len({next(iter(case.expected_arguments.values())) for case in cases}) == 12


def test_score_tool_selection_accepts_exact_tool_and_arguments() -> None:
    case = eval_case()

    result = score_tool_selection(
        case,
        llm_response(call("get_product_history", {"product_id": "P4711"})),
    )

    assert result.actual_tool == "get_product_history"
    assert result.actual_arguments == {"product_id": "P4711"}
    assert result.tool_selection_correct is True
    assert result.arguments_correct is True
    assert result.error is None


def test_argument_score_requires_correct_tool_and_exact_arguments() -> None:
    case = eval_case()

    wrong_arguments = score_tool_selection(
        case,
        llm_response(call("get_product_history", {"product_id": "P9999"})),
    )
    wrong_tool = score_tool_selection(
        case,
        llm_response(call("get_machine_status", {"product_id": "P4711"})),
    )

    assert wrong_arguments.tool_selection_correct is True
    assert wrong_arguments.arguments_correct is False
    assert wrong_tool.tool_selection_correct is False
    assert wrong_tool.arguments_correct is False


@pytest.mark.parametrize("tool_call_count", [0, 2])
def test_score_tool_selection_rejects_non_single_call_response(
    tool_call_count: int,
) -> None:
    case = eval_case()
    tool_calls = tuple(
        call(
            "get_product_history",
            {"product_id": "P4711"},
            call_id=f"call-{index}",
        )
        for index in range(tool_call_count)
    )

    result = score_tool_selection(case, llm_response(*tool_calls))

    assert result.tool_call_count == tool_call_count
    assert result.tool_selection_correct is False
    assert result.arguments_correct is False
    assert result.error == (
        f"Expected exactly one tool call, received {tool_call_count}"
    )


def test_aggregate_results_calculates_both_accuracies() -> None:
    first_case = eval_case(case_id="first")
    second_case = eval_case(case_id="second")
    third_case = eval_case(case_id="third")
    results = (
        score_tool_selection(
            first_case,
            llm_response(call("get_product_history", {"product_id": "P4711"})),
        ),
        score_tool_selection(
            second_case,
            llm_response(call("get_product_history", {"product_id": "P9999"})),
        ),
        score_tool_selection(
            third_case,
            llm_response(call("get_machine_status", {"station_id": "S04"})),
        ),
    )

    report = aggregate_results(
        dataset="test.jsonl",
        model_profile="local_quality",
        results=results,
    )

    assert report.total_cases == 3
    assert report.correct_tool_selections == 2
    assert report.correct_arguments == 1
    assert report.tool_selection_accuracy == pytest.approx(2 / 3)
    assert report.argument_accuracy == pytest.approx(1 / 3)


def test_run_eval_continues_after_independent_case_failure() -> None:
    cases = (eval_case(case_id="fails"), eval_case(case_id="succeeds"))
    requested_inputs: list[str] = []

    def request_tool_selection(user_input: str) -> LLMResponse:
        requested_inputs.append(user_input)
        if len(requested_inputs) == 1:
            raise RuntimeError("LLM unavailable")
        return llm_response(call("get_product_history", {"product_id": "P4711"}))

    report = run_tool_selection_eval(
        cases=cases,
        request_tool_selection=request_tool_selection,
        dataset="test.jsonl",
        model_profile="local_quality",
        orchestration_path="langgraph",
    )

    assert requested_inputs == [case.user_input for case in cases]
    assert report.total_cases == 2
    assert report.results[0].error == "RuntimeError: LLM unavailable"
    assert report.results[1].arguments_correct is True
    assert report.tool_selection_accuracy == 0.5
    assert report.argument_accuracy == 0.5
    assert report.orchestration_path == "langgraph"
