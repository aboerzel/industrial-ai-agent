from types import SimpleNamespace

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.infrastructure.knowledge_mcp_server import (
    _invoke_knowledge_search,
)
from industrial_ai_agent.infrastructure.observed_knowledge_retrieval import (
    ObservedEmbeddingClient,
    ObservedKnowledgeRetriever,
    ObservedReranker,
)
from industrial_ai_agent.infrastructure.telemetry import (
    Telemetry,
    TelemetryConfiguration,
)


def test_retrieval_stage_spans_share_the_knowledge_search_trace() -> None:
    telemetry, exporter = _recording_telemetry()
    result = _result()
    embedding = ObservedEmbeddingClient(
        _EmbeddingClient(), telemetry=telemetry, model="local-embedding"
    )
    lexical = ObservedKnowledgeRetriever(
        _Retriever(result),
        telemetry=telemetry,
        span_name="retrieval.lexical",
        strategy="bm25",
    )
    fusion = ObservedKnowledgeRetriever(
        _Retriever(result),
        telemetry=telemetry,
        span_name="retrieval.fusion",
        strategy="reciprocal_rank_fusion",
    )
    reranker = ObservedReranker(
        _Reranker(), telemetry=telemetry, model="local-reranker"
    )

    with telemetry.span("knowledge.search", {"mcp.tool": "search_documentation"}):
        embedding.embed_query("private query")
        candidates = lexical.search("private query", 3)
        fusion.search("private query", 3)
        reranker.rerank("private query", candidates)

    spans = {span.name: span for span in exporter.get_finished_spans()}
    root = spans["knowledge.search"]
    assert {
        "retrieval.embedding",
        "retrieval.lexical",
        "retrieval.fusion",
        "retrieval.rerank",
    } <= set(spans)
    for name in (
        "retrieval.embedding",
        "retrieval.lexical",
        "retrieval.fusion",
        "retrieval.rerank",
    ):
        assert spans[name].context.trace_id == root.context.trace_id
        assert spans[name].parent is not None
        assert spans[name].parent.span_id == root.context.span_id
    assert "private query" not in str(
        [span.attributes for span in exporter.get_finished_spans()]
    )
    assert spans["retrieval.lexical"].attributes["retrieval.result_count"] == 1
    assert spans["retrieval.rerank"].attributes["retrieval.candidate_count"] == 1


def test_knowledge_search_wraps_the_pipeline_in_retrieval_search_span() -> None:
    telemetry, exporter = _recording_telemetry()

    _invoke_knowledge_search(
        telemetry=telemetry,
        action=lambda: SimpleNamespace(results=()),
    )

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["retrieval.search"].parent is not None
    assert (
        spans["retrieval.search"].parent.span_id
        == spans["knowledge.search"].context.span_id
    )
    assert spans["retrieval.search"].attributes["retrieval.strategy"] == (
        "hybrid_reranked"
    )
    assert spans["retrieval.search"].attributes["operation.status"] == "success"


def _recording_telemetry() -> tuple[Telemetry, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return (
        Telemetry(
            TelemetryConfiguration(enabled=True),
            tracer_provider=provider,
            meter_provider=MeterProvider(),
        ),
        exporter,
    )


class _EmbeddingClient:
    def embed_query(self, text: str) -> tuple[float, ...]:
        return (0.1, 0.2)

    def embed_documents(self, texts: list[str]) -> tuple[tuple[float, ...], ...]:
        return tuple((0.1, 0.2) for _ in texts)


class _Retriever:
    def __init__(self, result: KnowledgeRetrievalResult) -> None:
        self._result = result

    def search(self, query: str, limit: int) -> tuple[KnowledgeRetrievalResult, ...]:
        return (self._result,)[:limit]


class _Reranker:
    def rerank(
        self,
        query: str,
        candidates: tuple[KnowledgeRetrievalResult, ...],
    ) -> tuple[KnowledgeRetrievalResult, ...]:
        return candidates


def _result() -> KnowledgeRetrievalResult:
    return KnowledgeRetrievalResult(
        content="private document content",
        document_id="D-1",
        source="private.md",
        chunk_id="D-1::1",
        relevance_score=0.9,
    )
