"""Offline Lingua adapter for fail-closed response-language identification."""

import re
from functools import cached_property

from lingua import Language, LanguageDetector, LanguageDetectorBuilder

from industrial_ai_agent.agent.response_language import (
    DetectedResponseLanguage,
    ResponseLanguageDetector,
)


class LinguaResponseLanguageDetector(ResponseLanguageDetector):
    """Identify German, English, mixed, unknown, and unsupported-language prose."""

    @cached_property
    def _detector(self) -> LanguageDetector:
        return (
            LanguageDetectorBuilder.from_all_spoken_languages()
            .with_minimum_relative_distance(0.05)
            .build()
        )

    @cached_property
    def _supported_language_detector(self) -> LanguageDetector:
        return LanguageDetectorBuilder.from_languages(
            Language.ENGLISH, Language.GERMAN
        ).build()

    def detect(self, text: str) -> DetectedResponseLanguage:
        normalized = text.strip()
        if not normalized:
            return DetectedResponseLanguage.UNKNOWN
        language = self._detector.detect_language_of(normalized)
        if language is None:
            return DetectedResponseLanguage.UNKNOWN
        confidence = self._detector.compute_language_confidence_values(normalized)[0]
        if language in {Language.GERMAN, Language.ENGLISH} and self._is_mixed(
            normalized, language, confidence.value
        ):
            return DetectedResponseLanguage.MIXED
        if language == Language.GERMAN:
            return DetectedResponseLanguage.DE
        if language == Language.ENGLISH:
            return DetectedResponseLanguage.EN
        return DetectedResponseLanguage.OTHER

    def _is_mixed(
        self, text: str, detected_language: Language, overall_confidence: float
    ) -> bool:
        """Detect material German/English code-switching without lexical lists.

        Lingua's multi-language span API can split ordinary monolingual sentences at
        shared words. Token-level bilingual votes are therefore used only when the
        whole-text result is uncertain, and a material minority is required.
        """
        if overall_confidence >= 0.8:
            return False
        tokens = re.findall(r"[^\W\d_]+", text, flags=re.UNICODE)
        votes = {Language.ENGLISH: 0, Language.GERMAN: 0}
        for token in tokens:
            # Proper names, German nouns, and acronyms are poor code-switch signals.
            # Their casing lets us exclude them without maintaining vocabulary lists.
            if len(token) < 3 or token.istitle() or token.isupper():
                continue
            confidences = (
                self._supported_language_detector.compute_language_confidence_values(
                    token
                )
            )
            if (
                len(confidences) < 2
                or confidences[0].value - confidences[1].value < 0.1
            ):
                continue
            votes[confidences[0].language] += 1
        total_votes = sum(votes.values())
        minority_votes = votes[
            Language.GERMAN
            if detected_language == Language.ENGLISH
            else Language.ENGLISH
        ]
        return total_votes >= 2 and minority_votes / total_votes >= 0.25
