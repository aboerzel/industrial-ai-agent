import argparse
import asyncio
import sys
from pathlib import Path

from mcp.client.stdio import StdioServerParameters

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import ModelProfile
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
    ExecutionZone,
    ModelEgressPolicy,
)
from industrial_ai_agent.agent.model_routing import (
    CostPreference,
    DeterministicModelRouter,
    LLMCapability,
    QualityClass,
    TaskRequirements,
    TaskRole,
)
from industrial_ai_agent.infrastructure.in_memory_machine_status_repository import (
    InMemoryMachineStatusRepository,
)
from industrial_ai_agent.infrastructure.in_memory_product_history_repository import (
    InMemoryProductHistoryRepository,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    LLMConfiguration,
    load_llm_configuration,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.local_environment import load_local_environment
from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    McpLangChainToolProvider,
)
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "model_profiles.toml"
PUBLIC_PROMPT = "Reply exactly with LANGGRAPH_LLM_OK. Do not call a tool."
CONFIDENTIAL_PROMPT = (
    "P4711 failed during production. Investigate what happened and check the current "
    "status of the relevant station."
)


def main() -> None:
    args = _parse_args()
    load_local_environment(PROJECT_ROOT / ".env")
    configuration = load_llm_configuration(CONFIG_PATH)
    policy = ModelEgressPolicy()

    if args.confidential_troubleshooting:
        requirements = TaskRequirements(
            task_role=TaskRole.TROUBLESHOOTING,
            required_capabilities=frozenset(
                {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
            ),
            minimum_quality=QualityClass.HIGH,
            cost_preference=CostPreference.PREFER_QUALITY,
            data_classification=DataClassification.CONFIDENTIAL,
        )
        candidates = configuration.get_routing_profiles()
        prompt = CONFIDENTIAL_PROMPT
    else:
        requested_profile = ModelProfile(args.profile)
        candidates = tuple(
            candidate
            for candidate in configuration.get_routing_profiles()
            if candidate.profile == requested_profile
        )
        if not candidates:
            raise ValueError(f"Unknown model profile: {requested_profile.name}")
        requirements = TaskRequirements(
            task_role=TaskRole.GENERAL_REASONING,
            required_capabilities=frozenset({LLMCapability.TEXT}),
            minimum_quality=candidates[0].quality_class,
            cost_preference=CostPreference.BALANCED,
            data_classification=DataClassification.PUBLIC,
        )
        prompt = PUBLIC_PROMPT

    selected_profile = DeterministicModelRouter(policy).route(
        requirements,
        candidates,
    )
    _assert_expected_zone(configuration, requirements, selected_profile)

    with OpenAICompatibleLLMClient(configuration) as adapter:
        checked_client = EgressCheckedLLMClient(
            adapter,
            configuration,
            requirements.data_classification,
            policy=policy,
        )
        agent = LangGraphTroubleshootingAgent(
            LLMClientChatModel(checked_client, selected_profile),
            ProductHistoryCapability(InMemoryProductHistoryRepository()),
            MachineStatusCapability(InMemoryMachineStatusRepository()),
            mcp_tool_provider=(
                McpLangChainToolProvider(_factory_server_parameters())
                if args.mcp
                else None
            ),
        )
        session_lines: list[str] = []
        if args.mcp:
            result = asyncio.run(
                agent.aanswer_via_mcp(
                    prompt,
                    session_observer=lambda session: session_lines.extend(
                        (
                            "mcp_session_initialized=true",
                            f"mcp_server={session.server_name} {session.server_version}",
                            f"mcp_protocol={session.protocol_version}",
                            f"mcp_discovered_tools={','.join(session.discovered_tool_names)}",
                        )
                    ),
                )
            )
        else:
            result = agent.answer(prompt)

    if result.final_answer is None:
        raise RuntimeError("LangGraph smoke did not return a final answer")
    if (
        not args.confidential_troubleshooting
        and result.final_answer != "LANGGRAPH_LLM_OK"
    ):
        raise RuntimeError("Synthetic LangGraph response did not match expected text")
    if args.mcp and args.confidential_troubleshooting:
        actual_tools = [call.tool for call in result.executed_tool_calls]
        expected_tools = ["get_product_history", "get_machine_status"]
        if actual_tools != expected_tools:
            raise RuntimeError(
                f"MCP troubleshooting smoke expected {expected_tools}, got {actual_tools}"
            )
    print(f"selected_profile={selected_profile.name}")
    print(f"classification={requirements.data_classification.name}")
    print(f"status={result.status.value}")
    print(f"tool_call_count={result.tool_call_count}")
    for line in session_lines:
        print(line)
    print(result.final_answer)


def _assert_expected_zone(
    configuration: LLMConfiguration,
    requirements: TaskRequirements,
    selected_profile: ModelProfile,
) -> None:
    if (
        requirements.data_classification is DataClassification.CONFIDENTIAL
        and configuration.get_execution_zone(selected_profile.name)
        is not ExecutionZone.LOCAL
    ):
        raise RuntimeError("Confidential smoke test selected a non-local profile")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run explicit LangGraph troubleshooting smoke scenarios."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--profile")
    selection.add_argument("--confidential-troubleshooting", action="store_true")
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Discover and execute read-only tools through the local factory MCP server.",
    )
    return parser.parse_args()


def _factory_server_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "industrial_ai_agent.infrastructure.factory_mcp_server"],
    )


if __name__ == "__main__":
    main()
