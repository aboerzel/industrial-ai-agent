import json
from pathlib import Path

import pytest

from evals.run_trajectory import (
    TrajectoryEvalCase,
    aggregate_results,
    load_eval_cases,
    run_trajectory_eval,
    score_trajectory,
)
from industrial_ai_agent.agent.agent_run import (
    AgentRunResult,
    AgentRunStatus,
    ExecutedToolCall,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = (
    PROJECT_ROOT / "evals" / "datasets" / "troubleshooting_trajectory_v1.jsonl"
)
KNOWLEDGE_MCP_DATASET_PATH = (
    PROJECT_ROOT
    / "evals"
    / "datasets"
    / "troubleshooting_mcp_knowledge_trajectory_v1.jsonl"
)


def product_call(product_id: str = "P4711") -> ExecutedToolCall:
    return ExecutedToolCall(
        tool="get_product_history",
        arguments={"product_id": product_id},
    )


def machine_call(station_id: str = "S04") -> ExecutedToolCall:
    return ExecutedToolCall(
        tool="get_machine_status",
        arguments={"station_id": station_id},
    )


def eval_case(
    *,
    case_id: str = "case-1",
    expected_trajectory: tuple[ExecutedToolCall, ...] = (),
    expected_status: AgentRunStatus = AgentRunStatus.SUCCESS,
) -> TrajectoryEvalCase:
    return TrajectoryEvalCase(
        case_id=case_id,
        user_input=f"Request for {case_id}",
        expected_trajectory=expected_trajectory,
        expected_status=expected_status,
    )


def run_result(
    *trajectory: ExecutedToolCall,
    status: AgentRunStatus = AgentRunStatus.SUCCESS,
) -> AgentRunResult:
    return AgentRunResult(
        status=status,
        final_answer="Investigation complete."
        if status is AgentRunStatus.SUCCESS
        else None,
        tool_call_count=len(trajectory),
        executed_tool_calls=trajectory,
    )


def test_load_eval_cases_parses_structured_trajectory(tmp_path: Path) -> None:
    dataset_path = tmp_path / "cases.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "multi-step",
                "user_input": "Investigate P4711 and its station",
                "expected_trajectory": [
                    {
                        "tool": "get_product_history",
                        "arguments": {"product_id": "P4711"},
                    },
                    {
                        "tool": "get_machine_status",
                        "arguments": {"station_id": "S04"},
                    },
                ],
                "expected_status": "SUCCESS",
            }
        ),
        encoding="utf-8",
    )

    cases = load_eval_cases(dataset_path)

    assert cases == (
        eval_case(
            case_id="multi-step",
            expected_trajectory=(product_call(), machine_call()),
        ).model_copy(update={"user_input": "Investigate P4711 and its station"}),
    )


def test_load_eval_cases_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    dataset_path = tmp_path / "cases.jsonl"
    raw_case = {
        "case_id": "duplicate",
        "user_input": "Show S04 status",
        "expected_trajectory": [
            {
                "tool": "get_machine_status",
                "arguments": {"station_id": "S04"},
            }
        ],
        "expected_status": "SUCCESS",
    }
    dataset_path.write_text(
        f"{json.dumps(raw_case)}\n{json.dumps(raw_case)}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate eval case_id: duplicate"):
        load_eval_cases(dataset_path)


def test_versioned_dataset_contains_representative_trajectory_types() -> None:
    cases = load_eval_cases(DATASET_PATH)
    trajectory_lengths = [len(case.expected_trajectory) for case in cases]

    assert len(cases) == 10
    assert len({case.case_id for case in cases}) == 10
    assert 0 in trajectory_lengths
    assert 1 in trajectory_lengths
    assert 2 in trajectory_lengths
    assert all(case.expected_status is AgentRunStatus.SUCCESS for case in cases)


def test_knowledge_mcp_dataset_has_an_explicit_three_tool_trajectory() -> None:
    cases = load_eval_cases(KNOWLEDGE_MCP_DATASET_PATH)

    assert len(cases) == 1
    assert [call.tool for call in cases[0].expected_trajectory] == [
        "get_product_history",
        "get_machine_status",
        "search_documentation",
    ]
    assert cases[0].expected_trajectory[-1].arguments == {
        "query": "E-STOP-17 at S04",
        "top_k": 3,
    }


def test_exact_two_tool_trajectory_is_fully_correct() -> None:
    case = eval_case(expected_trajectory=(product_call(), machine_call()))

    result = score_trajectory(case, run_result(product_call(), machine_call()))

    assert result.exact_trajectory_correct is True
    assert result.positionally_correct_tool_calls == 2
    assert result.tool_call_slots == 2
    assert result.termination_correct is True
    assert result.task_success is True


def test_wrong_order_is_not_an_exact_trajectory() -> None:
    case = eval_case(expected_trajectory=(product_call(), machine_call()))

    result = score_trajectory(case, run_result(machine_call(), product_call()))

    assert result.exact_trajectory_correct is False
    assert result.positionally_correct_tool_calls == 0
    assert result.task_success is False


def test_wrong_tool_name_fails_at_that_position() -> None:
    case = eval_case(expected_trajectory=(product_call(),))

    result = score_trajectory(case, run_result(machine_call()))

    assert result.positionally_correct_tool_calls == 0
    assert result.exact_trajectory_correct is False


