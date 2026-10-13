"""Recording-only regressions for the transitive embedding provider boundary."""

from types import SimpleNamespace

import pytest

from industrial_ai_agent.agent.model_egress import ModelEgressDeniedError
from industrial_ai_agent.application.embedding_egress import (
    EmbeddingExecutionAuthorizer,
)
from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.in_memory_semantic_knowledge_retriever import (
    InMemorySemanticKnowledgeRetriever,
)
from industrial_ai_agent.infrastructure.knowledge_mcp_server import (
    ClearanceAwareDocumentationSearchFactory,
    create_knowledge_mcp_server,
)
from industrial_ai_agent.infrastructure.knowledge_retrieval_composition import (
    create_reranked_knowledge_retriever,
)
from industrial_ai_agent.infrastructure.observed_knowledge_retrieval import (
    ObservedEmbeddingClient,
)
from industrial_ai_agent.infrastructure.ollama_embedding_client import (
    OllamaEmbeddingClient,
)
from industrial_ai_agent.tools.documentation_search import DocumentationSearchCapability


class RecordingSdk:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.configurations: list[dict] = []

    def factory(self, **configuration):
        self.configurations.append(configuration)
        return self

    def embed_query(self, text):
        self.calls.append(("query", text))
        return [1.0, 0.0]

    def embed_documents(self, texts):
        self.calls.append(("documents", tuple(texts)))
        return [[1.0, 0.0] for _ in texts]


@pytest.fixture
def sdk(monkeypatch):
    recording = RecordingSdk()
    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.ollama_embedding_client.OllamaEmbeddings",
        recording.factory,
    )
    return recording


def _call(client, operation, classification):
    if operation == "query":
        return client.embed_query(
            "synthetic protected query", classification=classification
        )
    return client.embed_documents(
        ["synthetic protected document"], classification=classification
    )


@pytest.mark.parametrize("operation", ["query", "documents"])
@pytest.mark.parametrize("classification", list(DataClassification))
@pytest.mark.parametrize(
    "endpoint",
    [
        "https://unapproved.example:11434",
        "http://unapproved.example:11434",
        "https://localhost:11434",
        "http://localhost:443",
        "http://localhost",
        "http://localhost:11434/remote",
        "http://localhost:11434?target=remote",
        "http://localhost:11434#remote",
        "http://localhost:11434?",
        "http://localhost:11434#",
        "http://localhost:11434@unapproved.example:11434",
        "http://user:password@localhost:11434",
        "http://localhost.unapproved.example:11434",
        "http://host.docker.internal.unapproved.example:11434",
        "http://192.168.1.2:11434",
        "http://127.0.0.2:11434",
        "http://127.1:11434",
        "http://2130706433:11434",
        "http://[::ffff:127.0.0.1]:11434",
        "http://localhost.:11434",
        "http://%6cocalhost:11434",
        "http://localhost\\@unapproved.example:11434",
        "http://local\nhost:11434",
        "not-a-url",
        "",
        None,
    ],
)
def test_unapproved_destination_never_receives_text(
    sdk, operation, classification, endpoint
):
    client = OllamaEmbeddingClient(base_url=endpoint)
    with pytest.raises(ModelEgressDeniedError, match="^Model egress denied by policy$"):
        _call(client, operation, classification)
    assert sdk.calls == []
    assert sdk.configurations == []


@pytest.mark.parametrize("operation", ["query", "documents"])
@pytest.mark.parametrize("classification", [None, "RESTRICTED", 0, True, object()])
def test_unknown_classification_fails_closed_even_at_local_target(
    sdk, operation, classification
):
    with pytest.raises(ModelEgressDeniedError):
        _call(OllamaEmbeddingClient(), operation, classification)
    assert sdk.calls == []


@pytest.mark.parametrize("operation", ["query", "documents"])
def test_omitted_classification_fails_closed(sdk, operation):
    client = OllamaEmbeddingClient()
    with pytest.raises(ModelEgressDeniedError):
        if operation == "query":
            client.embed_query("synthetic secret")
        else:
            client.embed_documents(["synthetic secret"])
    assert sdk.calls == []


@pytest.mark.parametrize("operation", ["query", "documents"])
@pytest.mark.parametrize("classification", list(DataClassification))
@pytest.mark.parametrize(
    "endpoint,canonical",
    [
        ("http://localhost:11434", "http://127.0.0.1:11434"),
        ("HTTP://LOCALHOST:11434/", "http://127.0.0.1:11434"),
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("http://[::1]:11434", "http://[::1]:11434"),
        ("http://[0:0:0:0:0:0:0:1]:11434", "http://[::1]:11434"),
        ("http://host.docker.internal:11434", "http://host.docker.internal:11434"),
    ],
)
def test_explicit_local_target_passes_once(
    sdk, operation, classification, endpoint, canonical
):
    _call(OllamaEmbeddingClient(base_url=endpoint), operation, classification)
    assert len(sdk.calls) == 1
    assert sdk.configurations[0]["base_url"] == canonical
    assert sdk.configurations[0]["client_kwargs"] == {
        "trust_env": False,
        "follow_redirects": False,
    }


