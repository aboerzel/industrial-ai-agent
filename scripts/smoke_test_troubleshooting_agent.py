from pathlib import Path

from industrial_ai_agent.agent.troubleshooting_agent import (
    AgentRunStatus,
    TroubleshootingAgent,
)
from industrial_ai_agent.domain.machine_status import MachineStatus
from industrial_ai_agent.domain.product_history import (
    ProductHistory,
    ProductId,
    StationId,
)
from industrial_ai_agent.infrastructure.in_memory_machine_status_repository import (
    InMemoryMachineStatusRepository,
)
from industrial_ai_agent.infrastructure.in_memory_product_history_repository import (
    InMemoryProductHistoryRepository,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    load_llm_configuration,
)
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.local_environment import (
    load_local_environment,
)
from industrial_ai_agent.tools.machine_status import MachineStatusCapability
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RecordingProductHistoryRepository:
    def __init__(self) -> None:
        self._delegate = InMemoryProductHistoryRepository()
        self.requested_product_ids: list[ProductId] = []

    def get_product_history(self, product_id: ProductId) -> ProductHistory | None:
        self.requested_product_ids.append(product_id)
        return self._delegate.get_product_history(product_id)


class RecordingMachineStatusRepository:
    def __init__(self) -> None:
        self._delegate = InMemoryMachineStatusRepository()
        self.requested_station_ids: list[StationId] = []

    def get_machine_status(self, station_id: StationId) -> MachineStatus | None:
        self.requested_station_ids.append(station_id)
        return self._delegate.get_machine_status(station_id)


def main() -> None:
    load_local_environment(PROJECT_ROOT / ".env")
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    product_repository = RecordingProductHistoryRepository()
    machine_repository = RecordingMachineStatusRepository()

    with OpenAICompatibleLLMClient(configuration) as llm_client:
        agent = TroubleshootingAgent(
            llm_client,
            ProductHistoryCapability(product_repository),
            MachineStatusCapability(machine_repository),
        )
        result = agent.answer(
            "P4711 failed during production. Investigate what happened and check "
            "the current status of the relevant station."
        )

    if product_repository.requested_product_ids != [ProductId("P4711")]:
        raise RuntimeError("Smoke test did not select get_product_history for P4711")
    if machine_repository.requested_station_ids != [StationId("S04")]:
        raise RuntimeError("Smoke test did not select get_machine_status for S04")
    if result.status is not AgentRunStatus.SUCCESS:
        raise RuntimeError(f"Smoke test ended with status {result.status}")
    if result.tool_call_count != 2:
        raise RuntimeError("Smoke test did not execute exactly two tool calls")
    if result.final_answer is None:
        raise RuntimeError("Successful smoke test did not return a final answer")

    print("tool_calls=get_product_history(P4711),get_machine_status(S04)")
    print(f"status={result.status.value}")
    print(result.final_answer)


if __name__ == "__main__":
    main()
