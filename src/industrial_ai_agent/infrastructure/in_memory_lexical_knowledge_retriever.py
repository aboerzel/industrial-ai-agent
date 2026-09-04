import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from math import log
from pathlib import Path

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.IGNORECASE)
DEFAULT_BM25_K1 = 1.5
DEFAULT_BM25_B = 0.75


@dataclass(frozen=True, slots=True)
class _IndexedChunk:
    result: KnowledgeRetrievalResult
    terms: frozenset[str]
    term_frequencies: Counter[str]
    length: int


class InMemoryLexicalKnowledgeRetriever:
    def __init__(self, chunks: Iterable[KnowledgeRetrievalResult]) -> None:
        self._index = _build_index(chunks)

    def search(
        self,
        query: str,
        limit: int,
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        query_terms = _prepare_query(query, limit)

        scored_results = (
            (
                len(query_terms & indexed_chunk.terms) / len(query_terms),
                indexed_chunk.result,
            )
            for indexed_chunk in self._index
        )
        return _rank_results(scored_results, limit)


class InMemoryIdfKnowledgeRetriever:
    def __init__(self, chunks: Iterable[KnowledgeRetrievalResult]) -> None:
        self._index = _build_index(chunks)
        if not self._index:
            raise ValueError("IDF index must contain at least one chunk")

        self._document_frequencies = Counter(
            term for indexed_chunk in self._index for term in indexed_chunk.terms
        )

    def document_frequency(self, term: str) -> int:
        return self._document_frequencies[_normalize_single_term(term)]

    def inverse_document_frequency(self, term: str) -> float:
        return smoothed_inverse_document_frequency(
            total_chunks=len(self._index),
            document_frequency=self.document_frequency(term),
        )

    def search(
        self,
        query: str,
        limit: int,
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        query_terms = _prepare_query(query, limit)

        query_weights = {
            term: self.inverse_document_frequency(term) for term in query_terms
        }
        total_query_weight = sum(query_weights.values())
        scored_results = (
            (
                sum(
                    weight
                    for term, weight in query_weights.items()
                    if term in indexed_chunk.terms
                )
                / total_query_weight,
                indexed_chunk.result,
            )
            for indexed_chunk in self._index
        )
        return _rank_results(scored_results, limit)


class InMemoryBm25KnowledgeRetriever:
    def __init__(
        self,
        chunks: Iterable[KnowledgeRetrievalResult],
        *,
        k1: float = DEFAULT_BM25_K1,
        b: float = DEFAULT_BM25_B,
    ) -> None:
        if k1 <= 0:
            raise ValueError("k1 must be greater than 0")
        if b < 0 or b > 1:
            raise ValueError("b must be between 0 and 1")

        self._index = _build_index(chunks)
        if not self._index:
            raise ValueError("BM25 index must contain at least one chunk")

        self.k1 = k1
        self.b = b
        self._document_frequencies = Counter(
            term for indexed_chunk in self._index for term in indexed_chunk.terms
        )
        self._average_chunk_length = sum(
            indexed_chunk.length for indexed_chunk in self._index
        ) / len(self._index)
        if self._average_chunk_length <= 0:
            raise ValueError("BM25 index must contain searchable tokens")

    @property
    def average_chunk_length(self) -> float:
        return self._average_chunk_length

    def document_frequency(self, term: str) -> int:
        return self._document_frequencies[_normalize_single_term(term)]

    def term_frequency(self, chunk_id: str, term: str) -> int:
        normalized_term = _normalize_single_term(term)
        for indexed_chunk in self._index:
            if indexed_chunk.result.chunk_id == chunk_id:
                return indexed_chunk.term_frequencies[normalized_term]
        raise ValueError(f"Unknown chunk_id: {chunk_id}")

    def inverse_document_frequency(self, term: str) -> float:
        return bm25_inverse_document_frequency(
            total_chunks=len(self._index),
            document_frequency=self.document_frequency(term),
        )

    def search(
        self,
        query: str,
        limit: int,
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        query_terms = _prepare_query(query, limit)
        scored_results = (
            (
                sum(
                    self.inverse_document_frequency(term)
                    * bm25_term_frequency_weight(
                        term_frequency=indexed_chunk.term_frequencies[term],
                        chunk_length=indexed_chunk.length,
                        average_chunk_length=self._average_chunk_length,
                        k1=self.k1,
                        b=self.b,
                    )
                    for term in query_terms
                ),
                indexed_chunk.result,
            )
            for indexed_chunk in self._index
        )
        return _rank_results(scored_results, limit)


def bm25_inverse_document_frequency(
    *,
    total_chunks: int,
    document_frequency: int,
) -> float:
    if total_chunks < 1:
        raise ValueError("total_chunks must be at least 1")
    if document_frequency < 0 or document_frequency > total_chunks:
        raise ValueError("document_frequency must be between 0 and total_chunks")
    return log(
        1 + (total_chunks - document_frequency + 0.5) / (document_frequency + 0.5)
    )


def bm25_term_frequency_weight(
    *,
    term_frequency: int,
    chunk_length: int,
    average_chunk_length: float,
    k1: float = DEFAULT_BM25_K1,
    b: float = DEFAULT_BM25_B,
) -> float:
    if term_frequency < 0:
        raise ValueError("term_frequency must not be negative")
    if chunk_length < 0:
        raise ValueError("chunk_length must not be negative")
    if average_chunk_length <= 0:
        raise ValueError("average_chunk_length must be greater than 0")
    if k1 <= 0:
        raise ValueError("k1 must be greater than 0")
    if b < 0 or b > 1:
        raise ValueError("b must be between 0 and 1")
    if term_frequency == 0:
        return 0.0

    length_normalization = 1 - b + b * chunk_length / average_chunk_length
    return (term_frequency * (k1 + 1)) / (term_frequency + k1 * length_normalization)


def smoothed_inverse_document_frequency(
    *,
    total_chunks: int,
    document_frequency: int,
) -> float:
    if total_chunks < 1:
        raise ValueError("total_chunks must be at least 1")
    if document_frequency < 0 or document_frequency > total_chunks:
        raise ValueError("document_frequency must be between 0 and total_chunks")
    return log((total_chunks + 1) / (document_frequency + 1)) + 1


def _build_index(
    chunks: Iterable[KnowledgeRetrievalResult],
) -> tuple[_IndexedChunk, ...]:
    index: list[_IndexedChunk] = []
    for chunk in chunks:
        tokens = _tokenize(chunk.content)
        term_frequencies = Counter(tokens)
        index.append(
            _IndexedChunk(
                result=chunk,
                terms=frozenset(term_frequencies),
                term_frequencies=term_frequencies,
                length=len(tokens),
            )
        )
    return tuple(index)


def _prepare_query(query: str, limit: int) -> frozenset[str]:
    if limit < 1:
        raise ValueError("limit must be at least 1")

    query_terms = frozenset(_tokenize(query))
    if not query_terms:
        raise ValueError("query must contain at least one searchable token")
    return query_terms


def _rank_results(
    scored_results: Iterable[tuple[float, KnowledgeRetrievalResult]],
    limit: int,
) -> tuple[KnowledgeRetrievalResult, ...]:
    ranked_results = sorted(
        (item for item in scored_results if item[0] > 0),
        key=lambda item: (-item[0], item[1].chunk_id),
    )
    return tuple(
        result.model_copy(update={"relevance_score": score})
        for score, result in ranked_results[:limit]
    )


def load_markdown_chunks(directory: Path) -> tuple[KnowledgeRetrievalResult, ...]:
    if not directory.is_dir():
        raise ValueError(f"Knowledge base directory does not exist: {directory}")

    paths = sorted(
        directory.glob("*.md"), key=lambda document_path: document_path.name.casefold()
    )
    if not paths:
        raise ValueError("Knowledge base must contain at least one Markdown document")

    chunks: list[KnowledgeRetrievalResult] = []
    document_ids: set[str] = set()
    for path in paths:
        document_id = path.stem
        if document_id in document_ids:
            raise ValueError(f"Duplicate document_id: {document_id}")
        document_ids.add(document_id)

        sections = _split_markdown_sections(path.read_text(encoding="utf-8"))
        for position, (title, content) in enumerate(sections, start=1):
            chunks.append(
                KnowledgeRetrievalResult(
                    content=content,
                    document_id=document_id,
                    source=path.relative_to(directory).as_posix(),
                    chunk_id=f"{document_id}::chunk-{position:03d}",
                    metadata={"title": title, "format": "markdown"},
                )
            )

    return tuple(chunks)


def _split_markdown_sections(document: str) -> tuple[tuple[str, str], ...]:
    normalized_document = _normalize_document(document)
    if not normalized_document:
        raise ValueError("Knowledge document must not be empty")

    sections: list[tuple[str, str]] = []
    current_lines: list[str] = []
    current_title = "Untitled section"

    for line in normalized_document.splitlines():
        if line.startswith("#"):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
                current_lines = []
            current_title = line.lstrip("#").strip() or "Untitled section"
        current_lines.append(line)

    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))

    return tuple(sections)


def _normalize_document(document: str) -> str:
    normalized_newlines = document.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized_newlines.splitlines()).strip()


def _tokenize(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in _TOKEN_PATTERN.finditer(text))


def _normalize_single_term(term: str) -> str:
    normalized_terms = _tokenize(term)
    if len(normalized_terms) != 1:
        raise ValueError("term must contain exactly one searchable token")
    return normalized_terms[0]
