import sys
from types import SimpleNamespace

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from industrial_ai_agent.agent.llm import (
    FinishReason,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    LLMToolDefinition,
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


class _FixedResponseClient:
    def __init__(self, response: LLMResponse) -> None:
        self._response = response

    def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
        del profile, request
        return self._response


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


def test_usage_metric_failure_does_not_change_tool_response() -> None:
    telemetry, _ = _recording_langfuse_telemetry()

    class _BrokenCounter:
        def add(self, value: int, attributes: object) -> None:
            del value, attributes
            raise OSError("metric exporter unavailable")

    telemetry._llm_input_tokens = _BrokenCounter()  # type: ignore[assignment]
    telemetry._llm_output_tokens = _BrokenCounter()  # type: ignore[assignment]
    telemetry._llm_total_tokens = _BrokenCounter()  # type: ignore[assignment]
    telemetry._llm_tool_calls = _BrokenCounter()  # type: ignore[assignment]
    telemetry._llm_tool_input_tokens = _BrokenCounter()  # type: ignore[assignment]
    telemetry._llm_tool_output_tokens = _BrokenCounter()  # type: ignore[assignment]
    telemetry._llm_tool_tokens = _BrokenCounter()  # type: ignore[assignment]

    class _ToolResponseClient:
        def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
            del profile, request
            return LLMResponse(
                text=None,
                finish_reason=FinishReason.TOOL_CALLS,
                tool_calls=(
                    LLMToolCall(
                        id="call-1",
                        name="get_product_history",
                        arguments={"product_id": "P4711"},
                    ),
                ),
                usage=LLMUsage(input_tokens=11, output_tokens=7, total_tokens=18),
            )

    client = ObservedLLMClient(
        _ToolResponseClient(),
        configuration=_configuration(api_cost_usd=0),
        data_classification=DataClassification.CONFIDENTIAL,
        telemetry=telemetry,
    )

    response = client.chat(
        ModelProfile("local_quality"),
        _tool_request(),
    )

    assert response.finish_reason is FinishReason.TOOL_CALLS
    assert response.tool_calls[0].name == "get_product_history"
    assert response.tool_calls[0].arguments == {"product_id": "P4711"}


def test_usage_metrics_do_not_change_structured_final_response() -> None:
    telemetry, _ = _recording_langfuse_telemetry()

    class _StructuredResponseClient:
        def chat(self, profile: ModelProfile, request: LLMRequest) -> LLMResponse:
            del profile, request
            return LLMResponse(
                text='{"answer":"grounded","next_steps":[]}',
                finish_reason=FinishReason.STOP,
                usage=LLMUsage(input_tokens=11),
            )

    client = ObservedLLMClient(
        _StructuredResponseClient(),
        configuration=_configuration(api_cost_usd=0),
        data_classification=DataClassification.RESTRICTED,
        telemetry=telemetry,
    )

    response = client.chat(
        ModelProfile("local_quality"),
        LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="private"),)),
    )

    assert response.text == '{"answer":"grounded","next_steps":[]}'
    assert response.usage == LLMUsage(input_tokens=11)


def test_observed_llm_client_records_provider_usage_as_token_metrics() -> None:
    reader = InMemoryMetricReader()
    telemetry = Telemetry(
        TelemetryConfiguration(enabled=True),
        meter_provider=MeterProvider(metric_readers=[reader]),
    )
    client = ObservedLLMClient(
        _ResponseClient(),
        configuration=_configuration(api_cost_usd=0),
        data_classification=DataClassification.RESTRICTED,
        telemetry=telemetry,
    )

    client.chat(
        ModelProfile("local_quality"),
        LLMRequest(messages=(LLMMessage(role=MessageRole.USER, content="private"),)),
    )

    expected_labels = {
        "model.profile": "local_quality",
        "data.classification": "RESTRICTED",
        "execution.zone": "LOCAL",
        "operation.status": "success",
    }
    assert _metric_values(reader, "llm_input_tokens_total") == [(expected_labels, 11)]
    assert _metric_values(reader, "llm_output_tokens_total") == [(expected_labels, 7)]
    assert _metric_values(reader, "llm_total_tokens_total") == [(expected_labels, 18)]
    assert _metric_values(reader, "llm_tool_calls_total") == []
    assert _metric_values(reader, "llm_tool_input_tokens_total") == []
    assert _metric_values(reader, "llm_tool_output_tokens_total") == []
    assert _metric_values(reader, "llm_tool_tokens_total") == []


