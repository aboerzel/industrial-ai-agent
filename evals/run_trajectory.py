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
from industrial_ai_agent.agent.llm import ModelProfile
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
from industrial_ai_agent.agent.troubleshooting_agent import (
    AgentRunResult,
    AgentRunStatus,
    ExecutedToolCall,
    TroubleshootingAgent,
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
    PROJECT_ROOT / "evals" / "datasets" / "troubleshooting_trajectory_v1.jsonl"
)
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "model_profiles.toml"


class TrajectoryEvalCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    user_input: str
    expected_trajectory: tuple[ExecutedToolCall, ...]
    expected_status: AgentRunStatus

    @field_validator("case_id", "user_input")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Value must not be empty")
        return normalized_value


class TrajectoryEvalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    user_input: str
    expected_trajectory: tuple[ExecutedToolCall, ...]
    actual_trajectory: tuple[ExecutedToolCall, ...]
    expected_status: AgentRunStatus
    actual_status: AgentRunStatus | None
    expected_tool_calls: int
    actual_tool_calls: int
    positionally_correct_tool_calls: int
    tool_call_slots: int
    exact_trajectory_correct: bool
    termination_correct: bool
    task_success: bool
    final_answer: str | None
    error: str | None = None


class TrajectoryEvalReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset: str
    model_profile: str
    orchestration_path: str = "manual"
    total_cases: int
    successful_tasks: int
    exact_trajectories: int
    correct_terminations: int
    positionally_correct_tool_calls: int
    tool_call_slots: int
    task_success_rate: float
    exact_trajectory_accuracy: float
    tool_call_accuracy: float
    termination_accuracy: float
    cases_with_missing_tool_calls: tuple[str, ...]
    cases_with_additional_tool_calls: tuple[str, ...]
    failed_case_ids: tuple[str, ...]
    results: tuple[TrajectoryEvalResult, ...]


def load_eval_cases(path: Path) -> tuple[TrajectoryEvalCase, ...]:
    cases: list[TrajectoryEvalCase] = []
    case_ids: set[str] = set()

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            raw_case: Any = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON on dataset line {line_number}") from error
        try:
            case = TrajectoryEvalCase.model_validate(raw_case)
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


def score_trajectory(
    case: TrajectoryEvalCase,
    run_result: AgentRunResult,
) -> TrajectoryEvalResult:
    expected_trajectory = case.expected_trajectory
    actual_trajectory = run_result.executed_tool_calls
    positionally_correct_tool_calls = sum(
        expected_call == actual_call
        for expected_call, actual_call in zip(
            expected_trajectory,
            actual_trajectory,
            strict=False,
        )
    )
    tool_call_slots = max(len(expected_trajectory), len(actual_trajectory))
    exact_trajectory_correct = expected_trajectory == actual_trajectory
    termination_correct = case.expected_status is run_result.status

    return TrajectoryEvalResult(
        case_id=case.case_id,
        user_input=case.user_input,
        expected_trajectory=expected_trajectory,
        actual_trajectory=actual_trajectory,
        expected_status=case.expected_status,
        actual_status=run_result.status,
        expected_tool_calls=len(expected_trajectory),
        actual_tool_calls=len(actual_trajectory),
        positionally_correct_tool_calls=positionally_correct_tool_calls,
        tool_call_slots=tool_call_slots,
        exact_trajectory_correct=exact_trajectory_correct,
        termination_correct=termination_correct,
        task_success=exact_trajectory_correct and termination_correct,
        final_answer=run_result.final_answer,
    )


