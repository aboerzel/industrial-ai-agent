"""Offline Lingua adapter for fail-closed response-language identification."""

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

    def detect(self, text: str) -> DetectedResponseLanguage:
        normalized = text.strip()
        if not normalized:
            return DetectedResponseLanguage.UNKNOWN
        spans = self._detector.detect_multiple_languages_of(normalized)
        detected_languages = {span.language for span in spans}
        if len(detected_languages) > 1:
            return DetectedResponseLanguage.MIXED
        language = self._detector.detect_language_of(normalized)
        if language is None:
            return DetectedResponseLanguage.UNKNOWN
        if language == Language.GERMAN:
            return DetectedResponseLanguage.DE
        if language == Language.ENGLISH:
            return DetectedResponseLanguage.EN
        return DetectedResponseLanguage.OTHER
