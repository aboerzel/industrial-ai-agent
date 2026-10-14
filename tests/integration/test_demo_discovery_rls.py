"""Demo session -> real API/policy/graph/capability -> PostgreSQL RLS, no models."""

import asyncio
import json
import os
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from langchain_core.tools import StructuredTool

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import FinishReason, LLMResponse, ModelProfile
from industrial_ai_agent.agent.mcp_tool_provider import McpToolSession
from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.agent.run_classification_policy import (
    resolve_demo_discovery_tool,
)
from industrial_ai_agent.agent.tool_policy import ToolOperation, ToolPolicy
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.demo_security import (
    BearerTokenSecurityContextResolver,
)
from industrial_ai_agent.infrastructure.api.demo_sessions import DemoSessions
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlFactoryDiscoveryRepository,
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.tools.factory_discovery import FactoryDiscoveryCapability

DATABASE_URL = os.getenv("FACTORY_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="requires disposable PostgreSQL fixtures"
)
STATIONS_BY_LEVEL = (("S01", "S05"), ("S02", "S03"), ("S04", "S06"), ("S07", "S08"))
PRODUCTS_BY_LEVEL = (
    ("P4101", "P4102"),
    ("P4900", "P4901"),
    ("P4711", "P4801", "P4802", "P4805", "P4811"),
    ("P9001", "P9002"),
)


class DiscoveryRunService:
    """Record actual authorized capabilities before the fake final explanation."""

    def __init__(self, repository_for_context):
        self.repository_for_context = repository_for_context
        self.observations = []
        self.model_requests = []

    async def run_with_policy(
        self, message, *, run_policy, response_language, **kwargs
    ):
        tool_name = resolve_demo_discovery_tool(message)
        assert tool_name in run_policy.allowed_tool_names
        context = SecurityContext(
            subject_id=run_policy.mcp_client_identity,
            clearance=run_policy.mcp_clearance_ceiling,
            roles=("test-reader",),
            authenticated=True,
        )
        capability = FactoryDiscoveryCapability(self.repository_for_context(context))
        service = self

        class Provider:
            @asynccontextmanager
            async def open_session(self):
                async def read_inventory():
                    result = await asyncio.to_thread(getattr(capability, tool_name))
                    payload = result.model_dump(mode="json")
                    service.observations.append((run_policy, payload))
                    return json.dumps(payload)

                yield McpToolSession(
                    tools=(
                        StructuredTool.from_function(
                            coroutine=read_inventory,
                            name=tool_name,
                            description="Read authorized demo inventory.",
                        ),
                    ),
                    discovered_tool_names=(tool_name,),
                    server_name="recording-factory",
                    server_version="test",
                    protocol_version="test",
                    tool_policies=(ToolPolicy(tool_name, ToolOperation.READ),),
                )

        class FinalModel:
            def chat(self, profile, request):
                assert service.observations, (
                    "Discovery must execute before any model call"
                )
                service.model_requests.append(request)
                payload = service.observations[-1][1]
                items = payload.get("stations", payload.get("products"))
                key = "station_id" if tool_name == "list_stations" else "product_id"
                ids = ", ".join(item[key] for item in items)
                answer = (
                    f"Sichtbare Einträge: {ids}."
                    if response_language is ResponseLanguage.DE
                    else f"Visible entries: {ids}."
                )
                return LLMResponse(
                    text=json.dumps(
                        {
                            "answer": answer,
                            "investigation_steps": [
                                {"step": 1, "action": tool_name, "finding": answer}
                            ],
                            "next_steps": [],
                        }
                    ),
                    finish_reason=FinishReason.STOP,
                )

        agent = LangGraphTroubleshootingAgent(
            LLMClientChatModel(FinalModel(), ModelProfile("local_quality")),
            mcp_tool_provider=Provider(),
            run_classification=run_policy.data_classification,
        )
        return await agent.aanswer_via_mcp(message, response_language=response_language)


