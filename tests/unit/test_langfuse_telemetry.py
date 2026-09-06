import sys
from types import SimpleNamespace

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    MessageRole,
    ModelProfile,
)
from industrial_ai_agent.domain.security import DataClassification
from industrial_ai_agent.infrastructure.llm.configuration import LLMConfiguration
from industrial_ai_agent.infrastructure.observed_llm_client import ObservedLLMClient
from industrial_ai_agent.infrastructure.telemetry import (
    Telemetry,
    TelemetryConfiguration,
    _should_export_to_langfuse,
    configure_telemetry,
)


class _ResponseClient:
    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        del profile, request
        return LLMResponse(
            text="private model response",
            finish_reason=FinishReason.STOP,
            usage=LLMUsage(input_tokens=11, output_tokens=7, total_tokens=18),
        )


def test_langfuse_generation_contains_only_allowlisted_metadata() -> None:
    telemetry, exporter = _recording_langfuse_telemetry()
    client = ObservedLLMClient(
        _ResponseClient(),
        configuration=_configuration(api_cost_usd=0),
        data_classification=DataClassification.INTERNAL,
        telemetry=telemetry,
    )

    with telemetry.span("agent.run", {"run.id": "run-123"}):
        client.chat(
            ModelProfile("local_quality"),
            LLMRequest(
                messages=(LLMMessage(role=MessageRole.USER, content="private"),)
            ),
        )

    spans = {span.name: span for span in exporter.get_finished_spans()}
    agent_attributes = spans["agent.run"].attributes
    generation_attributes = spans["llm.call"].attributes

    assert agent_attributes["langfuse.observation.type"] == "agent"
    assert agent_attributes["langfuse.observation.metadata.run_id"] == "run-123"
    assert generation_attributes["langfuse.observation.type"] == "generation"
    assert generation_attributes["langfuse.observation.metadata.run_id"] == "run-123"
    assert generation_attributes["gen_ai.provider.name"] == "ollama"
    assert generation_attributes["gen_ai.request.model"] == "qwen3.5:9b"
    assert generation_attributes["gen_ai.usage.input_tokens"] == 11
    assert generation_attributes["gen_ai.usage.output_tokens"] == 7
    assert generation_attributes["gen_ai.usage.total_tokens"] == 18
    assert generation_attributes["gen_ai.usage.cost"] == 0.0
    assert "private model response" not in str(generation_attributes)


def test_rca_reasoning_generation_keeps_metadata_only_context() -> None:
    telemetry, exporter = _recording_langfuse_telemetry()
    client = ObservedLLMClient(
        _ResponseClient(),
        configuration=_configuration(api_cost_usd=0),
        data_classification=DataClassification.INTERNAL,
        telemetry=telemetry,
        operation_type="rca.reasoning",
        rca_focus="overview",
    )

    with telemetry.span(
        "rca.reasoning", {"run.id": "run-123", "rca.focus": "overview"}
    ):
        client.chat(
            ModelProfile("local_quality"),
            LLMRequest(
                messages=(LLMMessage(role=MessageRole.USER, content="private RCA"),)
            ),
        )

    generation = next(
        span for span in exporter.get_finished_spans() if span.name == "llm.call"
    )
    assert generation.attributes["langfuse.observation.type"] == "generation"
    assert (
        generation.attributes["langfuse.observation.metadata.operation"]
        == "rca.reasoning"
    )
    assert (
        generation.attributes["langfuse.observation.metadata.rca_focus"] == "overview"
    )
    assert generation.attributes["gen_ai.usage.total_tokens"] == 18
    rendered = str(generation.attributes)
    assert "private RCA" not in rendered
    assert "private model response" not in rendered


def test_langfuse_filter_rejects_infrastructure_spans() -> None:
    # The SDK asks at span start, before Langfuse attributes are attached.
    assert _should_export_to_langfuse(SimpleNamespace(name="llm.call", attributes={}))
    assert _should_export_to_langfuse(
        SimpleNamespace(
            name="llm.call",
            attributes={"langfuse.observation.type": "generation"},
        )
    )
    assert not _should_export_to_langfuse(
        SimpleNamespace(name="GET /health", attributes={})
    )
    assert not _should_export_to_langfuse(
        SimpleNamespace(
            name="mcp.tool", attributes={"langfuse.observation.type": "tool"}
        )
    )


def test_missing_langfuse_credentials_leave_telemetry_and_execution_usable() -> None:
    telemetry = configure_telemetry(
        TelemetryConfiguration(enabled=True, langfuse_enabled=True)
    )
    client = ObservedLLMClient(
        _ResponseClient(),
        configuration=_configuration(api_cost_usd=0),
        data_classification=DataClassification.INTERNAL,
        telemetry=telemetry,
    )

    try:
        with telemetry.span("agent.run", {"run.id": "run-123"}):
            response = client.chat(
                ModelProfile("local_quality"),
                LLMRequest(
                    messages=(LLMMessage(role=MessageRole.USER, content="private"),)
                ),
            )
        assert response.text == "private model response"
        assert telemetry.enabled
        assert not telemetry.langfuse_enabled
    finally:
        telemetry.shutdown()


def test_unavailable_langfuse_initialization_does_not_block_llm_execution(
    monkeypatch,
) -> None:
    class _UnavailableLangfuse:
        def __init__(self, **_: object) -> None:
            raise OSError("unavailable")

    monkeypatch.setitem(
        sys.modules, "langfuse", SimpleNamespace(Langfuse=_UnavailableLangfuse)
    )
    telemetry = configure_telemetry(
        TelemetryConfiguration(
            enabled=True,
            langfuse_enabled=True,
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
    )
    client = ObservedLLMClient(
        _ResponseClient(),
        configuration=_configuration(api_cost_usd=0),
        data_classification=DataClassification.INTERNAL,
        telemetry=telemetry,
    )

    try:
        with telemetry.span("agent.run", {"run.id": "run-123"}):
            response = client.chat(
                ModelProfile("local_quality"),
                LLMRequest(
                    messages=(LLMMessage(role=MessageRole.USER, content="private"),)
                ),
            )
        assert response.text == "private model response"
        assert not telemetry.langfuse_enabled
    finally:
        telemetry.shutdown()


def _recording_langfuse_telemetry() -> tuple[Telemetry, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    return (
        Telemetry(
            TelemetryConfiguration(enabled=True, langfuse_enabled=True),
            tracer_provider=tracer_provider,
            meter_provider=MeterProvider(),
            langfuse_client=object(),
        ),
        exporter,
    )


def _configuration(*, api_cost_usd: int | None) -> LLMConfiguration:
    return LLMConfiguration.model_validate(
        {
            "profiles": {
                "local_quality": {
                    "provider": "ollama",
                    "model": "qwen3.5:9b",
                    "base_url": "http://localhost:11434/v1",
                    "temperature": 0,
                    "authentication": "none",
                    "execution_zone": "LOCAL",
                    "capabilities": ["TEXT"],
                    "quality_class": "HIGH",
                    "cost_class": "LOW",
                    "api_cost_usd": api_cost_usd,
                }
            }
        }
    )
