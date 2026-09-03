import json
from pathlib import Path

import pytest

from evals.run_retrieval import (
    RetrievalEvalCase,
    aggregate_results,
    load_eval_cases,
    run_retrieval_eval,
    score_retrieval,
)
from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = PROJECT_ROOT / "evals" / "datasets" / "knowledge_retrieval_v1.jsonl"


def retrieval_result(chunk_id: str) -> KnowledgeRetrievalResult:
    document_id = chunk_id.split("::", maxsplit=1)[0]
    return KnowledgeRetrievalResult(
        content=f"Content for {chunk_id}",
        document_id=document_id,
        source=f"{document_id}.md",
        chunk_id=chunk_id,
        relevance_score=1.0,
    )


def eval_case(
    *,
    case_id: str = "case-1",
    expected_chunk_ids: tuple[str, ...] = ("doc::chunk-001",),
) -> RetrievalEvalCase:
    return RetrievalEvalCase(
        case_id=case_id,
        query=f"Query for {case_id}",
        expected_relevant_chunk_ids=expected_chunk_ids,
    )


def test_load_eval_cases_parses_structured_ground_truth(tmp_path: Path) -> None:
    dataset_path = tmp_path / "cases.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "case_id": "multiple",
                "query": "E-STOP-17 at S04",
                "expected_relevant_chunk_ids": [
                    "error_codes::chunk-002",
                    "station_s04::chunk-002",
                ],
            }
        ),
        encoding="utf-8",
    )

    cases = load_eval_cases(dataset_path)

    assert cases[0].case_id == "multiple"
    assert cases[0].expected_relevant_chunk_ids == (
        "error_codes::chunk-002",
        "station_s04::chunk-002",
    )


def test_load_eval_cases_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    dataset_path = tmp_path / "cases.jsonl"
    raw_case = {
        "case_id": "duplicate",
        "query": "S04",
        "expected_relevant_chunk_ids": ["station_s04::chunk-001"],
    }
    dataset_path.write_text(
        f"{json.dumps(raw_case)}\n{json.dumps(raw_case)}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate eval case_id: duplicate"):
        load_eval_cases(dataset_path)


def test_versioned_dataset_contains_representative_cases() -> None:
    cases = load_eval_cases(DATASET_PATH)

    assert len(cases) == 10
    assert len({case.case_id for case in cases}) == 10
    assert any("E-STOP-17" in case.query for case in cases)
    assert any("S04" in case.query for case in cases)
    assert any(len(case.expected_relevant_chunk_ids) > 1 for case in cases)


def test_hit_at_one_requires_relevant_first_result() -> None:
    case = eval_case(expected_chunk_ids=("relevant::chunk-001",))

    result = score_retrieval(
        case,
        (
            retrieval_result("irrelevant::chunk-001"),
            retrieval_result("relevant::chunk-001"),
        ),
        k=3,
    )

    assert result.hit_at_1 is False
    assert result.hit_at_k is True
    assert [item.chunk_id for item in result.actual_ranking] == [
        "irrelevant::chunk-001",
        "relevant::chunk-001",
    ]
    assert all(item.relevance_score == 1.0 for item in result.actual_ranking)


def test_recall_at_k_counts_all_expected_relevant_chunks() -> None:
    case = eval_case(
        expected_chunk_ids=("doc::chunk-001", "doc::chunk-002"),
    )

    result = score_retrieval(
        case,
        (retrieval_result("doc::chunk-001"),),
        k=3,
    )

    assert result.hit_at_k is True
    assert result.recall_at_k == 0.5


def test_scoring_only_considers_first_k_results() -> None:
    case = eval_case(expected_chunk_ids=("relevant::chunk-001",))

    result = score_retrieval(
        case,
        (
            retrieval_result("first::chunk-001"),
            retrieval_result("second::chunk-001"),
            retrieval_result("relevant::chunk-001"),
        ),
        k=2,
    )

    assert result.actual_chunk_ids == (
        "first::chunk-001",
        "second::chunk-001",
    )
    assert result.hit_at_k is False
    assert result.recall_at_k == 0.0


def test_aggregate_results_calculates_hit_rates_and_macro_recall() -> None:
    first_case = eval_case(case_id="first")
    second_case = eval_case(
        case_id="second",
        expected_chunk_ids=("doc::chunk-001", "doc::chunk-002"),
    )
    results = (
        score_retrieval(
            first_case,
            (retrieval_result("doc::chunk-001"),),
            k=3,
        ),
        score_retrieval(
            second_case,
            (
                retrieval_result("irrelevant::chunk-001"),
                retrieval_result("doc::chunk-001"),
            ),
            k=3,
        ),
    )

    report = aggregate_results(
        dataset="test.jsonl",
        knowledge_base="knowledge_base",
        strategy="simple",
        k=3,
        results=results,
    )

    assert report.hit_rate_at_1 == 0.5
    assert report.strategy == "simple"
    assert report.hit_rate_at_k == 1.0
    assert report.mean_recall_at_k == 0.75
    assert report.missed_at_1_case_ids == ("second",)
    assert report.missed_at_k_case_ids == ()
    assert report.incomplete_recall_at_k_case_ids == ("second",)
    assert report.failed_case_ids == ("second",)


def test_run_retrieval_eval_uses_requested_k_for_each_case() -> None:
    cases = (eval_case(case_id="first"), eval_case(case_id="second"))
    requests: list[tuple[str, int]] = []

    def search(query: str, limit: int) -> tuple[KnowledgeRetrievalResult, ...]:
        requests.append((query, limit))
        return (retrieval_result("doc::chunk-001"),)

    report = run_retrieval_eval(
        cases=cases,
        search=search,
        dataset="test.jsonl",
        knowledge_base="knowledge_base",
        strategy="idf",
        k=3,
    )

    assert requests == [(case.query, 3) for case in cases]
    assert report.total_cases == 2
    assert report.strategy == "idf"
    assert report.hit_rate_at_1 == 1.0
