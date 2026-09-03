from pathlib import Path

from dotenv import load_dotenv

from industrial_ai_agent.agent.product_history_agent import ProductHistoryAgent
from industrial_ai_agent.domain.product_history import ProductHistory, ProductId
from industrial_ai_agent.infrastructure.in_memory_product_history_repository import (
    InMemoryProductHistoryRepository,
)
from industrial_ai_agent.infrastructure.llm.configuration import (
    load_llm_configuration,
)
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.tools.product_history import ProductHistoryCapability

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RecordingProductHistoryRepository:
    def __init__(self) -> None:
        self._delegate = InMemoryProductHistoryRepository()
        self.requested_product_ids: list[ProductId] = []

    def get_product_history(self, product_id: ProductId) -> ProductHistory | None:
        self.requested_product_ids.append(product_id)
        return self._delegate.get_product_history(product_id)


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    repository = RecordingProductHistoryRepository()
    capability = ProductHistoryCapability(repository)

    with OpenAICompatibleLLMClient(configuration) as llm_client:
        agent = ProductHistoryAgent(llm_client, capability)
        answer = agent.answer("Why was product P4711 rejected?")

    if repository.requested_product_ids != [ProductId("P4711")]:
        raise RuntimeError("Smoke test did not execute get_product_history for P4711")
    print("tool_call=get_product_history product_id=P4711")
    print(answer)


if __name__ == "__main__":
    main()
