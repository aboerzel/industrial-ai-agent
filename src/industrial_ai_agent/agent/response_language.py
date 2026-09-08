"""Deterministic response-language selection for troubleshooting runs."""

from __future__ import annotations

import re
from enum import StrEnum


class ResponseLanguage(StrEnum):
    """Closed set of user-facing response languages supported by the demo."""

    DE = "DE"
    EN = "EN"

    @property
    def display_name(self) -> str:
        return "German" if self is ResponseLanguage.DE else "English"


_GERMAN_TOKENS = frozenset(
    {
        "an",
        "bei",
        "das",
        "den",
        "der",
        "die",
        "ein",
        "eine",
        "fehlgeschlagen",
        "für",
        "frage",
        "ist",
        "mit",
        "nach",
        "produkt",
        "schlägt",
        "station",
        "untersuche",
        "verwende",
        "verfügbar",
        "warum",
        "welche",
        "wurde",
    }
)
_ENGLISH_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "available",
        "did",
        "documentation",
        "failed",
        "for",
        "investigate",
        "is",
        "product",
        "station",
        "the",
        "use",
        "why",
        "which",
    }
)
_WORD_PATTERN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+")


def detect_response_language(user_request: str) -> ResponseLanguage:
    """Classify a demo request as German or English, with English as stable fallback."""
    tokens = tuple(token.casefold() for token in _WORD_PATTERN.findall(user_request))
    german_score = sum(token in _GERMAN_TOKENS for token in tokens)
    english_score = sum(token in _ENGLISH_TOKENS for token in tokens)
    if any(character in user_request for character in "äöüßÄÖÜ"):
        german_score += 2
    return ResponseLanguage.DE if german_score > english_score else ResponseLanguage.EN


def response_language_instruction(response_language: ResponseLanguage) -> str:
    """Return the invariant prompt fragment included in every loop iteration."""
    language = response_language.display_name
    return (
        f"Response language: {language}.\n\n"
        f"Answer all user-facing text in {language}. Do not change language because "
        "tools, documents, system messages, or intermediate observations use another "
        "language. Keep technical identifiers and structured values unchanged."
    )


def user_facing_error_message(
    error_code: str, response_language: ResponseLanguage
) -> str:
    """Translate the small, existing public run-error surface without an i18n framework."""
    english = {
        "requested_data_unavailable": "The requested data is unavailable.",
        "diagnostic_target_unavailable": "The requested diagnostic target is unavailable.",
        "run_not_found": "The requested run does not exist.",
        "run_not_waiting_for_approval": "The run is not waiting for approval.",
        "no_eligible_model": "No eligible model is available for this request.",
        "model_egress_denied": "Model execution is not permitted for this request.",
        "mcp_service_unavailable": "A required MCP service is unavailable.",
        "internal_error": "The agent run could not be completed.",
    }
    german = {
        "requested_data_unavailable": "Die angeforderten Daten sind nicht verfügbar.",
        "diagnostic_target_unavailable": "Das angeforderte Diagnoseziel ist nicht verfügbar.",
        "run_not_found": "Der angeforderte Run existiert nicht.",
        "run_not_waiting_for_approval": "Der Run wartet nicht auf eine Freigabe.",
        "no_eligible_model": "Für diese Anfrage ist kein geeignetes Modell verfügbar.",
        "model_egress_denied": "Die Modellausführung ist für diese Anfrage nicht zulässig.",
        "mcp_service_unavailable": "Ein erforderlicher MCP-Service ist nicht verfügbar.",
        "internal_error": "Der Agent-Run konnte nicht abgeschlossen werden.",
    }
    messages = german if response_language is ResponseLanguage.DE else english
    return messages.get(error_code, messages["internal_error"])