def test_wrong_arguments_are_not_positionally_correct() -> None:
    case = eval_case(expected_trajectory=(product_call(), machine_call()))

    result = score_trajectory(
        case,
        run_result(product_call("P9999"), machine_call()),
    )

    assert result.positionally_correct_tool_calls == 1
    assert result.exact_trajectory_correct is False


def test_missing_tool_call_is_penalized() -> None:
    case = eval_case(expected_trajectory=(product_call(), machine_call()))

    result = score_trajectory(case, run_result(product_call()))

    assert result.expected_tool_calls == 2
    assert result.actual_tool_calls == 1
    assert result.positionally_correct_tool_calls == 1
    assert result.tool_call_slots == 2
    assert result.exact_trajectory_correct is False


def test_additional_tool_call_is_penalized() -> None:
    case = eval_case(expected_trajectory=(product_call(), machine_call()))

    result = score_trajectory(
        case,
        run_result(product_call(), machine_call(), machine_call("S12")),
    )

    assert result.expected_tool_calls == 2
    assert result.actual_tool_calls == 3
    assert result.positionally_correct_tool_calls == 2
    assert result.tool_call_slots == 3
    assert result.exact_trajectory_correct is False


def test_termination_score_accepts_matching_status() -> None:
    trajectory = (product_call(), machine_call(), product_call(), machine_call())
    case = eval_case(
        expected_trajectory=trajectory,
        expected_status=AgentRunStatus.LIMIT_REACHED,
    )

    result = score_trajectory(
        case,
        run_result(*trajectory, status=AgentRunStatus.LIMIT_REACHED),
    )

    assert result.termination_correct is True


def test_termination_score_rejects_different_status() -> None:
    case = eval_case(
        expected_trajectory=(product_call(),),
        expected_status=AgentRunStatus.LIMIT_REACHED,
    )

    result = score_trajectory(case, run_result(product_call()))

    assert result.exact_trajectory_correct is True
    assert result.termination_correct is False
    assert result.task_success is False


def test_task_success_requires_trajectory_and_termination() -> None:
    case = eval_case(expected_trajectory=(product_call(), machine_call()))

    result = score_trajectory(case, run_result(product_call()))

    assert result.termination_correct is True
    assert result.exact_trajectory_correct is False
    assert result.task_success is False


def test_zero_tool_trajectory_can_succeed() -> None:
    result = score_trajectory(eval_case(), run_result())

    assert result.expected_tool_calls == 0
    assert result.actual_tool_calls == 0
    assert result.tool_call_slots == 0
    assert result.exact_trajectory_correct is True
    assert result.task_success is True


def test_aggregate_results_calculates_all_metrics_and_count_differences() -> None:
    exact_case = eval_case(
        case_id="exact",
        expected_trajectory=(product_call(), machine_call()),
    )
    missing_case = eval_case(
        case_id="missing",
        expected_trajectory=(product_call(), machine_call()),
    )
    additional_case = eval_case(
        case_id="additional",
        expected_trajectory=(product_call(),),
    )
    results = (
        score_trajectory(exact_case, run_result(product_call(), machine_call())),
        score_trajectory(missing_case, run_result(product_call())),
        score_trajectory(
            additional_case,
            run_result(product_call(), machine_call()),
        ),
    )

    report = aggregate_results(
        dataset="test.jsonl",
        model_profile="local_quality",
        results=results,
    )

    assert report.total_cases == 3
    assert report.task_success_rate == pytest.approx(1 / 3)
    assert report.exact_trajectory_accuracy == pytest.approx(1 / 3)
    assert report.tool_call_accuracy == pytest.approx(4 / 6)
    assert report.termination_accuracy == 1.0
    assert report.cases_with_missing_tool_calls == ("missing",)
    assert report.cases_with_additional_tool_calls == ("additional",)
    assert report.failed_case_ids == ("missing", "additional")


def test_run_eval_executes_cases_independently_and_records_final_answer() -> None:
    cases = (
        eval_case(case_id="fails", expected_trajectory=(product_call(),)),
        eval_case(case_id="succeeds", expected_trajectory=(machine_call(),)),
    )

    def run_agent(user_input: str) -> AgentRunResult:
        if user_input == "Request for fails":
            raise RuntimeError("LLM unavailable")
        return run_result(machine_call())

    report = run_trajectory_eval(
        cases=cases,
        run_agent=run_agent,
        dataset="test.jsonl",
        model_profile="local_quality",
        orchestration_path="langgraph",
    )

    assert report.results[0].error == "RuntimeError: LLM unavailable"
    assert report.results[1].final_answer == "Investigation complete."
    assert report.task_success_rate == 0.5
    assert report.orchestration_path == "langgraph"


def test_agent_run_result_exposes_provider_independent_executed_trajectory() -> None:
    result = run_result(product_call(), machine_call())

    assert result.executed_tool_calls == (product_call(), machine_call())
    assert result.model_dump()["executed_tool_calls"] == (
        {"tool": "get_product_history", "arguments": {"product_id": "P4711"}},
        {"tool": "get_machine_status", "arguments": {"station_id": "S04"}},
    )
