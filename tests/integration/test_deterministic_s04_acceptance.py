"""Deterministic full-stack acceptance coverage for the S04 root-cause path.

The scripted client is deliberately local to this test module. It is injected at the
LLM port after the production resolver and final capability/egress guards, and is not
part of the runtime model catalog or Docker composition.
"""

from __future__ import annotations

import json
import sys
from asyncio import run
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from mcp.client.stdio import StdioServerParameters

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    ModelId,
)
from industrial_ai_agent.agent.model_egress import (
    EgressCheckedLLMClient,
    ExecutionZone,
    ModelExecutionAuthorizer,
)
from industrial_ai_agent.agent.model_selection import (
    AGENT_CALL_REQUIREMENTS,
    AGENT_CONSUMER,
    CapabilityCheckedLLMClient,
    CostClass,
    ModelAssignment,
    ModelAssignmentRepository,
    ModelCapability,
    ModelResolutionService,
    QualityClass,
)
from industrial_ai_agent.agent.run_classification_policy import ResolvedRunPolicy
from industrial_ai_agent.agent.troubleshooting_run_service import (
    McpBackedTroubleshootingAgent,
    RoutedTroubleshootingAgentFactory,
    TroubleshootingRunService,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.llm.configuration import (
    AuthenticationMode,
    ModelCatalogConfiguration,
    ModelConfig,
    load_model_catalog,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    DEFAULT_ALLOWED_FACTORY_TOOLS,
    DEFAULT_ALLOWED_KNOWLEDGE_TOOLS,
    McpLangChainToolProvider,
    McpServerConfiguration,
)

_ACCEPTANCE_MODEL_ID = ModelId("acceptance_s04")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_S04_REQUEST = (
    "Untersuche Station S04 und ermittle die Ursache des aktuellen Fehlers. "
    "Nutze Maschinenstatus und technische Dokumentation und schlage sinnvolle "
    "nächste Schritte vor."
)
_FACTORY_SERVER_SOURCE = """
from industrial_ai_agent.infrastructure.factory_mcp_server import create_factory_mcp_server
from industrial_ai_agent.infrastructure.in_memory_factory_discovery_repository import InMemoryFactoryDiscoveryRepository
from industrial_ai_agent.infrastructure.in_memory_machine_status_repository import InMemoryMachineStatusRepository
from industrial_ai_agent.infrastructure.in_memory_maintenance_ticket_repository import InMemoryMaintenanceTicketRepository
from industrial_ai_agent.infrastructure.in_memory_product_history_repository import InMemoryProductHistoryRepository
from industrial_ai_agent.tools.factory_discovery import FactoryDiscoveryCapability
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

create_factory_mcp_server(
    product_history=ProductHistoryCapability(InMemoryProductHistoryRepository()),
    machine_status=MachineStatusCapability(InMemoryMachineStatusRepository()),
    factory_discovery=FactoryDiscoveryCapability(InMemoryFactoryDiscoveryRepository()),
    maintenance_ticket=MaintenanceTicketCapability(InMemoryMaintenanceTicketRepository()),
).run(transport='stdio')
"""


def _knowledge_server_source() -> str:
    """Compose the real Knowledge MCP tool with deterministic lexical retrieval."""
    knowledge_root = _PROJECT_ROOT / "knowledge_base"
    return f"""
from pathlib import Path

from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
    InMemoryBm25KnowledgeRetriever,
    load_markdown_chunks,
)
from industrial_ai_agent.infrastructure.knowledge_mcp_server import create_knowledge_mcp_server
from industrial_ai_agent.tools.documentation_search import DocumentationSearchCapability

knowledge_root = Path({str(knowledge_root)!r})
retriever = InMemoryBm25KnowledgeRetriever(load_markdown_chunks(knowledge_root))
create_knowledge_mcp_server(
    documentation_search=DocumentationSearchCapability(retriever),
).run(transport='stdio')
"""


class ScriptedS04LLM(LLMClient):
    """A bounded test double that follows the canonical S04 evidence trajectory."""

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self._tool_step = 0

    def chat(self, model_id: ModelId, request: LLMRequest) -> LLMResponse:
        assert model_id == _ACCEPTANCE_MODEL_ID
        self.requests.append(request)
        if request.response_format is not None:
            return LLMResponse(
                text=json.dumps(
                    {
                        "answer": (
                            "Die Station S04 steht wegen QUALITY-09 still. "
                            "Die autorisierte Maschinenbeobachtung und die "
                            "zugeordnete Fehlerdokumentation weisen auf die "
                            "Prüfung der Qualitätsmessung hin."
                        ),
                        "investigation_steps": [],
                        "next_steps": [
                            "Qualitätsmessung an S04 gemäß der QUALITY-09-Prozedur prüfen."
                        ],
                        "identifiers": [],
                        "documents": [],
                    }
                ),
                finish_reason=FinishReason.STOP,
            )
        if self._tool_step == 0:
            self._tool_step += 1
            return _tool_response(
                "get_machine_status", {"station_id": "S04"}, "s04-status"
            )
        if self._tool_step == 1:
            self._tool_step += 1
            return _tool_response(
                "search_documentation",
                {"query": "S04 QUALITY-09", "top_k": 3},
                "quality-documentation",
            )
        return LLMResponse(
            text=(
                "### Wahrscheinliche Ursache\n\n"
                "QUALITY-09 an Station S04 erfordert die Prüfung der "
                "Qualitätsmessung gemäß der technischen Dokumentation."
            ),
            finish_reason=FinishReason.STOP,
        )


def _tool_response(
    name: str, arguments: dict[str, object], call_id: str
) -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=(LLMToolCall(id=call_id, name=name, arguments=arguments),),
        finish_reason=FinishReason.TOOL_CALLS,
    )


