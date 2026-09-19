"""PostgreSQL adapter for persistent model assignments."""

from sqlalchemy import text

from industrial_ai_agent.agent.llm import ModelId
from industrial_ai_agent.agent.model_selection import (
    ModelAssignment,
    ModelConsumerId,
    ModelSelectionMode,
    ModelSelectionPolicy,
)
from industrial_ai_agent.domain.security import DataClassification, SecurityContext
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlSessionFactory,
)


class PostgreSqlModelAssignmentRepository:
    def __init__(
        self,
        session_factory: PostgreSqlSessionFactory,
        security_context: SecurityContext,
    ) -> None:
        self._session_factory = session_factory
        self._security_context = security_context

    def get(
        self,
        consumer_id: ModelConsumerId,
        data_classification: DataClassification,
    ) -> ModelAssignment | None:
        with self._session_factory.session(self._security_context) as session:
            row = (
                session.execute(
                    text(
                        """
                    SELECT consumer_id, data_classification, model_id, selection_mode,
                           selection_policy, updated_at, updated_by
                    FROM agent_runtime.model_assignments
                    WHERE consumer_id = :consumer_id
                      AND data_classification = :data_classification
                    """
                    ),
                    {
                        "consumer_id": consumer_id.value,
                        "data_classification": int(data_classification),
                    },
                )
                .mappings()
                .one_or_none()
            )
        return _assignment_from_row(row) if row is not None else None

    def list(self) -> tuple[ModelAssignment, ...]:
        with self._session_factory.session(self._security_context) as session:
            rows = session.execute(
                text(
                    """
                    SELECT consumer_id, data_classification, model_id, selection_mode,
                           selection_policy, updated_at, updated_by
                    FROM agent_runtime.model_assignments
                    ORDER BY consumer_id, data_classification
                    """
                )
            ).mappings()
            return tuple(_assignment_from_row(row) for row in rows)

    def upsert(self, assignment: ModelAssignment) -> ModelAssignment:
        with self._session_factory.session(self._security_context) as session:
            row = (
                session.execute(
                    text(
                        """
                    INSERT INTO agent_runtime.model_assignments (
                        consumer_id, data_classification, model_id, selection_mode,
                        selection_policy, updated_by
                    ) VALUES (
                        :consumer_id, :data_classification, :model_id, :selection_mode,
                        :selection_policy, :updated_by
                    )
                    ON CONFLICT (consumer_id, data_classification) DO UPDATE SET
                        model_id = EXCLUDED.model_id,
                        selection_mode = EXCLUDED.selection_mode,
                        selection_policy = EXCLUDED.selection_policy,
                        updated_at = CURRENT_TIMESTAMP,
                        updated_by = EXCLUDED.updated_by
                    RETURNING consumer_id, data_classification, model_id, selection_mode,
                              selection_policy, updated_at, updated_by
                    """
                    ),
                    {
                        "consumer_id": assignment.consumer_id.value,
                        "data_classification": int(assignment.data_classification),
                        "model_id": (
                            assignment.model_id.value
                            if assignment.model_id is not None
                            else None
                        ),
                        "selection_mode": assignment.selection_mode.value,
                        "selection_policy": (
                            assignment.selection_policy.value
                            if assignment.selection_policy is not None
                            else None
                        ),
                        "updated_by": assignment.updated_by,
                    },
                )
                .mappings()
                .one()
            )
            return _assignment_from_row(row)


def _assignment_from_row(row: object) -> ModelAssignment:
    return ModelAssignment(
        consumer_id=ModelConsumerId(row["consumer_id"]),  # type: ignore[index]
        data_classification=DataClassification(row["data_classification"]),  # type: ignore[index]
        model_id=(ModelId(row["model_id"]) if row["model_id"] is not None else None),  # type: ignore[index]
        selection_mode=ModelSelectionMode(row["selection_mode"]),  # type: ignore[index]
        selection_policy=(
            ModelSelectionPolicy(row["selection_policy"])
            if row["selection_policy"] is not None
            else None
        ),  # type: ignore[index]
        updated_at=row["updated_at"],  # type: ignore[index]
        updated_by=row["updated_by"],  # type: ignore[index]
    )
