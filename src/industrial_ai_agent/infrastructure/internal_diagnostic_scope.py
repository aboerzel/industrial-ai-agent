"""RLS-bound preflight for the structured INTERNAL diagnostic API contract."""

import asyncio

from industrial_ai_agent.agent.run_classification_policy import InternalDiagnosticTarget
from industrial_ai_agent.domain.product_history import ProductId, StationId
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlMachineStatusRepository,
    PostgreSqlProductHistoryRepository,
    PostgreSqlSessionFactory,
)


class PostgreSqlInternalDiagnosticScopeValidator:
    """Accept targets only when their required projections are visible at INTERNAL."""

    def __init__(self, session_factory: PostgreSqlSessionFactory) -> None:
        self._session_factory = session_factory
        self._security_context = SecurityContext(
            subject_id="industrial-agent-internal",
            roles=("industrial-agent-internal",),
            clearance=DataClassification.INTERNAL,
            authenticated=True,
        )

    async def is_available(self, target: InternalDiagnosticTarget) -> bool:
        return await asyncio.to_thread(self._is_available, target)

    def _is_available(self, target: InternalDiagnosticTarget) -> bool:
        product_history = PostgreSqlProductHistoryRepository(
            self._session_factory, self._security_context
        ).get_product_history(ProductId(target.product_id))
        machine_status = PostgreSqlMachineStatusRepository(
            self._session_factory, self._security_context
        ).get_machine_status(StationId(target.station_id))
        return bool(
            product_history is not None
            and machine_status is not None
            and product_history.classification <= DataClassification.INTERNAL
            and machine_status.classification <= DataClassification.INTERNAL
        )