@dataclass
class _AssignmentRepository(ModelAssignmentRepository):
    assignment: ModelAssignment

    def get(self, consumer_id, data_classification):
        if (
            consumer_id == self.assignment.consumer_id
            and data_classification is self.assignment.data_classification
        ):
            return self.assignment
        return None

    def list(self) -> tuple[ModelAssignment, ...]:
        return (self.assignment,)

    def upsert(self, assignment: ModelAssignment) -> ModelAssignment:
        self.assignment = assignment
        return assignment


@dataclass
class _AcceptanceAgentFactory(RoutedTroubleshootingAgentFactory):
    catalog: ModelCatalogConfiguration
    clients: list[ScriptedS04LLM] = field(default_factory=list)
    authorizer: ModelExecutionAuthorizer = field(
        default_factory=ModelExecutionAuthorizer
    )

    def open_agent(
        self,
        *,
        model_id: ModelId,
        run_policy: ResolvedRunPolicy,
        checkpointer: object | None = None,
    ) -> AbstractContextManager[McpBackedTroubleshootingAgent]:
        del checkpointer
        return self._open_agent(model_id=model_id, run_policy=run_policy)

    @contextmanager
    def _open_agent(
        self, *, model_id: ModelId, run_policy: ResolvedRunPolicy
    ) -> Iterator[McpBackedTroubleshootingAgent]:
        scripted = ScriptedS04LLM()
        self.clients.append(scripted)
        checked = EgressCheckedLLMClient(
            scripted,
            self.catalog,
            run_policy.data_classification,
            authorizer=self.authorizer,
        )
        guarded = CapabilityCheckedLLMClient(
            checked,
            self.catalog,
            consumer_id=run_policy.model_consumer_id,
            data_classification=run_policy.data_classification,
        )
        yield LangGraphTroubleshootingAgent(
            LLMClientChatModel(guarded, model_id, supports_structured_output=True),
            mcp_tool_provider=_mcp_provider(),
            run_classification=run_policy.data_classification,
        )


def _catalog() -> ModelCatalogConfiguration:
    return ModelCatalogConfiguration(
        models=(
            ModelConfig(
                id=_ACCEPTANCE_MODEL_ID.value,
                display_name="Acceptance S04 Script",
                provider="acceptance_test",
                provider_model="scripted-s04",
                base_url="http://acceptance.invalid/v1",
                temperature=0,
                authentication=AuthenticationMode.NONE,
                execution_zone=ExecutionZone.LOCAL,
                max_data_classification=DataClassification.RESTRICTED,
                capabilities=frozenset(
                    {
                        ModelCapability.TEXT,
                        ModelCapability.TOOL_CALLING,
                        ModelCapability.STRUCTURED_OUTPUT,
                    }
                ),
                quality_class=QualityClass.STANDARD,
                cost_class=CostClass.LOW,
            ),
        )
    )


