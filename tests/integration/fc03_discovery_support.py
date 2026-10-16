"""Local FC03 fixtures: real RLS, Factory MCP, agent and API; fake model only."""

import json
import os
import re
from contextlib import asynccontextmanager

from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from sqlalchemy import text
from sqlalchemy.engine import make_url

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import FinishReason, LLMResponse, ModelProfile
from industrial_ai_agent.agent.mcp_tool_provider import McpToolSession
from industrial_ai_agent.agent.run_classification_policy import (
    resolve_demo_discovery_tool,
)
from industrial_ai_agent.agent.tool_policy import ToolOperation, ToolPolicy
from industrial_ai_agent.domain.security import SecurityContext
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.demo_security import (
    BearerTokenSecurityContextResolver,
)
from industrial_ai_agent.infrastructure.api.demo_sessions import DemoSessions
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.api.run_store import InMemoryAgentRunStore
from industrial_ai_agent.infrastructure.factory_mcp_server import (
    create_factory_mcp_server,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlFactoryDiscoveryRepository,
    PostgreSqlMachineStatusRepository,
    PostgreSqlProductHistoryRepository,
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.tools.factory_discovery import FactoryDiscoveryCapability
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

PRODUCT_LEVELS = (
    ("P4101", "P4102"),
    ("P4900", "P4901"),
    ("P4711", "P4801", "P4802", "P4805", "P4811"),
    ("P9001", "P9002"),
)
STATION_LEVELS = (("S01", "S05"), ("S02", "S03"), ("S04", "S06"), ("S07", "S08"))


def product_ids(value):
    return sorted(set(re.findall(r"\bP\d{4}\b", value or "")))


def station_ids(value):
    return sorted(set(re.findall(r"\bS\d{2}\b", value or "")))


def expected_ids(clearance):
    return sorted(
        product for level in PRODUCT_LEVELS[: int(clearance) + 1] for product in level
    )


class DiscoveryService:
    def __init__(self, factory, *, model_mode="fallback"):
        self.factory = factory
        self.model_mode = model_mode
        self.traces = []

    async def run_with_policy(
        self, message, *, run_policy, response_language, **kwargs
    ):
        station_discovery = resolve_demo_discovery_tool(message) == "list_stations"
        tool_name = "list_stations" if station_discovery else "list_products"
        collection = "stations" if station_discovery else "products"
        identifier = "station_id" if station_discovery else "product_id"
        extract_ids = station_ids if station_discovery else product_ids
        context = SecurityContext(
            run_policy.mcp_client_identity,
            ("reader",),
            run_policy.mcp_clearance_ceiling,
            True,
        )
        repository = PostgreSqlFactoryDiscoveryRepository(self.factory, context)
        trace = {"prompt": message, "clearance": context.clearance.name}
        self.traces.append(trace)
        with self.factory.connection(context) as connection:
            trace["database_ids"] = list(
                connection.scalars(
                    text("SELECT code FROM station ORDER BY code")
                    if station_discovery
                    else text("SELECT product_code FROM product ORDER BY product_code")
                )
            )
            trace["bypass_rls"] = connection.scalar(
                text(
                    "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"
                )
            )
        trace["repository_ids"] = [
            getattr(row, identifier).value for row in getattr(repository, tool_name)()
        ]
        server = create_factory_mcp_server(
            product_history=ProductHistoryCapability(
                PostgreSqlProductHistoryRepository(self.factory, context)
            ),
            machine_status=MachineStatusCapability(
                PostgreSqlMachineStatusRepository(self.factory, context)
            ),
            factory_discovery=FactoryDiscoveryCapability(repository),
        )

        class Provider:
            @asynccontextmanager
            async def open_session(self):
                async def inventory():
                    result = await server.call_tool(tool_name, {})
                    assert not result.is_error
                    payload = result.structured_content
                    trace["factory_mcp"] = payload
                    trace["factory_mcp_ids"] = [
                        row[identifier] for row in payload[collection]
                    ]
                    trace["agent_raw_ids"] = trace["factory_mcp_ids"]
                    return json.dumps(payload)

                yield McpToolSession(
                    tools=(
                        StructuredTool.from_function(
                            coroutine=inventory,
                            name=tool_name,
                            description="Read the complete authorized inventory.",
                        ),
                    ),
                    discovered_tool_names=(tool_name,),
                    server_name="real-factory-fixture",
                    server_version="test",
                    protocol_version="test",
                    tool_policies=(ToolPolicy(tool_name, ToolOperation.READ),),
                )

        mode = self.model_mode

        class FakeModel:
            def chat(self, profile, request):
                observations = [
                    item.content
                    for item in request.messages
                    if item.role.value == "tool"
                ]
                assert observations, "The guarded inventory must precede the model"
                trace["model_input_ids"] = extract_ids("\n".join(observations))
                answer = "S01." if station_discovery else "P4101."
                if mode == "fallback":
                    answer += "\n\n## Next steps\n\nReview product history."
                elif mode == "invented":
                    answer += " S99." if station_discovery else " P9999."
                trace["model_output_ids"] = extract_ids(answer)
                trace["model_output"] = answer
                return LLMResponse(
                    text=json.dumps({"answer": answer, "next_steps": []}),
                    finish_reason=FinishReason.STOP,
                )

        class RecordingAgent(LangGraphTroubleshootingAgent):
            @staticmethod
            def _restore_public_state(state):
                trace["tool_message_ids"] = extract_ids(
                    "\n".join(
                        str(item.content)
                        for item in state["messages"]
                        if isinstance(item, ToolMessage)
                    )
                )
                trace["effective_classification"] = int(
                    state["effective_classification"]
                )
                return LangGraphTroubleshootingAgent._restore_public_state(state)

        agent = RecordingAgent(
            LLMClientChatModel(FakeModel(), ModelProfile("local_quality")),
            mcp_tool_provider=Provider(),
            run_classification=run_policy.data_classification,
        )
        result = await agent.aanswer_via_mcp(
            message, response_language=response_language
        )
        trace["agent_result"] = result.model_dump(mode="json")
        trace["reference_ids"] = [
            reference.value
            for reference in result.identifiers
            if reference.type.value == ("station" if station_discovery else "product")
        ]
        trace["public_projection_ids"] = sorted(
            set(extract_ids(result.final_answer)) | set(trace["reference_ids"])
        )
        return result


def fixture_app(*, model_mode="fallback", durable=False):
    database = os.environ["FACTORY_DATABASE_URL"]
    url = make_url(database)
    if url.host not in {"127.0.0.1", "localhost"} or not (
        url.database and url.database.startswith("verification_")
    ):
        raise ValueError("FC03 requires a disposable loopback verification database")
    factory = PostgreSqlSessionFactory(database)
    service = DiscoveryService(factory, model_mode=model_mode)
    store = InMemoryAgentRunStore()
    app = create_app(
        service,
        run_store=None if durable else store,
        run_store_factory=(lambda context: PostgreSqlAgentRunStore(factory, context))
        if durable
        else None,
        demo_sessions=DemoSessions(),
        security_context_resolver=BearerTokenSecurityContextResolver.from_environment(
            {"MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN": "synthetic-fc03-no-provider"}
        ),
    )
    return app, service, store, factory
