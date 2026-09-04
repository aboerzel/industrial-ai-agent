import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from mcp.client.stdio import StdioServerParameters
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
from industrial_ai_agent.agent.llm import LLMResponse, ModelProfile
from industrial_ai_agent.agent.model_egress import (
    DataClassification,
    EgressCheckedLLMClient,
)
from industrial_ai_agent.agent.model_routing import (
    CostPreference,
    DeterministicModelRouter,
    LLMCapability,
    TaskRequirements,
    TaskRole,
)
from industrial_ai_agent.agent.troubleshooting_agent import TroubleshootingAgent
from industrial_ai_agent.infrastructure.factory_mcp_client import (
    FactoryMcpTransport,
    StreamableHttpServerParameters,
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
from industrial_ai_agent.infrastructure.local_environment import (
    load_local_environment,
)
from industrial_ai_agent.infrastructure.mcp_langchain_tool_provider import (
    McpLangChainToolProvider,
)
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_PATH = (
    PROJECT_ROOT / "evals" / "datasets" / "troubleshooting_tool_selection_v1.jsonl"
)
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "model_profiles.toml"


class ToolSelectionEvalCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    user_input: str
    expected_tool: str
    expected_arguments: dict[str, Any]

    @field_validator("case_id", "user_input", "expected_tool")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Value must not be empty")
        return normalized_value


class ToolSelectionEvalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    user_input: str
    expected_tool: str
    expected_arguments: dict[str, Any]
    actual_tool: str | None
    actual_arguments: dict[str, Any] | None
    tool_call_count: int
    tool_selection_correct: bool
    arguments_correct: bool
    error: str | None = None


class ToolSelectionEvalReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset: str
    model_profile: str
    orchestration_path: str = "manual"
    total_cases: int
    correct_tool_selections: int
    correct_arguments: int
    tool_selection_accuracy: float
    argument_accuracy: float
    results: tuple[ToolSelectionEvalResult, ...]


def load_eval_cases(path: Path) -> tuple[ToolSelectionEvalCase, ...]:
    cases: list[ToolSelectionEvalCase] = []
    case_ids: set[str] = set()

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            raw_case = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON on dataset line {line_number}") from error
        try:
            case = ToolSelectionEvalCase.model_validate(raw_case)
        except ValidationError as error:
            raise ValueError(
                f"Invalid eval case on dataset line {line_number}"
            ) from error
        if case.case_id in case_ids:
            raise ValueError(f"Duplicate eval case_id: {case.case_id}")
        case_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise ValueError("Eval dataset must contain at least one case")
    return tuple(cases)


def score_tool_selection(
    case: ToolSelectionEvalCase,
    response: LLMResponse,
) -> ToolSelectionEvalResult:
    tool_call_count = len(response.tool_calls)
    first_tool_call = response.tool_calls[0] if response.tool_calls else None
    actual_tool = first_tool_call.name if first_tool_call is not None else None
    actual_arguments = (
        first_tool_call.arguments if first_tool_call is not None else None
    )
    tool_selection_correct = tool_call_count == 1 and actual_tool == case.expected_tool
    arguments_correct = (
        tool_selection_correct and actual_arguments == case.expected_arguments
    )
    error = (
        None
        if tool_call_count == 1
        else f"Expected exactly one tool call, received {tool_call_count}"
    )

    return ToolSelectionEvalResult(
        case_id=case.case_id,
        user_input=case.user_input,
        expected_tool=case.expected_tool,
        expected_arguments=case.expected_arguments,
        actual_tool=actual_tool,
        actual_arguments=actual_arguments,
        tool_call_count=tool_call_count,
        tool_selection_correct=tool_selection_correct,
        arguments_correct=arguments_correct,
        error=error,
    )


def aggregate_results(
    *,
    dataset: str,
    model_profile: str,
    orchestration_path: str = "manual",
    results: Sequence[ToolSelectionEvalResult],
) -> ToolSelectionEvalReport:
    if not results:
        raise ValueError("Cannot aggregate an empty eval result set")

    total_cases = len(results)
    correct_tool_selections = sum(result.tool_selection_correct for result in results)
    correct_arguments = sum(result.arguments_correct for result in results)
    return ToolSelectionEvalReport(
        dataset=dataset,
        model_profile=model_profile,
        orchestration_path=orchestration_path,
        total_cases=total_cases,
        correct_tool_selections=correct_tool_selections,
        correct_arguments=correct_arguments,
        tool_selection_accuracy=correct_tool_selections / total_cases,
        argument_accuracy=correct_arguments / total_cases,
        results=tuple(results),
    )


def run_tool_selection_eval(
    *,
    cases: Sequence[ToolSelectionEvalCase],
    request_tool_selection: Callable[[str], LLMResponse],
    dataset: str,
    model_profile: str,
    orchestration_path: str = "manual",
) -> ToolSelectionEvalReport:
    results: list[ToolSelectionEvalResult] = []
    for case in cases:
        try:
            response = request_tool_selection(case.user_input)
        except Exception as error:  # noqa: BLE001
            results.append(_error_result(case, error))
            continue
        results.append(score_tool_selection(case, response))

    return aggregate_results(
        dataset=dataset,
        model_profile=model_profile,
        orchestration_path=orchestration_path,
        results=results,
    )


async def run_tool_selection_eval_async(
    *,
    cases: Sequence[ToolSelectionEvalCase],
    request_tool_selection: Callable[[str], Awaitable[LLMResponse]],
    dataset: str,
    model_profile: str,
    orchestration_path: str,
) -> ToolSelectionEvalReport:
    results: list[ToolSelectionEvalResult] = []
    for case in cases:
        try:
            response = await request_tool_selection(case.user_input)
        except Exception as error:  # noqa: BLE001
            results.append(_error_result(case, error))
            continue
        results.append(score_tool_selection(case, response))
    return aggregate_results(
        dataset=dataset,
        model_profile=model_profile,
        orchestration_path=orchestration_path,
        results=results,
    )


def _error_result(
    case: ToolSelectionEvalCase,
    error: Exception,
) -> ToolSelectionEvalResult:
    return ToolSelectionEvalResult(
        case_id=case.case_id,
        user_input=case.user_input,
        expected_tool=case.expected_tool,
        expected_arguments=case.expected_arguments,
        actual_tool=None,
        actual_arguments=None,
        tool_call_count=0,
        tool_selection_correct=False,
        arguments_correct=False,
        error=f"{type(error).__name__}: {error}",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the first troubleshooting LLM tool-selection decision."
    )
    parser.add_argument("--profile", default="troubleshooting")
    parser.add_argument(
        "--agent-path",
        choices=("manual", "langgraph"),
        default="manual",
    )
    parser.add_argument(
        "--tool-transport",
        choices=("direct", "mcp"),
        default="direct",
        help="Use MCP only with the LangGraph path.",
    )
    parser.add_argument("--mcp-transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--mcp-url", default="http://127.0.0.1:8001/mcp")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path; evals/results is ignored by Git.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    load_local_environment(PROJECT_ROOT / ".env")
    cases = load_eval_cases(args.dataset)
    configuration = load_llm_configuration(args.config)
    requested_profile = ModelProfile(args.profile)
    request_classification = DataClassification.INTERNAL
    if args.tool_transport == "mcp" and args.agent_path != "langgraph":
        raise ValueError("MCP tool transport requires --agent-path langgraph")

    with OpenAICompatibleLLMClient(configuration) as adapter:
        llm_client = EgressCheckedLLMClient(
            adapter,
            configuration,
            request_classification,
        )
        product_history = ProductHistoryCapability(InMemoryProductHistoryRepository())
        machine_status = MachineStatusCapability(InMemoryMachineStatusRepository())
        if args.agent_path == "langgraph":
            model_profile = _route_requested_profile(
                configuration,
                requested_profile,
                TaskRole.TOOL_SELECTION,
                request_classification,
            )
            agent = LangGraphTroubleshootingAgent(
                LLMClientChatModel(llm_client, model_profile),
                product_history,
                machine_status,
                mcp_tool_provider=(
                    McpLangChainToolProvider(_mcp_transport_from_args(args))
                    if args.tool_transport == "mcp"
                    else None
                ),
            )
        else:
            model_profile = requested_profile
            agent = TroubleshootingAgent(
                llm_client,
                product_history,
                machine_status,
                model_profile=model_profile,
            )
        if args.tool_transport == "mcp":
            if not isinstance(agent, LangGraphTroubleshootingAgent):
                raise RuntimeError("MCP tool transport requires a LangGraph agent")
            report = asyncio.run(
                run_tool_selection_eval_async(
                    cases=cases,
                    request_tool_selection=agent.request_tool_selection_via_mcp,
                    dataset=args.dataset.name,
                    model_profile=model_profile.name,
                    orchestration_path="langgraph-mcp",
                )
            )
        else:
            report = run_tool_selection_eval(
                cases=cases,
                request_tool_selection=agent.request_tool_selection,
                dataset=args.dataset.name,
                model_profile=model_profile.name,
                orchestration_path=args.agent_path,
            )

    serialized_report = report.model_dump_json(indent=2)
    print(serialized_report)
    if args.output is not None:
        output_path = (
            args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(f"{serialized_report}\n", encoding="utf-8")


def _route_requested_profile(
    configuration: LLMConfiguration,
    requested_profile: ModelProfile,
    task_role: TaskRole,
    data_classification: DataClassification,
) -> ModelProfile:
    candidates = tuple(
        profile
        for profile in configuration.get_routing_profiles()
        if profile.profile == requested_profile
    )
    if not candidates:
        raise ValueError(f"Unknown model profile: {requested_profile.name}")
    candidate = candidates[0]
    return DeterministicModelRouter().route(
        TaskRequirements(
            task_role=task_role,
            required_capabilities=frozenset(
                {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
            ),
            minimum_quality=candidate.quality_class,
            cost_preference=CostPreference.BALANCED,
            data_classification=data_classification,
        ),
        candidates,
    )


def _mcp_transport_from_args(args: argparse.Namespace) -> FactoryMcpTransport:
    if args.mcp_transport == "http":
        return StreamableHttpServerParameters(url=args.mcp_url)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "industrial_ai_agent.infrastructure.factory_mcp_server"],
    )


if __name__ == "__main__":
    main()
