from pathlib import Path

from dotenv import load_dotenv

from industrial_ai_agent.agent.troubleshooting_agent import TroubleshootingAgent
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
    load_dotenv(PROJECT_ROOT / ".env")
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
        product_answer = agent.answer("Why was product P4711 rejected?")
        machine_answer = agent.answer("What is the current status of station S12?")

    if product_repository.requested_product_ids != [ProductId("P4711")]:
        raise RuntimeError("Smoke test did not select get_product_history for P4711")
    if machine_repository.requested_station_ids != [StationId("S12")]:
        raise RuntimeError("Smoke test did not select get_machine_status for S12")

    print("tool_call=get_product_history product_id=P4711")
    print(product_answer)
    print("tool_call=get_machine_status station_id=S12")
    print(machine_answer)


if __name__ == "__main__":
    main()
