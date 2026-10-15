"""FC02: labels follow emitted RLS-visible relationships, never caller clearance."""

import asyncio
import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from openai import OpenAI
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
    _append_observation_identifiers,
    _document_references_from_observation,
    _extract_classification,
)
from industrial_ai_agent.agent.llm import LLMMessage, LLMRequest, MessageRole, ModelId
from industrial_ai_agent.agent.model_egress import (
    DataClassificationBoundaryError,
    EgressCheckedLLMClient,
    ModelEgressDeniedError,
)
from industrial_ai_agent.domain.knowledge_retrieval import KnowledgeRetrievalResult
from industrial_ai_agent.domain.maintenance_ticket import (
    MaintenanceTicketId,
    MaintenanceTicketRequestId,
)
from industrial_ai_agent.domain.product_history import StationId
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.docling_ingestion import (
    CatalogDocument,
    _chunk_document,
)
from industrial_ai_agent.infrastructure.factory_mcp_server import (
    create_factory_mcp_server,
)
from industrial_ai_agent.infrastructure.knowledge_mcp_server import (
    create_knowledge_mcp_server,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    ModelCatalogConfiguration,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.persistence.models import (
    DocumentCatalogRecord,
    FactoryRecord,
    MachineStateRecord,
    MaintenanceTicketRecord,
    StationRecord,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlDocumentCatalogRepository,
    PostgreSqlDocumentContentRepository,
    PostgreSqlFactoryDiscoveryRepository,
    PostgreSqlMachineStatusRepository,
    PostgreSqlMaintenanceTicketRepository,
    PostgreSqlProductHistoryRepository,
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.tools.documentation_search import DocumentationSearchCapability
from industrial_ai_agent.tools.factory_discovery import FactoryDiscoveryCapability
from industrial_ai_agent.tools.machine_status import (
    MachineStatusCapability,
    MachineStatusResult,
)
from industrial_ai_agent.tools.maintenance_ticket import (
    MaintenanceTicketCapability,
    MaintenanceTicketLookupResult,
)
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

pytestmark = pytest.mark.skipif(
    not os.getenv("FACTORY_DATABASE_URL")
    or not os.getenv("FACTORY_DATABASE_ADMIN_URL"),
    reason="requires disposable PostgreSQL app/admin fixtures",
)
LABELS = DataClassification
# Source, station, caller: include higher-source and PUBLIC-under-RESTRICTED controls.
MATRIX = (
    (0, 2, 2),
    (1, 2, 2),
    (2, 1, 2),
    (0, 3, 3),
    (0, 0, 3),
    (3, 1, 3),
    (1, 0, 3),
    (2, 3, 3),
)


@dataclass(frozen=True)
class ProjectionCase:
    index: int
    source: DataClassification
    station: DataClassification
    caller: DataClassification
    station_id: UUID
    document_id: str

    @property
    def code(self) -> str:
        return f"S{81 + self.index}"

    @property
    def ticket(self) -> str:
        return f"MT-{self.code}-20261015"

    @property
    def request_id(self) -> str:
        return f"synthetic-fc02-{self.station_id}"

    @property
    def expected(self) -> DataClassification:
        return LABELS(max(int(self.source), int(self.station)))


@dataclass
class MixedRows:
    factory: PostgreSqlSessionFactory
    admin: Engine
    cases: tuple[ProjectionCase, ...]
    unlinked_document_id: str


def context(clearance: DataClassification) -> SecurityContext:
    return SecurityContext("synthetic-fc02-reader", ("reader",), clearance, True)


@pytest.fixture(scope="module")
def mixed_rows() -> Iterator[MixedRows]:
    database_url = os.environ["FACTORY_DATABASE_URL"]
    url = make_url(database_url)
    if url.host not in {"localhost", "127.0.0.1"} or not (
        url.database and url.database.startswith("verification_")
    ):
        pytest.skip("FC02 writes require an isolated verification database")
    factory = PostgreSqlSessionFactory(database_url)
    admin = create_engine(os.environ["FACTORY_DATABASE_ADMIN_URL"])
    factory_id = uuid4()
    cases = tuple(
        ProjectionCase(
            i, LABELS(source), LABELS(station), LABELS(caller), uuid4(), str(uuid4())
        )
        for i, (source, station, caller) in enumerate(MATRIX)
    )
    unlinked = str(uuid4())
    try:
        with Session(admin) as session, session.begin():
            session.add(
                FactoryRecord(
                    id=factory_id,
                    code="FC02-SYNTHETIC",
                    name="Synthetic classification matrix",
                    classification=0,
                )
            )
            session.flush()
            for case in cases:
                session.add(
                    StationRecord(
                        id=case.station_id,
                        factory_id=factory_id,
                        code=case.code,
                        name=f"Synthetic station {case.code}",
                        classification=int(case.station),
                    )
                )
            session.flush()
            for case in cases:
                session.add(
                    MachineStateRecord(
                        id=uuid4(),
                        station_id=case.station_id,
                        observed_at=datetime(2026, 10, 15, tzinfo=UTC),
                        state="FAULTED",
                        active_error_code=f"FC02-FAULT-{case.index}",
                        classification=int(case.source),
                    )
                )
                session.add(
                    MaintenanceTicketRecord(
                        id=uuid4(),
                        station_id=case.station_id,
                        ticket_code=case.ticket,
                        request_id=case.request_id,
                        status="OPEN",
                        summary="Synthetic FC02 ticket",
                        classification=int(case.source),
                    )
                )
                session.add(
                    DocumentCatalogRecord(
                        id=case.document_id,
                        factory_id=factory_id,
                        station_id=case.station_id,
                        title="Synthetic FC02 document",
                        mime_type="text/plain",
                        source_system="synthetic-fc02",
                        version="1",
                        valid_from=date(2026, 10, 15),
                        tags=[f"FC02-FAULT-{case.index}"],
                        file_path=f"documents/fc02/{case.index:02}.txt",
                        checksum=hashlib.sha256(case.document_id.encode()).hexdigest(),
                        classification=int(case.source),
                    )
                )
            session.add(
                DocumentCatalogRecord(
                    id=unlinked,
                    factory_id=factory_id,
                    station_id=None,
                    title="Synthetic unlinked public document",
                    mime_type="text/plain",
                    source_system="synthetic-fc02",
                    version="1",
                    valid_from=date(2026, 10, 15),
                    tags=[],
                    file_path="documents/fc02/unlinked.txt",
                    checksum=hashlib.sha256(unlinked.encode()).hexdigest(),
                    classification=0,
                )
            )
        yield MixedRows(factory, admin, cases, unlinked)
    finally:
        with admin.begin() as connection:
            for table in ("maintenance_ticket", "machine_state"):
                connection.execute(
                    text(
                        f"DELETE FROM {table} WHERE station_id IN "
                        "(SELECT id FROM station WHERE factory_id=:id)"
                    ),
                    {"id": factory_id},
                )
            for table in ("document_catalog", "station", "factory"):
                connection.execute(
                    text(
                        f"DELETE FROM {table} WHERE "
                        f"{'id' if table == 'factory' else 'factory_id'}=:id"
                    ),
                    {"id": factory_id},
                )
        factory.dispose()
        admin.dispose()


@dataclass(frozen=True)
class FixedRetriever:
    chunks: tuple[KnowledgeRetrievalResult, ...]

    def search(self, query: str, top_k: int) -> tuple[KnowledgeRetrievalResult, ...]:
        del query
        return self.chunks[:top_k]


def catalog_for(
    rows: MixedRows, case: ProjectionCase, clearance=None
) -> CatalogDocument:
    return next(
        document
        for document in PostgreSqlDocumentCatalogRepository(
            rows.factory, context(clearance if clearance is not None else case.caller)
        ).list_documents()
        if document.document_id == case.document_id
    )


def factory_server(rows: MixedRows, clearance: DataClassification):
    security = context(clearance)
    return create_factory_mcp_server(
        product_history=ProductHistoryCapability(
            PostgreSqlProductHistoryRepository(rows.factory, security)
        ),
        machine_status=MachineStatusCapability(
            PostgreSqlMachineStatusRepository(rows.factory, security)
        ),
        factory_discovery=FactoryDiscoveryCapability(
            PostgreSqlFactoryDiscoveryRepository(rows.factory, security)
        ),
        maintenance_ticket=MaintenanceTicketCapability(
            PostgreSqlMaintenanceTicketRepository(rows.factory, security)
        ),
    )


def wire_result(rows: MixedRows, case: ProjectionCase, category: str):
    if category == "document":
        chunks = _chunk_document(catalog_for(rows, case), "# Synthetic\nPublic text.")
        server = create_knowledge_mcp_server(
            documentation_search=DocumentationSearchCapability(FixedRetriever(chunks))
        )
        tool, arguments = "search_documentation", {"query": "synthetic"}
    else:
        server = factory_server(rows, case.caller)
        tool, arguments = (
            ("get_machine_status", {"station_id": case.code})
            if category == "machine"
            else ("get_maintenance_ticket", {"ticket_id": case.ticket})
        )
    response = asyncio.run(server.call_tool(tool, arguments))
    assert not response.is_error
    # Exercise actual MCP serialization, not just the internal dataclass.
    payload = json.loads(json.dumps(response.structured_content))
    assert _extract_classification(payload) == case.expected
    return payload


@pytest.mark.parametrize("case_index", range(len(MATRIX)))
def test_fc02_01_machine_internal_capability_and_mcp_labels(mixed_rows, case_index):
    case = mixed_rows.cases[case_index]
    repository = PostgreSqlMachineStatusRepository(
        mixed_rows.factory, context(case.caller)
    )
    internal = repository.get_machine_status(StationId(case.code))
    assert internal.classification == case.expected
    assert internal.station_id.value == case.code
    capability = MachineStatusCapability(repository).get_machine_status(case.code)
    assert capability.classification == case.expected
    payload = wire_result(mixed_rows, case, "machine")
    assert MachineStatusResult.model_validate_json(json.dumps(payload)) == capability
    assert payload["state"] == "FAULTED"
    assert payload["active_error_code"] == f"FC02-FAULT-{case.index}"


@pytest.mark.parametrize("case_index", range(len(MATRIX)))
def test_fc02_02_ticket_internal_lookup_retry_capability_and_mcp_labels(
    mixed_rows, case_index
):
    case = mixed_rows.cases[case_index]
    repository = PostgreSqlMaintenanceTicketRepository(
        mixed_rows.factory, context(case.caller)
    )
    internal = repository.get_maintenance_ticket(MaintenanceTicketId(case.ticket))
    by_request = repository.get_maintenance_ticket_by_request_id(
        MaintenanceTicketRequestId(case.request_id)
    )
    # Existing-result retry performs no insert; preserve its classification too.
    retry = repository.create_maintenance_ticket(
        MaintenanceTicketRequestId(case.request_id),
        StationId(case.code),
        "Synthetic FC02 ticket",
    )
    assert internal == by_request == retry
    assert internal.classification == case.expected
    capability = MaintenanceTicketCapability(repository).get_maintenance_ticket(
        case.ticket
    )
    assert capability.classification == case.expected
    payload = wire_result(mixed_rows, case, "ticket")
    assert (
        MaintenanceTicketLookupResult.model_validate_json(json.dumps(payload))
        == capability
    )
    assert payload["station_id"] == case.code
    assert payload["summary"] == "Synthetic FC02 ticket"


@pytest.mark.parametrize("case_index", range(len(MATRIX)))
def test_fc02_03_document_catalog_chunk_capability_and_mcp_labels(
    mixed_rows, case_index
):
    case = mixed_rows.cases[case_index]
    catalog = catalog_for(mixed_rows, case)
    assert catalog.classification == case.expected
    assert catalog.station_code == case.code
    chunks = _chunk_document(catalog, "# Synthetic\nPublic text.")
    capability = DocumentationSearchCapability(
        FixedRetriever(chunks)
    ).search_documentation("synthetic")
    assert capability.results[0].classification == case.expected
    payload = wire_result(mixed_rows, case, "document")
    parsed = KnowledgeRetrievalResult.model_validate_json(
        json.dumps(payload["results"][0])
    )
    assert parsed.classification == case.expected
    assert parsed.metadata["station_code"] == case.code
    assert parsed.metadata["fault_ids"] == [f"FC02-FAULT-{case.index}"]


def test_fc02_05_09_hidden_or_absent_document_relation_does_not_raise_label(mixed_rows):
    case = mixed_rows.cases[3]  # PUBLIC document/state, RESTRICTED station.
    catalog = catalog_for(mixed_rows, case, LABELS.PUBLIC)
    assert catalog.station_code is None
    assert catalog.classification is LABELS.PUBLIC
    chunks = _chunk_document(catalog, "# Public\nSynthetic public content.")
    assert case.code not in json.dumps(
        [chunk.model_dump(mode="json") for chunk in chunks]
    )
    assert all(chunk.classification is LABELS.PUBLIC for chunk in chunks)
    machine = PostgreSqlMachineStatusRepository(
        mixed_rows.factory, context(LABELS.PUBLIC)
    )
    assert machine.get_machine_status(StationId(case.code)) is None
    neutral = MachineStatusCapability(machine).get_machine_status(case.code)
    assert (
        not neutral.found
        and neutral.state is None
        and neutral.active_error_code is None
    )
    unlinked = next(
        document
        for document in PostgreSqlDocumentCatalogRepository(
            mixed_rows.factory, context(LABELS.RESTRICTED)
        ).list_documents()
        if document.document_id == mixed_rows.unlinked_document_id
    )
    assert unlinked.station_code is None
    assert unlinked.classification is LABELS.PUBLIC
    with mixed_rows.factory.connection(context(LABELS.PUBLIC)) as connection:
        assert (
            connection.execute(
                text(
                    "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"
                )
            ).scalar_one()
            is False
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM station WHERE id=:id"),
                {"id": case.station_id},
            ).scalar_one()
            == 0
        )
    # A hidden relationship is still a physically valid foreign key.
    with mixed_rows.admin.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM document_catalog d JOIN station s ON s.id=d.station_id "
                    "WHERE d.id=:id"
                ),
                {"id": case.document_id},
            ).scalar_one()
            == 1
        )