def _mcp_provider() -> McpLangChainToolProvider:
    return McpLangChainToolProvider(
        (
            McpServerConfiguration(
                server_id="factory",
                transport=StdioServerParameters(
                    command=sys.executable,
                    args=["-c", _FACTORY_SERVER_SOURCE],
                ),
                allowed_tool_names=DEFAULT_ALLOWED_FACTORY_TOOLS,
            ),
            McpServerConfiguration(
                server_id="knowledge",
                transport=StdioServerParameters(
                    command=sys.executable,
                    args=["-c", _knowledge_server_source()],
                ),
                allowed_tool_names=DEFAULT_ALLOWED_KNOWLEDGE_TOOLS,
            ),
        )
    )


def _client() -> tuple[TestClient, _AcceptanceAgentFactory, InMemoryAgentRunStore]:
    catalog = _catalog()
    assignment = ModelAssignment(
        consumer_id=AGENT_CONSUMER,
        data_classification=DataClassification.CONFIDENTIAL,
        model_id=_ACCEPTANCE_MODEL_ID,
    )
    factory = _AcceptanceAgentFactory(catalog)
    service = TroubleshootingRunService(
        model_resolver=ModelResolutionService(
            catalog=catalog,
            assignments=_AssignmentRepository(assignment),
            authorizer=factory.authorizer,
            consumer_requirements={AGENT_CONSUMER: AGENT_CALL_REQUIREMENTS},
            model_is_statically_available=lambda _: True,
        ),
        agent_factory=factory,
    )
    store = InMemoryAgentRunStore()
    return TestClient(create_app(service, run_store=store)), factory, store


def test_acceptance_model_is_not_a_production_catalog_entry() -> None:
    production_catalog = load_model_catalog(
        _PROJECT_ROOT / "config" / "model_catalog.toml"
    )

    assert _ACCEPTANCE_MODEL_ID.value not in {
        model.id for model in production_catalog.models
    }


def _run_s04(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/runs",
        json={
            "message": _S04_REQUEST,
            "user_clearance": "CONFIDENTIAL",
            "response_language": "DE",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_s04_root_cause_path_is_deterministic_through_http_langgraph_mcp_and_store() -> (
    None
):
    client, factory, store = _client()

    runs = [_run_s04(client) for _ in range(10)]

    assert all(run["status"] == "success" for run in runs)
    assert all(run["data_classification"] == "CONFIDENTIAL" for run in runs)
    assert all(
        [call["tool"] for call in run["tool_calls"]]
        == ["get_machine_status", "search_documentation"]
        for run in runs
    )
    assert all("S04" in (run["answer"] or "") for run in runs)
    assert all("QUALITY-09" in (run["answer"] or "") for run in runs)
    assert all(run["next_steps"] for run in runs)
    assert all("{data[" not in (run["answer"] or "") for run in runs)
    assert all("{{" not in (run["answer"] or "") for run in runs)
    assert all("```python" not in (run["answer"] or "").casefold() for run in runs)
    assert all("die" in (run["answer"] or "").casefold() for run in runs)
    assert all(run["error"] is None for run in runs)
    assert all(
        [step["action"] for step in run["investigation_steps"]]
        == ["get_machine_status", "search_documentation"]
        for run in runs
    )
    assert all("QUALITY-09" in run["investigation_steps"][0]["finding"] for run in runs)
    assert all(
        any(
            message.tool_call_id == "quality-documentation"
            and message.content is not None
            and "QUALITY-09" in message.content
            for message in scripted.requests[2].messages
        )
        for scripted in factory.clients
    )

    assert len(factory.clients) == 10
    assert all(len(scripted.requests) == 4 for scripted in factory.clients)
    assert all(
        [request.response_format is not None for request in scripted.requests]
        == [False, False, False, True]
        for scripted in factory.clients
    )
    assert all(
        all(request.tools for request in scripted.requests[:2])
        for scripted in factory.clients
    )

    run_id = runs[0]["run_id"]
    investigation_id = runs[0]["investigation_id"]
    stored = run(store.get(UUID(run_id)))
    assert stored is not None
    assert stored.failure_origin is None
    investigation = client.get(
        f"/api/v1/investigations/{investigation_id}?user_clearance=CONFIDENTIAL"
    )
    assert investigation.status_code == 200
    assert investigation.json()["turns"][0]["error"] is None
    report = client.get(
        f"/api/v1/investigations/{investigation_id}/pdf?user_clearance=CONFIDENTIAL"
    )
    assert report.status_code == 200
    assert b"QUALITY-09" in report.content