def test_tool_decision_usage_is_attributed_once_to_its_bound_tool() -> None:
    reader = InMemoryMetricReader()
    telemetry = Telemetry(
        TelemetryConfiguration(enabled=True),
        meter_provider=MeterProvider(metric_readers=[reader]),
    )
    client = ObservedLLMClient(
        _FixedResponseClient(
            LLMResponse(
                text=None,
                finish_reason=FinishReason.TOOL_CALLS,
                tool_calls=(
                    LLMToolCall(
                        id="call-1",
                        name="get_product_history",
                        arguments={"product_id": "P4711"},
                    ),
                ),
                usage=LLMUsage(input_tokens=11, output_tokens=7, total_tokens=18),
            )
        ),
        configuration=_configuration(api_cost_usd=0),
        data_classification=DataClassification.CONFIDENTIAL,
        telemetry=telemetry,
    )

    client.chat(ModelProfile("local_quality"), _tool_request())

    expected_labels = {
        "model.profile": "local_quality",
        "data.classification": "CONFIDENTIAL",
        "execution.zone": "LOCAL",
        "operation.status": "success",
        "mcp.tool": "get_product_history",
    }
    assert _metric_values(reader, "llm_tool_calls_total") == [(expected_labels, 1)]
    assert _metric_values(reader, "llm_tool_input_tokens_total") == [
        (expected_labels, 11)
    ]
    assert _metric_values(reader, "llm_tool_output_tokens_total") == [
        (expected_labels, 7)
    ]
    assert _metric_values(reader, "llm_tool_tokens_total") == [(expected_labels, 18)]


def test_tool_decision_without_usage_keeps_the_decision_and_skips_tokens() -> None:
    reader = InMemoryMetricReader()
    telemetry = Telemetry(
        TelemetryConfiguration(enabled=True),
        meter_provider=MeterProvider(metric_readers=[reader]),
    )
    client = ObservedLLMClient(
        _FixedResponseClient(
            LLMResponse(
                text=None,
                finish_reason=FinishReason.TOOL_CALLS,
                tool_calls=(
                    LLMToolCall(
                        id="call-1",
                        name="get_product_history",
                        arguments={"product_id": "P4711"},
                    ),
                ),
            )
        ),
        configuration=_configuration(api_cost_usd=0),
        data_classification=DataClassification.CONFIDENTIAL,
        telemetry=telemetry,
    )

    response = client.chat(ModelProfile("local_quality"), _tool_request())

    assert response.finish_reason is FinishReason.TOOL_CALLS
    assert len(_metric_values(reader, "llm_tool_calls_total")) == 1
    assert _metric_values(reader, "llm_tool_input_tokens_total") == []
    assert _metric_values(reader, "llm_tool_output_tokens_total") == []
    assert _metric_values(reader, "llm_tool_tokens_total") == []


