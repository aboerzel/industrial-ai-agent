"""Deterministic response-language selection for troubleshooting runs."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Protocol


class ResponseLanguage(StrEnum):
    """Closed set of user-facing response languages supported by the demo."""

    DE = "DE"
    EN = "EN"

    @property
    def display_name(self) -> str:
        return "German" if self is ResponseLanguage.DE else "English"


class DetectedResponseLanguage(StrEnum):
    """Provider-independent result of local natural-language identification."""

    DE = "DE"
    EN = "EN"
    OTHER = "OTHER"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class ResponseLanguageDetector(Protocol):
    """Inner port for deterministic, offline response-language identification."""

    def detect(self, text: str) -> DetectedResponseLanguage: ...


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
_RESPONSE_URL_PATTERN = re.compile(
    r"(?:https?://|www\.)\S+|\b[^\s@]+@[^\s@]+\b", re.IGNORECASE
)
_RESPONSE_FENCE_PATTERN = re.compile(r"(?m)^[ \t]*```[A-Za-z0-9_+.-]*[ \t]*$")
_RESPONSE_STRUCTURAL_HEADING_PATTERN = re.compile(
    r"(?im)^[ \t]{0,3}#{1,6}[ \t]+Likely Root Cause[ \t]*$"
)
_RESPONSE_MARKDOWN_DELIMITER_PATTERN = re.compile(r"`+")
_RESPONSE_TOKEN_PATTERN = re.compile(r"[^\W_]+(?:[-_.:/][^\W_]+)*", re.UNICODE)
_TECHNICAL_RESPONSE_TOKENS = frozenset(
    {
        "BLOCKED",
        "CLOSED",
        "ERROR",
        "FAILED",
        "FAULTED",
        "IDLE",
        "NOT_REQUIRED",
        "OK",
        "OPEN",
        "PENDING",
        "RUNNING",
        "STOPPED",
        "SUCCEEDED",
        "UNKNOWN",
        "API",
        "HTTP",
        "HTTPS",
        "LLM",
        "MCP",
        "PLC",
        "RLS",
    }
)


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


def is_response_language_compliant(
    text: str,
    response_language: ResponseLanguage,
    detector: ResponseLanguageDetector,
) -> bool:
    """Accept only selected-language prose or language-neutral technical content.

    Unknown natural-language prose fails closed. URLs, identifiers, and closed uppercase
    status values remain language-neutral. Markdown code delimiters do not make prose
    exempt from the user-facing language contract.
    """
    if not text.strip():
        return False
    prose, removed_urls = _strip_language_neutral_urls(text)
    prose = _RESPONSE_FENCE_PATTERN.sub(" ", prose)
    prose = _RESPONSE_STRUCTURAL_HEADING_PATTERN.sub(" ", prose)
    prose = _RESPONSE_MARKDOWN_DELIMITER_PATTERN.sub(" ", prose)
    tokens = _RESPONSE_TOKEN_PATTERN.findall(prose)
    natural_language_tokens = tuple(
        token for token in tokens if not _is_technical_response_token(token)
    )
    if not natural_language_tokens:
        return bool(tokens or removed_urls) and len(tokens) <= 4
    detected = detector.detect(" ".join(natural_language_tokens))
    return detected.value == response_language.value


def _is_technical_response_token(token: str) -> bool:
    cased_characters = tuple(character for character in token if character.isalpha())
    return (
        token in _TECHNICAL_RESPONSE_TOKENS
        or (
            any(character.isdigit() for character in token)
            and (
                not cased_characters
                or token.isupper()
                or any(separator in token for separator in "-_.:/")
            )
        )
        or "_" in token
        or "/" in token
        or (
            any(separator in token for separator in "-.:")
            and len(cased_characters) >= 2
            and all(character.isupper() for character in cased_characters)
        )
    )


def _strip_language_neutral_urls(text: str) -> tuple[str, bool]:
    stripped, count = _RESPONSE_URL_PATTERN.subn(" ", text)
    return stripped, count > 0


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
        "model_not_configured": "No model is configured for this request.",
        "model_capability_mismatch": (
            "The configured model does not support this request."
        ),
        "model_egress_denied": "Model execution is not permitted for this request.",
        "mcp_service_unavailable": "A required MCP service is unavailable.",
        "llm_rate_limit": (
            "The language model is temporarily unavailable because its usage limit "
            "has been reached. Please try again later."
        ),
        "llm_quota_exceeded": (
            "The language model is temporarily unavailable because its usage limit "
            "has been reached. Please try again later."
        ),
        "llm_provider_unavailable": (
            "The language model provider is temporarily unavailable. Please try "
            "again later."
        ),
        "llm_provider_request_invalid": (
            "The language model provider rejected this request. Please try again later."
        ),
        "model_output_invalid": "The model returned an invalid final response.",
        "tool_execution_failed": "A required tool could not complete the request.",
        "internal_error": "The agent run could not be completed.",
        "agent_execution_timeout": "The agent run exceeded its execution time limit.",
        "evidence_requirements_unsatisfied": (
            "The investigation could not be completed because required evidence is still missing."
        ),
        "evidence_source_unavailable": (
            "The investigation cannot continue because an authorized evidence source is unavailable."
        ),
        "recovery_incomplete": "The requested recovery was not completed.",
        "recovery_blocked": "The requested recovery was blocked before execution.",
        "recovery_failed": "The requested recovery did not pass verification.",
        "recovery_succeeded": "The requested recovery was completed and verified.",
    }
    german = {
        "requested_data_unavailable": "Die angeforderten Daten sind nicht verfügbar.",
        "diagnostic_target_unavailable": "Das angeforderte Diagnoseziel ist nicht verfügbar.",
        "run_not_found": "Der angeforderte Run existiert nicht.",
        "run_not_waiting_for_approval": "Der Run wartet nicht auf eine Freigabe.",
        "no_eligible_model": "Für diese Anfrage ist kein geeignetes Modell verfügbar.",
        "model_not_configured": "Für diese Anfrage ist kein Modell konfiguriert.",
        "model_capability_mismatch": (
            "Das konfigurierte Modell unterstützt diese Anfrage nicht."
        ),
        "model_egress_denied": "Die Modellausführung ist für diese Anfrage nicht zulässig.",
        "mcp_service_unavailable": "Ein erforderlicher MCP-Service ist nicht verfügbar.",
        "llm_rate_limit": (
            "Das Sprachmodell ist aufgrund eines Nutzungslimits vorübergehend nicht "
            "verfügbar. Bitte versuchen Sie es später erneut."
        ),
        "llm_quota_exceeded": (
            "Das Sprachmodell ist aufgrund eines Nutzungslimits vorübergehend nicht "
            "verfügbar. Bitte versuchen Sie es später erneut."
        ),
        "llm_provider_unavailable": (
            "Der Anbieter des Sprachmodells ist vorübergehend nicht verfügbar. Bitte "
            "versuchen Sie es später erneut."
        ),
        "llm_provider_request_invalid": (
            "Der Anbieter des Sprachmodells hat diese Anfrage abgelehnt. Bitte "
            "versuchen Sie es später erneut."
        ),
        "model_output_invalid": "Das Modell hat keine gültige finale Antwort geliefert.",
        "tool_execution_failed": "Ein erforderliches Werkzeug konnte die Anfrage nicht abschließen.",
        "internal_error": "Der Agent-Run konnte nicht abgeschlossen werden.",
        "agent_execution_timeout": "Der Agent-Run hat sein Ausfuehrungszeitlimit ueberschritten.",
        "evidence_requirements_unsatisfied": (
            "Die Untersuchung konnte nicht abgeschlossen werden, da erforderliche Evidenz fehlt."
        ),
        "evidence_source_unavailable": (
            "Die Untersuchung kann nicht fortgesetzt werden, da eine autorisierte Evidenzquelle nicht verfügbar ist."
        ),
        "recovery_incomplete": "Die angeforderte Recovery wurde nicht abgeschlossen.",
        "recovery_blocked": "Die angeforderte Recovery wurde vor der Ausführung blockiert.",
        "recovery_failed": "Die angeforderte Recovery hat die Verifikation nicht bestanden.",
        "recovery_succeeded": (
            "Die angeforderte Recovery wurde abgeschlossen und verifiziert."
        ),
    }
    messages = german if response_language is ResponseLanguage.DE else english
    return messages.get(error_code, messages["internal_error"])
