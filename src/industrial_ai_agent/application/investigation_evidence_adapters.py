"""Adapters from current capability result contracts to trusted evidence observations."""

from __future__ import annotations

from collections.abc import Iterable

from industrial_ai_agent.domain.investigation_evidence import (
    DocumentationEvidence,
    EvidenceSource,
    MachineStateEvidence,
)
from industrial_ai_agent.tools.documentation_search import DocumentationSearchResult
from industrial_ai_agent.tools.machine_status import MachineStatusResult


def machine_state_evidence_from_result(
    result: MachineStatusResult,
    *,
    source: EvidenceSource,
) -> MachineStateEvidence | None:
    """Translate a found status result into its tool-independent observation type."""
    if not result.found or result.state is None:
        return None
    return MachineStateEvidence(
        station_id=result.station_id,
        state=result.state,
        active_fault_id=result.active_error_code,
        source=source,
        data_classification=result.classification,
    )


def documentation_evidence_from_result(
    result: DocumentationSearchResult,
    *,
    fault_id: str,
    source: EvidenceSource,
) -> DocumentationEvidence | None:
    """Translate catalog-tagged result references into fault-relevant evidence.

    The adapter intentionally trusts explicit retrieval metadata only. Query text and
    document body content are not relevance proofs, and no model-generated statement
    reaches this boundary.
    """
    normalized_fault_id = fault_id.strip().upper()
    document_ids = tuple(
        sorted(
            {
                item.document_id
                for item in result.results
                if normalized_fault_id
                in _trusted_fault_ids(item.metadata.get("fault_ids"))
            }
        )
    )
    if not document_ids:
        return None
    return DocumentationEvidence(
        fault_id=normalized_fault_id,
        document_ids=document_ids,
        source=source,
        data_classification=max(
            item.classification
            for item in result.results
            if item.document_id in document_ids
        ),
    )


def _trusted_fault_ids(value: object) -> frozenset[str]:
    """Accept only the explicit catalog metadata shape used by trusted retrieval."""
    if not isinstance(value, Iterable) or isinstance(value, str | bytes):
        return frozenset()
    return frozenset(
        item.strip().upper() for item in value if isinstance(item, str) and item.strip()
    )
