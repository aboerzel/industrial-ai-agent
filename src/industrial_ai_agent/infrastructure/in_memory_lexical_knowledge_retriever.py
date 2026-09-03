import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from math import log
from pathlib import Path

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _IndexedChunk:
    result: KnowledgeRetrievalResult
    terms: frozenset[str]


class InMemoryLexicalKnowledgeRetriever:
    def __init__(self, chunks: Iterable[KnowledgeRetrievalResult]) -> None:
        self._index = tuple(
            _IndexedChunk(
                result=chunk,
                terms=frozenset(_tokenize(chunk.content)),
            )
            for chunk in chunks
        )

    def search(
        self,
        query: str,
        limit: int,
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        query_terms = frozenset(_tokenize(query))
        if not query_terms:
            raise ValueError("query must contain at least one searchable token")

        scored_results = (
            (
                len(query_terms & indexed_chunk.terms) / len(query_terms),
                indexed_chunk.result,
            )
            for indexed_chunk in self._index
        )
        ranked_results = sorted(
            (item for item in scored_results if item[0] > 0),
            key=lambda item: (-item[0], item[1].chunk_id),
        )
        return tuple(
            result.model_copy(update={"relevance_score": score})
            for score, result in ranked_results[:limit]
        )


class InMemoryIdfKnowledgeRetriever:
    def __init__(self, chunks: Iterable[KnowledgeRetrievalResult]) -> None:
        self._index = tuple(
            _IndexedChunk(
                result=chunk,
                terms=frozenset(_tokenize(chunk.content)),
            )
            for chunk in chunks
        )
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
        if limit < 1:
            raise ValueError("limit must be at least 1")

        query_terms = frozenset(_tokenize(query))
        if not query_terms:
            raise ValueError("query must contain at least one searchable token")

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
        ranked_results = sorted(
            (item for item in scored_results if item[0] > 0),
            key=lambda item: (-item[0], item[1].chunk_id),
        )
        return tuple(
            result.model_copy(update={"relevance_score": score})
            for score, result in ranked_results[:limit]
        )


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
