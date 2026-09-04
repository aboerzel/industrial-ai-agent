import json
from pathlib import Path

import pytest

from evals.run_retrieval import (
    RetrievalEvalCase,
    aggregate_results,
    load_eval_cases,
    run_retrieval_eval,
    score_retrieval,
    validate_eval_cases,
)
from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
    load_markdown_chunks,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = PROJECT_ROOT / "evals" / "datasets" / "knowledge_retrieval_v1.jsonl"
V2_DATASET_PATH = PROJECT_ROOT / "evals" / "datasets" / "knowledge_retrieval_v2.jsonl"
KNOWLEDGE_BASE_PATH = PROJECT_ROOT / "knowledge_base"


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


def test_load_eval_cases_rejects_duplicate_queries(tmp_path: Path) -> None:
    dataset_path = tmp_path / "cases.jsonl"
    first_case = {
        "case_id": "first",
        "query": "S04 status",
        "expected_relevant_chunk_ids": ["station_s04::chunk-001"],
    }
    second_case = {
        "case_id": "second",
        "query": "s04 STATUS",
        "expected_relevant_chunk_ids": ["station_s04::chunk-002"],
    }
    dataset_path.write_text(
        f"{json.dumps(first_case)}\n{json.dumps(second_case)}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate eval query"):
        load_eval_cases(dataset_path)


def test_versioned_dataset_contains_representative_cases() -> None:
    cases = load_eval_cases(DATASET_PATH)

    assert len(cases) == 10
    assert len({case.case_id for case in cases}) == 10
    assert any("E-STOP-17" in case.query for case in cases)
    assert any("S04" in case.query for case in cases)
    assert any(len(case.expected_relevant_chunk_ids) > 1 for case in cases)


def test_v2_dataset_is_valid_and_references_existing_chunks() -> None:
    cases = load_eval_cases(V2_DATASET_PATH)
    chunks = load_markdown_chunks(KNOWLEDGE_BASE_PATH)

    validate_eval_cases(cases, chunks)

    assert len(cases) == 28
    assert len({case.case_id for case in cases}) == 28
    assert all(case.query for case in cases)
    assert all(case.expected_relevant_chunk_ids for case in cases)


def test_v2_preserves_v1_queries_and_ground_truth() -> None:
    v1_cases = load_eval_cases(DATASET_PATH)
    v2_cases_by_id = {case.case_id: case for case in load_eval_cases(V2_DATASET_PATH)}

    for v1_case in v1_cases:
        v2_case = v2_cases_by_id[v1_case.case_id]
        assert v2_case.query == v1_case.query
        assert (
            v2_case.expected_relevant_chunk_ids == v1_case.expected_relevant_chunk_ids
        )


def test_v2_dataset_covers_required_categories() -> None:
    cases = load_eval_cases(V2_DATASET_PATH)
    actual_categories = {category for case in cases for category in case.categories}

    assert actual_categories == {
        "exact_identifier",
        "natural_language",
        "rare_term",
        "common_term_ambiguity",
        "multi_relevance",
        "short_query",
        "longer_technical_query",
        "cross_document_ambiguity",
        "term_frequency_sensitive",
        "length_sensitive",
    }


def test_v2_dataset_parses_at_least_five_multi_relevance_cases() -> None:
    cases = load_eval_cases(V2_DATASET_PATH)
    multi_relevance_cases = tuple(
        case for case in cases if "multi_relevance" in case.categories
    )

    assert len(multi_relevance_cases) >= 5
    assert all(
        len(case.expected_relevant_chunk_ids) > 1 for case in multi_relevance_cases
    )


def test_validate_eval_cases_rejects_unknown_chunk_ids() -> None:
    case = eval_case(expected_chunk_ids=("missing::chunk-001",))

    with pytest.raises(ValueError, match="references unknown chunk_ids"):
        validate_eval_cases((case,), (retrieval_result("doc::chunk-001"),))


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
    assert result.categories == ()


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
    assert report.category_reports == ()


def test_aggregate_results_reports_metrics_by_category() -> None:
    first_case = RetrievalEvalCase(
        case_id="first",
        query="First query",
        expected_relevant_chunk_ids=("doc::chunk-001",),
        categories=("short_query",),
    )
    second_case = RetrievalEvalCase(
        case_id="second",
        query="Second query",
        expected_relevant_chunk_ids=("doc::chunk-002",),
        categories=("short_query", "exact_identifier"),
    )
    results = (
        score_retrieval(
            first_case,
            (retrieval_result("doc::chunk-001"),),
            k=3,
        ),
        score_retrieval(
            second_case,
            (retrieval_result("other::chunk-001"),),
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

    category_reports = {item.category: item for item in report.category_reports}
    assert category_reports["short_query"].total_cases == 2
    assert category_reports["short_query"].hit_rate_at_1 == 0.5
    assert category_reports["exact_identifier"].missed_at_k_case_ids == ("second",)


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