def test_fc02_09_content_only_read_does_not_emit_or_authorize_station_metadata(
    mixed_rows, tmp_path
):
    case = mixed_rows.cases[3]
    content = case.document_id.encode()
    path = tmp_path / "documents" / "fc02" / f"{case.index:02}.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    document = PostgreSqlDocumentContentRepository(
        mixed_rows.factory, tmp_path
    ).get_document(case.document_id, context(LABELS.PUBLIC))
    assert document.content == content
    assert document.filename == "Synthetic-FC02-document.txt"
    assert not hasattr(document, "station_code")


@pytest.mark.parametrize("clearance", [LABELS.CONFIDENTIAL, LABELS.RESTRICTED])
def test_fc02_07_multiple_visible_classifications_preserve_order(mixed_rows, clearance):
    capability = FactoryDiscoveryCapability(
        PostgreSqlFactoryDiscoveryRepository(mixed_rows.factory, context(clearance))
    )
    stations = capability.list_stations()
    assert [item.station_id for item in stations.stations] == sorted(
        item.station_id for item in stations.stations
    )
    assert stations.classification == max(
        item.classification for item in stations.stations
    )
    assert (
        stations.classification == clearance
    )  # Matrix contains actual data at that label.
    documents = PostgreSqlDocumentCatalogRepository(
        mixed_rows.factory, context(clearance)
    ).list_documents()
    selected = tuple(doc for doc in documents if doc.source_system == "synthetic-fc02")
    assert [doc.file_path for doc in selected] == sorted(
        doc.file_path for doc in selected
    )
    chunks = tuple(
        chunk for doc in selected for chunk in _chunk_document(doc, "Public text.")
    )
    payload = (
        DocumentationSearchCapability(FixedRetriever(chunks))
        .search_documentation("synthetic", top_k=len(chunks))
        .model_dump(mode="json")
    )
    assert _extract_classification(payload) == clearance