def test_multiple_tool_calls_attribute_usage_once_to_first_admitted_tool() -> None:
    reader = InMemoryMetricReader()
    telemetry = Telemetry(
        TelemetryConfiguration(enabled=True),
        meter_provider=MeterProvider(metric_readers=[reader]),
    )
    client = ObservedLLMClient(
        _FixedResponseClient(
            LLMResponse(
                text=None,
                finish_reason=FinishReason.TOOL_CALLS,
                tool_calls=(
                    LLMToolCall(
                        id="call-1",
                        name="get_product_history",
                        arguments={"product_id": "P4711"},
                    ),
                    LLMToolCall(
                        id="call-2",
                        name="search_documentation",
                        arguments={"query": "QUALITY-09"},
                    ),
                ),
                usage=LLMUsage(input_tokens=11, output_tokens=7, total_tokens=18),
            )
        ),
        configuration=_configuration(api_cost_usd=0),
        data_classification=DataClassification.CONFIDENTIAL,
        telemetry=telemetry,
    )

    client.chat(
        ModelProfile("local_quality"),
        _tool_request("get_product_history", "search_documentation"),
    )

    labels = {
        "model.profile": "local_quality",
        "data.classification": "CONFIDENTIAL",
        "execution.zone": "LOCAL",
        "operation.status": "success",
        "mcp.tool": "get_product_history",
    }
    assert _metric_values(reader, "llm_tool_calls_total") == [(labels, 1)]
    assert _metric_values(reader, "llm_tool_tokens_total") == [(labels, 18)]


def test_unbound_model_tool_name_never_becomes_a_metric_label() -> None:
    reader = InMemoryMetricReader()
    telemetry = Telemetry(
        TelemetryConfiguration(enabled=True),
        meter_provider=MeterProvider(metric_readers=[reader]),
    )
    client = ObservedLLMClient(
        _FixedResponseClient(
            LLMResponse(
                text=None,
                finish_reason=FinishReason.TOOL_CALLS,
                tool_calls=(
                    LLMToolCall(
                        id="call-1",
                        name="invented_tool_name",
                        arguments={"product_id": "P4711"},
                    ),
                ),
                usage=LLMUsage(input_tokens=11, output_tokens=7, total_tokens=18),
            )
        ),
        configuration=_configuration(api_cost_usd=0),
        data_classification=DataClassification.CONFIDENTIAL,
        telemetry=telemetry,
    )

    client.chat(ModelProfile("local_quality"), _tool_request())

    assert _metric_values(reader, "llm_tool_calls_total") == []
    assert _metric_values(reader, "llm_tool_tokens_total") == []


def test_langfuse_v4_uses_the_required_ingestion_header(monkeypatch) -> None:
    received: dict[str, object] = {}

    class _CapturingLangfuse:
        def __init__(self, **kwargs: object) -> None:
            received.update(kwargs)

        def flush(self) -> None:
            return None

        def shutdown(self) -> None:
            return None

    monkeypatch.setitem(
        sys.modules, "langfuse", SimpleNamespace(Langfuse=_CapturingLangfuse)
    )
    telemetry = configure_telemetry(
        TelemetryConfiguration(
            enabled=True,
            langfuse_enabled=True,
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
    )

    try:
        assert telemetry.langfuse_enabled
        assert received["additional_headers"] == {"x-langfuse-ingestion-version": "4"}
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


def _metric_values(
    reader: InMemoryMetricReader, metric_name: str
) -> list[tuple[dict[str, object], int | float]]:
    values: list[tuple[dict[str, object], int | float]] = []
    for resource_metric in reader.get_metrics_data().resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name != metric_name:
                    continue
                for point in metric.data.data_points:
                    values.append((dict(point.attributes), point.value))
    return values


def _tool_request(*tool_names: str) -> LLMRequest:
    names = tool_names or ("get_product_history",)
    return LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="private"),),
        tools=tuple(
            LLMToolDefinition(
                name=name,
                description="Bounded test tool.",
                parameters={"type": "object", "additionalProperties": False},
            )
            for name in names
        ),
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
                    "max_data_classification": "RESTRICTED",
                    "capabilities": ["TEXT"],
                    "quality_class": "HIGH",
                    "cost_class": "LOW",
                    "api_cost_usd": api_cost_usd,
                }
            }
        }
    )
