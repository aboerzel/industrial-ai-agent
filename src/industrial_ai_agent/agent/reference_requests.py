"""Exact neutral reference reads; parsing selects behavior, never authority."""

import re
from dataclasses import dataclass

from industrial_ai_agent.domain.maintenance_ticket import is_maintenance_ticket_id
from industrial_ai_agent.tools.tool_contracts import SearchDocumentationArguments


@dataclass(frozen=True, slots=True)
class ReferenceRead:
    target: str
    argument: str
    first_tools: tuple[str, ...]
    allowed_tools: frozenset[str]
    station_status_only: bool = False

    def first_arguments(self) -> dict[str, object]:
        if self.argument == "query":
            return SearchDocumentationArguments(query=self.target).model_dump()
        return {self.argument: self.target}

    def permits(self, tool: str, arguments: dict[str, object]) -> bool:
        if tool not in self.allowed_tools:
            return False
        if self.argument == "station_id" and tool == "search_documentation":
            # ADR-020 verifies documentation against the observed active fault.
            return True
        return arguments.get(self.argument) == self.target


_STATION_TOOLS = ("get_machine_status", "get_station_overview")
_PRODUCT_TOOLS = frozenset({"get_product_overview", "get_product_history"})
_FORMS = (
    (
        r"(?:UNTERSUCHE STATION|INVESTIGATE STATION|PRÜFE DEN AKTUELLEN STATUS VON STATION|WHAT IS THE CURRENT STATUS OF STATION) (S\d{2,3})",
        "station_id",
        _STATION_TOOLS,
        frozenset((*_STATION_TOOLS, "search_documentation")),
    ),
    (
        r"(?:UNTERSUCHE PRODUKT|INVESTIGATE PRODUCT) (P\d{4})",
        "product_id",
        ("get_product_overview",),
        _PRODUCT_TOOLS,
    ),
    (
        r"(?:ZEIGE DIE PRODUKTHISTORIE VON|SHOW ME THE PRODUCTION HISTORY FOR) (P\d{4})",
        "product_id",
        ("get_product_history",),
        _PRODUCT_TOOLS,
    ),
    (
        r"(?:ZEIGE DAS WARTUNGSTICKET|SHOW TICKET) (MT-(?:[A-F0-9]{12}|S[0-9]{2}-[0-9]{8}))",
        "ticket_id",
        ("get_maintenance_ticket",),
        frozenset({"get_maintenance_ticket"}),
    ),
    (
        r"(?:UNTERSUCHE|INVESTIGATE) ([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)",
        "query",
        ("search_documentation",),
        frozenset({"search_documentation"}),
    ),
)


def resolve_reference_read(message: str) -> ReferenceRead | None:
    """Recognize only complete existing UI forms; classification remains separate."""
    normalized = " ".join(message.strip().upper().rstrip(".!?").split())
    for pattern, argument, first_tools, allowed_tools in _FORMS:
        match = re.fullmatch(pattern, normalized)
        if match is None:
            continue
        target = match[1]
        if argument == "query" and is_maintenance_ticket_id(target):
            return None
        return ReferenceRead(
            target,
            argument,
            first_tools,
            allowed_tools,
            station_status_only=argument == "station_id"
            and normalized.startswith(
                (
                    "PRÜFE DEN AKTUELLEN STATUS",
                    "WHAT IS THE CURRENT STATUS",
                )
            ),
        )
    return None