def aggregate_results(
    *,
    dataset: str,
    model_profile: str,
    orchestration_path: str = "manual",
    results: Sequence[TrajectoryEvalResult],
) -> TrajectoryEvalReport:
    if not results:
        raise ValueError("Cannot aggregate an empty eval result set")

    total_cases = len(results)
    successful_tasks = sum(result.task_success for result in results)
    exact_trajectories = sum(result.exact_trajectory_correct for result in results)
    correct_terminations = sum(result.termination_correct for result in results)
    positionally_correct_tool_calls = sum(
        result.positionally_correct_tool_calls for result in results
    )
    tool_call_slots = sum(result.tool_call_slots for result in results)
    return TrajectoryEvalReport(
        dataset=dataset,
        model_profile=model_profile,
        orchestration_path=orchestration_path,
        total_cases=total_cases,
        successful_tasks=successful_tasks,
        exact_trajectories=exact_trajectories,
        correct_terminations=correct_terminations,
        positionally_correct_tool_calls=positionally_correct_tool_calls,
        tool_call_slots=tool_call_slots,
        task_success_rate=successful_tasks / total_cases,
        exact_trajectory_accuracy=exact_trajectories / total_cases,
        tool_call_accuracy=(
            positionally_correct_tool_calls / tool_call_slots
            if tool_call_slots
            else 1.0
        ),
        termination_accuracy=correct_terminations / total_cases,
        cases_with_missing_tool_calls=tuple(
            result.case_id
            for result in results
            if result.actual_tool_calls < result.expected_tool_calls
        ),
        cases_with_additional_tool_calls=tuple(
            result.case_id
            for result in results
            if result.actual_tool_calls > result.expected_tool_calls
        ),
        failed_case_ids=tuple(
            result.case_id for result in results if not result.task_success
        ),
        results=tuple(results),
    )


def run_trajectory_eval(
    *,
    cases: Sequence[TrajectoryEvalCase],
    run_agent: Callable[[str], AgentRunResult],
    dataset: str,
    model_profile: str,
    orchestration_path: str = "manual",
) -> TrajectoryEvalReport:
    results: list[TrajectoryEvalResult] = []
    for case in cases:
        try:
            run_result = run_agent(case.user_input)
        except Exception as error:  # noqa: BLE001
            results.append(_error_result(case, error))
            continue
        results.append(score_trajectory(case, run_result))

    return aggregate_results(
        dataset=dataset,
        model_profile=model_profile,
        orchestration_path=orchestration_path,
        results=results,
    )


async def run_trajectory_eval_async(
    *,
    cases: Sequence[TrajectoryEvalCase],
    run_agent: Callable[[str], Awaitable[AgentRunResult]],
    dataset: str,
    model_profile: str,
    orchestration_path: str,
) -> TrajectoryEvalReport:
    results: list[TrajectoryEvalResult] = []
    for case in cases:
        try:
            run_result = await run_agent(case.user_input)
        except Exception as error:  # noqa: BLE001
            results.append(_error_result(case, error))
            continue
        results.append(score_trajectory(case, run_result))
    return aggregate_results(
        dataset=dataset,
        model_profile=model_profile,
        orchestration_path=orchestration_path,
        results=results,
    )


def _error_result(
    case: TrajectoryEvalCase,
    error: Exception,
) -> TrajectoryEvalResult:
    expected_tool_calls = len(case.expected_trajectory)
    return TrajectoryEvalResult(
        case_id=case.case_id,
        user_input=case.user_input,
        expected_trajectory=case.expected_trajectory,
        actual_trajectory=(),
        expected_status=case.expected_status,
        actual_status=None,
        expected_tool_calls=expected_tool_calls,
        actual_tool_calls=0,
        positionally_correct_tool_calls=0,
        tool_call_slots=expected_tool_calls,
        exact_trajectory_correct=False,
        termination_correct=False,
        task_success=False,
        final_answer=None,
        error=f"{type(error).__name__}: {error}",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate complete bounded troubleshooting-agent trajectories."
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
                TaskRole.TROUBLESHOOTING,
                request_classification,
            )
            agent = LangGraphTroubleshootingAgent(
                LLMClientChatModel(llm_client, model_profile),
                product_history,
                machine_status,
                mcp_tool_provider=(
                    McpLangChainToolProvider(_factory_server_parameters())
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
                run_trajectory_eval_async(
                    cases=cases,
                    run_agent=agent.aanswer_via_mcp,
                    dataset=args.dataset.name,
                    model_profile=model_profile.name,
                    orchestration_path="langgraph-mcp",
                )
            )
        else:
            report = run_trajectory_eval(
                cases=cases,
                run_agent=agent.answer,
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


def _factory_server_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "industrial_ai_agent.infrastructure.factory_mcp_server"],
    )


if __name__ == "__main__":
    main()
