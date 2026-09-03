import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
    InMemoryIdfKnowledgeRetriever,
    InMemoryLexicalKnowledgeRetriever,
    load_markdown_chunks,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_PATH = (
    PROJECT_ROOT / "evals" / "datasets" / "knowledge_retrieval_v1.jsonl"
)
DEFAULT_KNOWLEDGE_BASE_PATH = PROJECT_ROOT / "knowledge_base"
DEFAULT_K = 3
RetrievalStrategy = Literal["simple", "idf"]


class RetrievalEvalCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    query: str
    expected_relevant_chunk_ids: tuple[str, ...]

    @field_validator("case_id", "query")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Value must not be empty")
        return normalized_value

    @field_validator("expected_relevant_chunk_ids")
    @classmethod
    def validate_expected_chunks(cls, chunk_ids: tuple[str, ...]) -> tuple[str, ...]:
        normalized_chunk_ids = tuple(chunk_id.strip() for chunk_id in chunk_ids)
        if not normalized_chunk_ids or any(
            not chunk_id for chunk_id in normalized_chunk_ids
        ):
            raise ValueError(
                "expected_relevant_chunk_ids must contain non-empty values"
            )
        if len(set(normalized_chunk_ids)) != len(normalized_chunk_ids):
            raise ValueError("expected_relevant_chunk_ids must be unique")
        return normalized_chunk_ids


class RankedRetrievalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    relevance_score: float | None


class RetrievalEvalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    query: str
    expected_relevant_chunk_ids: tuple[str, ...]
    actual_chunk_ids: tuple[str, ...]
    actual_ranking: tuple[RankedRetrievalResult, ...]
    hit_at_1: bool
    hit_at_k: bool
    recall_at_k: float


class RetrievalEvalReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset: str
    knowledge_base: str
    strategy: RetrievalStrategy
    k: int
    total_cases: int
    hits_at_1: int
    hits_at_k: int
    hit_rate_at_1: float
    hit_rate_at_k: float
    mean_recall_at_k: float
    missed_at_1_case_ids: tuple[str, ...]
    missed_at_k_case_ids: tuple[str, ...]
    incomplete_recall_at_k_case_ids: tuple[str, ...]
    failed_case_ids: tuple[str, ...]
    results: tuple[RetrievalEvalResult, ...]


def load_eval_cases(path: Path) -> tuple[RetrievalEvalCase, ...]:
    cases: list[RetrievalEvalCase] = []
    case_ids: set[str] = set()

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            raw_case: Any = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON on dataset line {line_number}") from error
        try:
            case = RetrievalEvalCase.model_validate(raw_case)
        except ValidationError as error:
            raise ValueError(
                f"Invalid eval case on dataset line {line_number}"
            ) from error
        if case.case_id in case_ids:
            raise ValueError(f"Duplicate eval case_id: {case.case_id}")
        case_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise ValueError("Eval dataset must contain at least one case")
    return tuple(cases)


def score_retrieval(
    case: RetrievalEvalCase,
    results: Sequence[KnowledgeRetrievalResult],
    *,
    k: int,
) -> RetrievalEvalResult:
    if k < 1:
        raise ValueError("k must be at least 1")

    actual_chunk_ids = tuple(result.chunk_id for result in results[:k])
    expected_chunk_ids = set(case.expected_relevant_chunk_ids)
    retrieved_chunk_ids = set(actual_chunk_ids)
    relevant_retrieved = expected_chunk_ids & retrieved_chunk_ids
    return RetrievalEvalResult(
        case_id=case.case_id,
        query=case.query,
        expected_relevant_chunk_ids=case.expected_relevant_chunk_ids,
        actual_chunk_ids=actual_chunk_ids,
        actual_ranking=tuple(
            RankedRetrievalResult(
                chunk_id=result.chunk_id,
                relevance_score=result.relevance_score,
            )
            for result in results[:k]
        ),
        hit_at_1=bool(actual_chunk_ids and actual_chunk_ids[0] in expected_chunk_ids),
        hit_at_k=bool(relevant_retrieved),
        recall_at_k=len(relevant_retrieved) / len(expected_chunk_ids),
    )


def aggregate_results(
    *,
    dataset: str,
    knowledge_base: str,
    strategy: RetrievalStrategy,
    k: int,
    results: Sequence[RetrievalEvalResult],
) -> RetrievalEvalReport:
    if not results:
        raise ValueError("Cannot aggregate an empty eval result set")

    total_cases = len(results)
    hits_at_1 = sum(result.hit_at_1 for result in results)
    hits_at_k = sum(result.hit_at_k for result in results)
    return RetrievalEvalReport(
        dataset=dataset,
        knowledge_base=knowledge_base,
        strategy=strategy,
        k=k,
        total_cases=total_cases,
        hits_at_1=hits_at_1,
        hits_at_k=hits_at_k,
        hit_rate_at_1=hits_at_1 / total_cases,
        hit_rate_at_k=hits_at_k / total_cases,
        mean_recall_at_k=(sum(result.recall_at_k for result in results) / total_cases),
        missed_at_1_case_ids=tuple(
            result.case_id for result in results if not result.hit_at_1
        ),
        missed_at_k_case_ids=tuple(
            result.case_id for result in results if not result.hit_at_k
        ),
        incomplete_recall_at_k_case_ids=tuple(
            result.case_id for result in results if result.recall_at_k < 1.0
        ),
        failed_case_ids=tuple(
            result.case_id
            for result in results
            if not result.hit_at_1 or result.recall_at_k < 1.0
        ),
        results=tuple(results),
    )


def run_retrieval_eval(
    *,
    cases: Sequence[RetrievalEvalCase],
    search: Callable[[str, int], tuple[KnowledgeRetrievalResult, ...]],
    dataset: str,
    knowledge_base: str,
    strategy: RetrievalStrategy,
    k: int = DEFAULT_K,
) -> RetrievalEvalReport:
    results = tuple(score_retrieval(case, search(case.query, k), k=k) for case in cases)
    return aggregate_results(
        dataset=dataset,
        knowledge_base=knowledge_base,
        strategy=strategy,
        k=k,
        results=results,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the local lexical knowledge-retrieval baseline."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument(
        "--knowledge-base",
        type=Path,
        default=DEFAULT_KNOWLEDGE_BASE_PATH,
    )
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument(
        "--strategy",
        choices=("simple", "idf"),
        default="simple",
        help="Retrieval implementation to evaluate.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path; evals/results is ignored by Git.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    dataset_path = _resolve_path(args.dataset)
    knowledge_base_path = _resolve_path(args.knowledge_base)
    cases = load_eval_cases(dataset_path)
    chunks = load_markdown_chunks(knowledge_base_path)
    retriever = _create_retriever(args.strategy, chunks)
    report = run_retrieval_eval(
        cases=cases,
        search=retriever.search,
        dataset=dataset_path.name,
        knowledge_base=knowledge_base_path.name,
        strategy=args.strategy,
        k=args.k,
    )

    serialized_report = report.model_dump_json(indent=2)
    print(serialized_report)
    if args.output is not None:
        output_path = _resolve_path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f"{serialized_report}\n", encoding="utf-8")


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _create_retriever(
    strategy: RetrievalStrategy,
    chunks: tuple[KnowledgeRetrievalResult, ...],
) -> InMemoryLexicalKnowledgeRetriever | InMemoryIdfKnowledgeRetriever:
    if strategy == "simple":
        return InMemoryLexicalKnowledgeRetriever(chunks)
    return InMemoryIdfKnowledgeRetriever(chunks)


if __name__ == "__main__":
    main()