@pytest.mark.parametrize("category", ["machine", "ticket", "document"])
def test_fc02_08_trusted_structured_references_are_covered_by_result_label(
    mixed_rows, category
):
    case = mixed_rows.cases[0]
    payload = wire_result(mixed_rows, case, category)
    if category == "document":
        refs = _document_references_from_observation(json.dumps(payload))
        assert refs[0].document_id == case.document_id
        assert payload["results"][0]["metadata"]["station_code"] == case.code
    else:
        refs = []
        _append_observation_identifiers(
            refs,
            "get_machine_status" if category == "machine" else "get_maintenance_ticket",
            json.dumps(payload),
        )
        assert any(ref.value == case.code for ref in refs)
    assert _extract_classification(payload) is LABELS.CONFIDENTIAL


@pytest.mark.parametrize("category", ["machine", "ticket", "document"])
@pytest.mark.parametrize("run_ceiling", [LABELS.PUBLIC, LABELS.CONFIDENTIAL])
def test_fc02_10_11_corrected_tool_label_precedes_model_egress(
    mixed_rows, category, run_ceiling, monkeypatch
):
    case = mixed_rows.cases[0]
    payload = wire_result(mixed_rows, case, category)
    counts = {"credentials": 0, "sdk": 0, "transport": 0}
    configuration = ModelCatalogConfiguration.model_validate(
        {
            "models": [
                {
                    "id": "synthetic_fc02",
                    "display_name": "Synthetic FC02",
                    "provider": "synthetic",
                    "provider_model": "synthetic",
                    "base_url": "https://provider.invalid/v1",
                    "temperature": 0,
                    "authentication": "api_key",
                    "api_key_env": "SYNTHETIC_FC02_KEY",
                    "execution_zone": "PUBLIC_CLOUD",
                    "max_data_classification": "PUBLIC",
                    "capabilities": ["text", "tool_calling"],
                    "quality_class": "HIGH",
                    "cost_class": "LOW",
                }
            ]
        }
    )

    def send(request):
        counts["transport"] += 1
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": "synthetic",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "SYNTHETIC"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    def sdk(**kwargs):
        counts["sdk"] += 1
        return OpenAI(**kwargs)

    with OpenAICompatibleLLMClient(
        configuration,
        environment={"SYNTHETIC_FC02_KEY": "synthetic-not-a-real-key"},
        client_factory=sdk,
        http_client_factory=lambda: httpx.Client(
            transport=httpx.MockTransport(send), trust_env=False, follow_redirects=False
        ),
    ) as adapter:
        resolve = adapter._resolve_api_key

        def credentials(config):
            counts["credentials"] += 1
            return resolve(config)

        monkeypatch.setattr(adapter, "_resolve_api_key", credentials)
        checked = EgressCheckedLLMClient(adapter, configuration, LABELS.PUBLIC)
        model = LLMClientChatModel(checked, ModelId("synthetic_fc02"))
        agent = LangGraphTroubleshootingAgent(model, run_classification=run_ceiling)
        state = {"effective_classification": int(LABELS.PUBLIC)}
        request = LLMRequest(
            messages=(LLMMessage(role=MessageRole.USER, content=json.dumps(payload)),)
        )
        if run_ceiling is LABELS.PUBLIC:
            with pytest.raises(DataClassificationBoundaryError):
                agent._observe_result_classification(state, payload)
        else:
            assert agent._observe_result_classification(state, payload) == 2
            with pytest.raises(ModelEgressDeniedError):
                checked.chat(ModelId("synthetic_fc02"), request)
        assert counts == {"credentials": 0, "sdk": 0, "transport": 0}
        # Mutation control: the old understated label permits this exact synthetic
        # payload through the real SDK/MockTransport, proving the guard is exercised.
        understated = EgressCheckedLLMClient(adapter, configuration, LABELS.PUBLIC)
        assert understated.chat(ModelId("synthetic_fc02"), request).text == "SYNTHETIC"
        assert counts == {"credentials": 1, "sdk": 1, "transport": 1}
