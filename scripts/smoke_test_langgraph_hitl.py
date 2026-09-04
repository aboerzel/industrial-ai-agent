import argparse
import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from industrial_ai_agent.agent.langgraph_troubleshooting_agent import (
    LangGraphTroubleshootingAgent,
)
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
from industrial_ai_agent.infrastructure.in_memory_maintenance_ticket_repository import (
    InMemoryMaintenanceTicketRepository,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    load_llm_configuration,
)
from industrial_ai_agent.infrastructure.llm.langchain_adapter import LLMClientChatModel
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.local_environment import load_local_environment
from industrial_ai_agent.tools.maintenance_ticket import MaintenanceTicketCapability

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "model_profiles.toml"
THREAD_ID = "langgraph-hitl-smoke"
PROMPT = "Create a maintenance ticket for station S04 due to E-STOP-17."


def main() -> None:
    args = _parse_args()
    load_local_environment(PROJECT_ROOT / ".env")
    configuration = load_llm_configuration(CONFIG_PATH)
    policy = ModelEgressPolicy()
    requirements = TaskRequirements(
        task_role=TaskRole.TROUBLESHOOTING,
        required_capabilities=frozenset(
            {LLMCapability.TEXT, LLMCapability.TOOL_CALLING}
        ),
        minimum_quality=QualityClass.HIGH,
        cost_preference=CostPreference.PREFER_QUALITY,
        data_classification=DataClassification.CONFIDENTIAL,
    )
    selected_profile = DeterministicModelRouter(policy).route(
        requirements,
        configuration.get_routing_profiles(),
    )
    if (
        configuration.get_execution_zone(selected_profile.name)
        is not ExecutionZone.LOCAL
    ):
        raise RuntimeError("Confidential HITL smoke selected a non-local model profile")

    ticket_repository = InMemoryMaintenanceTicketRepository()
    with OpenAICompatibleLLMClient(configuration) as adapter:
        checked_client = EgressCheckedLLMClient(
            adapter,
            configuration,
            requirements.data_classification,
            policy=policy,
        )
        agent = LangGraphTroubleshootingAgent(
            LLMClientChatModel(checked_client, selected_profile),
            maintenance_ticket=MaintenanceTicketCapability(ticket_repository),
            checkpointer=InMemorySaver(),
            run_classification=requirements.data_classification,
        )
        paused_state = agent.start(PROMPT, thread_id=THREAD_ID)
        payload = agent.get_interrupt_payload(thread_id=THREAD_ID)
        if payload is None:
            raise RuntimeError("HITL smoke expected an approval interrupt")
        final_state = agent.resume(thread_id=THREAD_ID, approval=args.approval)
        final_status = final_state["run_status"]
        final_answer = final_state["final_answer"]
        if final_status is None or final_answer is None:
            raise RuntimeError("HITL smoke did not reach a terminal state")

    print(f"selected_profile={selected_profile.name}")
    print(f"classification={requirements.data_classification.name}")
    print(f"paused_tool_call_count={paused_state['executed_tool_count']}")
    print(json.dumps(payload, sort_keys=True))
    print(f"approval={args.approval}")
    print(f"status={final_status.value}")
    print(f"ticket_count={len(ticket_repository.tickets)}")
    print(final_answer)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the explicit local LangGraph HITL approval smoke test."
    )
    parser.add_argument("--approval", choices=("approve", "reject"), required=True)
    return parser.parse_args()


if __name__ == "__main__":
    main()