def test_authorization_repeats_on_every_call(sdk):
    client = OllamaEmbeddingClient()
    client.embed_query("allowed", classification=DataClassification.RESTRICTED)
    with pytest.raises(ModelEgressDeniedError):
        client.embed_query("synthetic secret", classification=None)
    assert len(sdk.calls) == 1


def _chunk(classification=DataClassification.RESTRICTED):
    return KnowledgeRetrievalResult(
        content="synthetic protected document",
        document_id="test",
        source="test.md",
        chunk_id="test::1",
        classification=classification,
    )


def test_document_ingestion_reaches_same_guard_before_sdk(sdk):
    with pytest.raises(ModelEgressDeniedError):
        InMemorySemanticKnowledgeRetriever(
            [_chunk()],
            ObservedEmbeddingClient(
                OllamaEmbeddingClient(base_url="https://unapproved.example"),
                telemetry=None,
                model="test",
            ),
            query_classification=DataClassification.RESTRICTED,
        )
    assert sdk.calls == []


def test_missing_chunk_label_is_not_implicitly_public(sdk):
    chunk = KnowledgeRetrievalResult(
        content="synthetic secret",
        document_id="test",
        source="test.md",
        chunk_id="test::1",
    )
    with pytest.raises(ModelEgressDeniedError):
        InMemorySemanticKnowledgeRetriever([chunk], OllamaEmbeddingClient())
    assert sdk.calls == []


class RecordingEmbeddingPort:
    def __init__(self):
        self.classifications = []

    def embed_documents(self, texts, *, classification=None):
        self.classifications.append(("documents", classification))
        return tuple((1.0, 0.0) for _ in texts)

    def embed_query(self, text, *, classification=None):
        self.classifications.append(("query", classification))
        return (1.0, 0.0)


def test_chunk_batch_and_query_labels_survive_langchain_and_observation():
    port = RecordingEmbeddingPort()
    retriever = InMemorySemanticKnowledgeRetriever(
        [
            _chunk(DataClassification.PUBLIC),
            _chunk().model_copy(update={"chunk_id": "test::2"}),
        ],
        ObservedEmbeddingClient(port, telemetry=None, model="test"),
        query_classification=DataClassification.CONFIDENTIAL,
    )
    retriever.search("synthetic query", 1)
    assert port.classifications == [
        ("documents", DataClassification.RESTRICTED),
        ("query", DataClassification.CONFIDENTIAL),
    ]


def test_missing_query_context_denies_before_query_provider(sdk):
    retriever = InMemorySemanticKnowledgeRetriever([_chunk()], OllamaEmbeddingClient())
    sdk.calls.clear()
    with pytest.raises(ModelEgressDeniedError):
        retriever.search("synthetic secret", 1)
    assert sdk.calls == []


class PassthroughReranker:
    def rerank(self, query, candidates):
        return tuple(candidates)


def test_mcp_query_and_indexing_use_guarded_local_pipeline(sdk):
    retriever = create_reranked_knowledge_retriever(
        [_chunk()],
        query_classification=DataClassification.RESTRICTED,
        reranker=PassthroughReranker(),
    )
    server = create_knowledge_mcp_server(
        documentation_search=DocumentationSearchCapability(retriever)
    )
    tool = server._tool_manager.get_tool("search_documentation")
    result = tool.fn("synthetic protected query", 1)
    assert result["results"][0]["chunk_id"] == "test::1"
    assert [operation for operation, _ in sdk.calls] == ["documents", "query"]


@pytest.mark.parametrize("clearance", list(DataClassification))
def test_http_query_uses_restricted_at_provider_boundary_regardless_of_clearance(
    monkeypatch, tmp_path, sdk, clearance
):
    context = SecurityContext("test", ("test",), clearance, True)
    captured = []
    original = EmbeddingExecutionAuthorizer.require_allowed

    def authorize(self, classification, endpoint):
        captured.append(classification)
        return original(self, classification, endpoint)

    monkeypatch.setattr(
        EmbeddingExecutionAuthorizer,
        "require_allowed",
        authorize,
    )
    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.persistence.postgres.PostgreSqlSessionFactory",
        lambda _: object(),
    )
    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.persistence.postgres.PostgreSqlDocumentCatalogRepository",
        lambda *_: SimpleNamespace(list_documents=lambda: (object(),)),
    )
    monkeypatch.setattr(
        "industrial_ai_agent.infrastructure.docling_ingestion.eligible_catalog_documents",
        lambda catalog, _: catalog,
    )
    factory = ClearanceAwareDocumentationSearchFactory(
        database_url="unused",
        embedding_base_url=None,
        reranker_device=None,
        reranker_local_files_only=True,
        document_root=tmp_path,
        reranker=PassthroughReranker(),
    )
    monkeypatch.setattr(
        factory,
        "_shared_ingestor",
        lambda: SimpleNamespace(ingest=lambda _: (_chunk(clearance),)),
    )
    factory.for_context(context).search_documentation("synthetic protected query", 1)
    assert captured == [clearance, DataClassification.RESTRICTED]
    assert [operation for operation, _ in sdk.calls] == ["documents", "query"]