@pytest.mark.parametrize("username", tuple(DemoSessions().users))
@pytest.mark.parametrize(
    "prompt,tool,levels,key",
    [
        (
            "welche stationen kennst du",
            "list_stations",
            STATIONS_BY_LEVEL,
            "station_id",
        ),
        (
            "Welche Produkte kennst du?",
            "list_products",
            PRODUCTS_BY_LEVEL,
            "product_id",
        ),
    ],
)
def test_server_demo_discovery_returns_exact_rls_authorized_entities(
    username, prompt, tool, levels, key
):
    factory = PostgreSqlSessionFactory(DATABASE_URL)
    service = DiscoveryRunService(
        lambda context: PostgreSqlFactoryDiscoveryRepository(factory, context)
    )
    app = create_app(
        service,
        run_store=InMemoryAgentRunStore(),
        demo_sessions=DemoSessions(),
        security_context_resolver=BearerTokenSecurityContextResolver.from_environment(
            {"MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN": "synthetic-only-token"}
        ),
    )
    try:
        with TestClient(app, headers={"X-Demo-Session": "1"}) as browser:
            browser.post(
                "/api/v1/auth/switch", json={"username": username}
            ).raise_for_status()
            identity = browser.get("/api/v1/auth/me").json()
            response = browser.post(
                "/api/v1/runs", json={"message": prompt, "response_language": "DE"}
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["status"] == "success"
            assert [call["tool"] for call in body["tool_calls"]] == [tool]
            ceiling = DataClassification[identity["clearance"]]
            expected = sorted(
                item for level in levels[: int(ceiling) + 1] for item in level
            )
            policy, observation = service.observations[-1]
            entities = observation[
                "stations" if tool == "list_stations" else "products"
            ]
            assert sorted(item[key] for item in entities) == expected
            assert policy.mcp_clearance_ceiling == ceiling
            assert body["data_classification"] == ceiling.name
            assert all(
                item["classification"] == int(ceiling_for_id)
                for ceiling_for_id, ids in enumerate(levels)
                for item in entities
                if item[key] in ids
            )
            references = sorted(
                item["value"]
                for item in body["identifiers"]
                if item["type"] == ("station" if tool == "list_stations" else "product")
            )
            if tool == "list_stations":
                assert references == expected
            else:
                # Product observations also reference stations. The existing
                # twelve-reference presentation bound must not be expanded here.
                assert set(references) <= set(expected)
                assert all(identifier in body["answer"] for identifier in expected)
            hidden = {item for ids in levels for item in ids} - set(expected)
            assert all(identifier not in response.text for identifier in hidden)
            assert service.model_requests
    finally:
        factory.dispose()


@pytest.mark.parametrize("username", ["demo-public", "demo-confidential", "demo-admin"])
def test_hidden_lookup_and_mixed_discovery_fail_neutrally_before_agent(username):
    service = DiscoveryRunService(
        lambda _: (_ for _ in ()).throw(AssertionError("Must not load data"))
    )
    with TestClient(
        create_app(
            service,
            run_store=InMemoryAgentRunStore(),
            demo_sessions=DemoSessions(),
            security_context_resolver=BearerTokenSecurityContextResolver.from_environment(
                {"MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN": "synthetic-only-token"}
            ),
        ),
        headers={"X-Demo-Session": "1"},
    ) as browser:
        browser.post(
            "/api/v1/auth/switch", json={"username": username}
        ).raise_for_status()
        for message in [
            "S07",
            "Welche Stationen kennst du? Details zu S07",
            "Welche Stationen kennst du? SECRET CUSTOMER PLAN",
        ]:
            response = browser.post(
                "/api/v1/runs", json={"message": message, "response_language": "DE"}
            )
            assert response.status_code == 404
            assert response.json()["code"] == "requested_data_unavailable"
            assert "S07" not in response.text
        assert service.observations == []
        assert service.model_requests == []


def test_reseeding_is_idempotent_and_preserves_an_unrelated_operator_record():
    from uuid import UUID, uuid4

    from sqlalchemy import create_engine, delete, select
    from sqlalchemy.orm import Session

    from industrial_ai_agent.infrastructure.persistence.demo_seed import (
        FACTORY_ID,
        STATION_CLASSIFICATIONS,
        seed_demo_data,
    )
    from industrial_ai_agent.infrastructure.persistence.models import StationRecord

    url = os.getenv("FACTORY_DATABASE_ADMIN_URL")
    assert url
    engine = create_engine(url)
    owned_id = uuid4()
    try:
        with Session(engine) as session, session.begin():
            session.add(
                StationRecord(
                    id=owned_id,
                    factory_id=UUID(FACTORY_ID),
                    code="S99",
                    name="Synthetic operator-owned record",
                    classification=3,
                )
            )
        for _ in range(2):
            seed_demo_data(url)
            with Session(engine) as session:
                records = tuple(session.scalars(select(StationRecord)))
                assert {
                    row.code: row.classification for row in records if row.code != "S99"
                } == STATION_CLASSIFICATIONS
                assert (
                    session.get(StationRecord, owned_id).name
                    == "Synthetic operator-owned record"
                )
                assert len(records) == len(STATION_CLASSIFICATIONS) + 1
    finally:
        with Session(engine) as session, session.begin():
            session.execute(delete(StationRecord).where(StationRecord.id == owned_id))
        engine.dispose()
