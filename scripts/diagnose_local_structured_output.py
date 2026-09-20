"""Run content-free, repeated local structured-output compatibility diagnostics."""

from __future__ import annotations

import argparse
import json
from enum import StrEnum
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ValidationError

from industrial_ai_agent.agent.llm import (
    LLMJsonSchema,
    LLMMessage,
    LLMProviderError,
    LLMReasoningEffort,
    LLMRequest,
    LLMResponseFormat,
    MessageRole,
    ModelId,
)
from industrial_ai_agent.infrastructure.llm.configuration import load_model_catalog
from industrial_ai_agent.infrastructure.llm.openai_compatible import (
    OpenAICompatibleLLMClient,
)
from industrial_ai_agent.infrastructure.llm.provider_contract import (
    StructuredValidationFailure,
    _safe_validation_failures,
)
from industrial_ai_agent.infrastructure.local_environment import load_local_environment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _Flat(BaseModel):
    status: str
    count: int


class _Nullable(BaseModel):
    status: str
    note: str | None


class _Default(BaseModel):
    status: str
    retry_count: int = 0


class _Detail(BaseModel):
    code: str
    quantity: int


class _Nested(BaseModel):
    status: str
    detail: _Detail


class _NestedList(BaseModel):
    status: str
    items: list[_Detail]


class _Severity(StrEnum):
    LOW = "LOW"
    HIGH = "HIGH"


class _ProductionRepresentative(BaseModel):
    status: str
    optional_note: str | None
    retry_count: int = 0
    severity: _Severity
    detail: _Detail
    items: list[_Detail]


_SCHEMAS: tuple[tuple[str, type[BaseModel], str], ...] = (
    ("flat_required", _Flat, "Return JSON with status OK and count 1."),
    ("optional_nullable", _Nullable, "Return JSON with status OK and note null."),
    ("field_default", _Default, "Return JSON with status OK. Omit retry_count."),
    (
        "nested_object",
        _Nested,
        "Return JSON with status OK and detail {code: primary, quantity: 1}.",
    ),
    (
        "list_nested_objects",
        _NestedList,
        "Return JSON with status OK and items [{code: item, quantity: 1}].",
    ),
    (
        "production_representative",
        _ProductionRepresentative,
        (
            "Return JSON only. Set status OK, optional_note null, severity LOW, "
            "detail {code: primary, quantity: 1}, and items "
            "[{code: item, quantity: 1}]."
        ),
    ),
)


def _request(schema_name: str, model: type[BaseModel], prompt: str) -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content=prompt),),
        response_format=LLMResponseFormat(
            json_schema=LLMJsonSchema(
                name=f"phase5b_{schema_name}",
                schema_definition=model.model_json_schema(),
            )
        ),
        reasoning_effort=LLMReasoningEffort.NONE,
    )


def _safe_validation(
    response_text: str | None, model: type[BaseModel]
) -> dict[str, object]:
    if not isinstance(response_text, str):
        return _invalid_json_result(False)
    raw = response_text.strip()
    contains_json = raw.startswith(("{", "["))
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return _invalid_json_result(contains_json)
    try:
        model.model_validate(parsed)
    except ValidationError as error:
        return {
            "response_contains_json": contains_json,
            "json_parses_syntactically": True,
            "pydantic_validation_succeeds": False,
            "validation_failures": [
                failure.model_dump(mode="json")
                for failure in _safe_validation_failures(error)
            ],
        }
    return {
        "response_contains_json": contains_json,
        "json_parses_syntactically": True,
        "pydantic_validation_succeeds": True,
        "validation_failures": [],
    }


def _invalid_json_result(contains_json: bool) -> dict[str, object]:
    return {
        "response_contains_json": contains_json,
        "json_parses_syntactically": False,
        "pydantic_validation_succeeds": False,
        "validation_failures": [
            StructuredValidationFailure(
                path=(), category="other", validation_code="invalid_json"
            ).model_dump(mode="json")
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", action="append", required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions < 1:
        raise ValueError("--repetitions must be positive")

    load_local_environment(PROJECT_ROOT / ".env")
    configuration = load_model_catalog(PROJECT_ROOT / "config" / "model_catalog.toml")
    client = OpenAICompatibleLLMClient(configuration)
    results: list[dict[str, object]] = []
    try:
        for model_id in args.model_id:
            for schema_name, model, prompt in _SCHEMAS:
                attempts: list[dict[str, object]] = []
                request = _request(schema_name, model, prompt)
                for _ in range(args.repetitions):
                    started = perf_counter()
                    try:
                        response = client.chat(ModelId(model_id), request)
                    except LLMProviderError as error:
                        attempts.append(
                            {
                                "duration_ms": (perf_counter() - started) * 1000,
                                "provider_http_status": error.provider_http_status,
                                "provider_error": error.code,
                            }
                        )
                    else:
                        attempts.append(
                            {
                                "duration_ms": (perf_counter() - started) * 1000,
                                "provider_http_status": 200,
                                "schema_hash": response.request_diagnostics.structured_schema_hash,
                                **_safe_validation(response.text, model),
                            }
                        )
                results.append(
                    {
                        "model_id": model_id,
                        "schema": schema_name,
                        "repetitions": args.repetitions,
                        "verified": all(
                            attempt.get("pydantic_validation_succeeds") is True
                            for attempt in attempts
                        ),
                        "attempts": attempts,
                    }
                )
    finally:
        client.close()
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
