"""Real delivered frontend/API/graph with synthetic ports for safe browser gates."""

import json
import runpy
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from langchain_core.tools import StructuredTool
from pydantic import create_model

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import FinishReason, LLMResponse, ModelProfile
from industrial_ai_agent.agent.mcp_tool_provider import McpToolSession
from industrial_ai_agent.agent.reference_requests import resolve_reference_read
from industrial_ai_agent.agent.tool_policy import ToolOperation, ToolPolicy
from industrial_ai_agent.domain.investigation_evidence import InvestigationType
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.tools.tool_contracts import SearchDocumentationArguments

fixture = runpy.run_path(str(Path(__file__).with_name("demo-auth-server.py")))
app = fixture["app"]


class ReferenceService:
    async def run_with_policy(
        self, message, *, run_policy, response_language, **kwargs
    ):
        intent = resolve_reference_read(message)
        assert intent is not None
        tool_name = next(
            name for name in intent.first_tools if name in run_policy.allowed_tool_names
        )
        classification = int(run_policy.mcp_clearance_ceiling)

        class Provider:
            @asynccontextmanager
            async def open_session(self):
                async def read(**arguments):
                    payload = {
                        intent.argument: intent.target,
                        "found": True,
                        "classification": classification,
                    }
                    if intent.argument == "station_id":
                        payload.update(state="RUNNING", active_error_code=None)
                        if tool_name == "get_station_overview":
                            payload.update(
                                name="Synthetic station",
                                recent_products=[],
                                recent_product_ids=[],
                            )
                    elif tool_name == "get_product_history":
                        payload["steps"] = []
                    elif tool_name == "get_product_overview":
                        payload.update(
                            latest_station_id=None,
                            latest_status=None,
                            latest_error_code=None,
                            passed_station_ids=[],
                        )
                    elif intent.argument == "ticket_id":
                        payload.update(
                            station_id="S02",
                            status="CLOSED",
                            summary="Synthetic ticket",
                        )
                    else:
                        payload = {
                            "query": intent.target,
                            "results": [
                                {
                                    "document_id": "CONFIDENTIAL",
                                    "source": "documents/confidential.txt",
                                    "chunk_id": "CONFIDENTIAL::chunk-001",
                                    "content": intent.target,
                                    "classification": classification,
                                    "metadata": {
                                        "title": "Synthetic document",
                                        "fault_ids": [intent.target],
                                    },
                                }
                            ],
                        }
                    return json.dumps(payload)

                tool = StructuredTool.from_function(
                    coroutine=read,
                    name=tool_name,
                    description="Synthetic local read",
                    args_schema=SearchDocumentationArguments
                    if intent.argument == "query"
                    else create_model("ReferenceArgs", **{intent.argument: (str, ...)}),
                )
                yield McpToolSession(
                    tools=(tool,),
                    discovered_tool_names=(tool_name,),
                    server_name="synthetic",
                    server_version="test",
                    protocol_version="test",
                    tool_policies=(ToolPolicy(tool_name, ToolOperation.READ),),
                )

        class Model:
            def chat(self, profile, request):
                return LLMResponse(
                    text="SYNTHETIC read completed.", finish_reason=FinishReason.STOP
                )

        return await LangGraphTroubleshootingAgent(
            LLMClientChatModel(Model(), ModelProfile("local_quality")),
            mcp_tool_provider=Provider(),
            run_classification=run_policy.data_classification,
            investigation_type=InvestigationType.STATION_LIST
            if intent.argument == "station_id" and classification == 0
            else InvestigationType.STATION_TROUBLESHOOTING,
            normalize_structured_final_output=False,
        ).aanswer_via_mcp(message, response_language=response_language, **kwargs)


app.state.run_service = ReferenceService()

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(sys.argv[1]),
        log_level="critical",
        access_log=False,
    )
