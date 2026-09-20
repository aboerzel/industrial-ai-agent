"""Content-free controlled real-model tool-decision diagnostic."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from langchain_core.tools import StructuredTool

from evals.run_real_model_quality import (
    PROJECT_ROOT,
    S04_REQUEST,
    _FirstCallTracingClient,
)
from evals.run_trajectory import DEFAULT_CONFIG_PATH
from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    MCP_TROUBLESHOOTING_SYSTEM_MESSAGE,
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import LLMReasoningEffort, ModelId
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
)
from industrial_ai_agent.agent.model_selection import ModelCapability
from industrial_ai_agent.agent.response_language import ResponseLanguage
from industrial_ai_agent.infrastructure.llm.configuration import load_model_catalog
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.local_environment import load_local_environment
from industrial_ai_agent.tools.tool_contracts import (
    GetMachineStatusArguments,
    SearchDocumentationArguments,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose real-model tool decisions.")
    parser.add_argument("--model-id", default="local_quality")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--reasoning-effort", choices=("current", "none"), default="current"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> list[dict[str, object]]:
    load_local_environment(PROJECT_ROOT / ".env")
    configuration = load_model_catalog(args.config)
    model_id = ModelId(args.model_id)
    model = configuration.get_model(model_id.value)
    reasoning_effort = (
        LLMReasoningEffort.NONE if args.reasoning_effort == "none" else None
    )
    results: list[dict[str, object]] = []
    with OpenAICompatibleLLMClient(configuration) as adapter:
        client = EgressCheckedLLMClient(
            adapter, configuration, DataClassification.INTERNAL
        )
        for _ in range(args.runs):
            tracing_client = _FirstCallTracingClient(client, model_id.value)
            tools = _production_s04_tools()
            try:
                chat_model = LLMClientChatModel(
                    tracing_client,
                    model_id,
                    supports_structured_output=(
                        ModelCapability.STRUCTURED_OUTPUT in model.capabilities
                    ),
                    reasoning_effort=reasoning_effort,
                )
                chat_model.bind_tools(tools).invoke(
                    LangGraphTroubleshootingAgent._initial_messages(
                        S04_REQUEST,
                        system_content=MCP_TROUBLESHOOTING_SYSTEM_MESSAGE,
                        response_language=ResponseLanguage.DE,
                    )
                )
            except Exception as error:  # noqa: BLE001 - metadata-only diagnostics
                summary = tracing_client.first_call_summary(
                    tuple(tool.name for tool in tools)
                )
                summary["diagnostic_error"] = type(error).__name__
            else:
                summary = tracing_client.first_call_summary(
                    tuple(tool.name for tool in tools)
                )
            results.append(summary)
    return results


def _production_s04_tools() -> tuple[StructuredTool, ...]:
    """Use the same Pydantic argument contracts exposed by the MCP capabilities."""
    return (
        StructuredTool.from_function(
            name="get_machine_status",
            description="Get the current status and active error of one station.",
            args_schema=GetMachineStatusArguments,
            func=lambda station_id: {"station_id": station_id},
        ),
        StructuredTool.from_function(
            name="search_documentation",
            description="Search technical documentation with preserved provenance.",
            args_schema=SearchDocumentationArguments,
            func=lambda query, top_k=3: {"query": query, "top_k": top_k},
        ),
    )


def main() -> None:
    args = _parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")
    runs = asyncio.run(_run(args))
    report = {
        "model_id": args.model_id,
        "reasoning_effort": args.reasoning_effort,
        "runs": runs,
        "tool_calls": f"{sum(run.get('tool_calls_present') is True for run in runs)}/{len(runs)}",
        "correct_machine_status_calls": (
            f"{sum('get_machine_status' in run.get('selected_tool_names', []) for run in runs)}/{len(runs)}"
        ),
    }
    serialized = json.dumps(report, indent=2)
    print(serialized)
    if args.output is not None:
        output = (
            args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
