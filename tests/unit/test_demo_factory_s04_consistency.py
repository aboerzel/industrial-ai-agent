from pathlib import Path

from industrial_ai_agent.domain.machine_status import MachineState
from industrial_ai_agent.domain.product_history import (
    ProductId,
    ProductionStepStatus,
    StationId,
)
from industrial_ai_agent.infrastructure.demo_factory_scenarios import (
    S04_TROUBLESHOOTING_ERROR_CODE,
)
from industrial_ai_agent.infrastructure.in_memory_lexical_knowledge_retriever import (
    InMemoryBm25KnowledgeRetriever,
    load_markdown_chunks,
)
from industrial_ai_agent.infrastructure.in_memory_machine_status_repository import (
    InMemoryMachineStatusRepository,
)
from industrial_ai_agent.infrastructure.in_memory_product_history_repository import (
    InMemoryProductHistoryRepository,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_general_s04_demo_data_and_knowledge_share_the_quality_fault() -> None:
    status = InMemoryMachineStatusRepository().get_machine_status(StationId("S04"))
    history = InMemoryProductHistoryRepository().get_product_history(ProductId("P4711"))
    results = InMemoryBm25KnowledgeRetriever(
        load_markdown_chunks(_PROJECT_ROOT / "knowledge_base")
    ).search(f"S04 {S04_TROUBLESHOOTING_ERROR_CODE}", limit=3)

    assert status is not None
    assert status.state is MachineState.FAULTED
    assert status.active_error_code == S04_TROUBLESHOOTING_ERROR_CODE
    assert history is not None
    assert history.steps[-1].station_id == StationId("S04")
    assert history.steps[-1].status is ProductionStepStatus.FAILED
    assert history.steps[-1].error_code == S04_TROUBLESHOOTING_ERROR_CODE
    assert any(S04_TROUBLESHOOTING_ERROR_CODE in result.content for result in results)
