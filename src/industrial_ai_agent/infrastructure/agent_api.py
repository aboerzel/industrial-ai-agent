"""FastAPI development entry point for the local Industrial AI Agent API."""

import asyncio
import os
import sys
from pathlib import Path

import uvicorn

from industrial_ai_agent.agent.model_egress import ModelExecutionAuthorizer
from industrial_ai_agent.agent.model_selection import (
    CURRENT_CONSUMER_REQUIREMENTS,
    CURRENT_MODEL_CONSUMERS,
    ModelResolutionService,
)
from industrial_ai_agent.application.model_configuration import (
    ModelConfigurationService,
)
from industrial_ai_agent.domain.security import DEMO_RUNTIME_SECURITY_CONTEXT
from industrial_ai_agent.infrastructure.api.app import create_app
from industrial_ai_agent.infrastructure.api.observed_run_store import (
    ObservedAgentRunStore,
)
from industrial_ai_agent.infrastructure.api.postgres_run_store import (
    PostgreSqlAgentRunStore,
)
from industrial_ai_agent.infrastructure.internal_diagnostic_scope import (
    PostgreSqlInternalDiagnosticScopeValidator,
)
from industrial_ai_agent.infrastructure.llm.configuration import load_model_catalog
from industrial_ai_agent.infrastructure.local_environment import load_local_environment
from industrial_ai_agent.infrastructure.observed_run_service import observed_run_service
from industrial_ai_agent.infrastructure.persistence.model_assignments import (
    PostgreSqlModelAssignmentRepository,
)
from industrial_ai_agent.infrastructure.persistence.postgres import (
    PostgreSqlDocumentContentRepository,
    PostgreSqlSessionFactory,
)
from industrial_ai_agent.infrastructure.telemetry import (
    TelemetryConfiguration,
    configure_telemetry,
)
from industrial_ai_agent.infrastructure.troubleshooting_run_composition import (
    DEFAULT_MODEL_CATALOG_PATH,
    create_default_troubleshooting_run_service,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOCAL_FRONTEND_ORIGINS = (
    "http://localhost:8080",
    "http://127.0.0.1:8080",
)
DEFAULT_DOCUMENT_ROOT = Path("/app/data/document-content")


def create_default_app():
    """Compose the local/demo FastAPI application without embedding deployment details."""
    load_local_environment(PROJECT_ROOT / ".env")
    configured_frontend_origin = os.getenv("AGENT_FRONTEND_ORIGIN")
    frontend_origins = (
        (configured_frontend_origin,)
        if configured_frontend_origin
        else DEFAULT_LOCAL_FRONTEND_ORIGINS
    )
    database_url = os.getenv("AGENT_RUNTIME_DATABASE_URL") or os.getenv(
        "FACTORY_DATABASE_URL"
    )
    if not database_url:
        raise RuntimeError(
            "AGENT_RUNTIME_DATABASE_URL or FACTORY_DATABASE_URL is required"
        )
    telemetry = configure_telemetry(
        TelemetryConfiguration(
            enabled=_environment_bool("OTEL_ENABLED", False),
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "127.0.0.1:4317"),
            service_name=os.getenv("OTEL_SERVICE_NAME", "industrial-ai-agent"),
            langfuse_enabled=_environment_bool("LANGFUSE_ENABLED", False),
            langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            langfuse_base_url=os.getenv("LANGFUSE_BASE_URL", "http://127.0.0.1:3001"),
            langfuse_environment=os.getenv("LANGFUSE_ENVIRONMENT", "local"),
            langfuse_release=os.getenv("LANGFUSE_RELEASE"),
        )
    )
    run_service = create_default_troubleshooting_run_service(
        runtime_database_url=database_url,
        telemetry=telemetry,
        internal_diagnostic_scope_validator=PostgreSqlInternalDiagnosticScopeValidator(
            PostgreSqlSessionFactory(database_url)
        ),
    )
    model_catalog = load_model_catalog(DEFAULT_MODEL_CATALOG_PATH)
    assignment_repository = PostgreSqlModelAssignmentRepository(
        PostgreSqlSessionFactory(database_url), DEMO_RUNTIME_SECURITY_CONTEXT
    )
    authorizer = ModelExecutionAuthorizer()
    model_resolver = ModelResolutionService(
        catalog=model_catalog,
        assignments=assignment_repository,
        authorizer=authorizer,
        consumer_requirements=CURRENT_CONSUMER_REQUIREMENTS,
    )
    model_configuration_service = ModelConfigurationService(
        catalog=model_catalog,
        assignments=assignment_repository,
        supported_consumers=model_resolver.supported_consumers,
        consumer_definitions=CURRENT_MODEL_CONSUMERS,
        authorizer=authorizer,
        model_is_statically_available=lambda model: model_catalog.is_model_available(
            model.model_id.value, environment=os.environ
        ),
    )
    model_configuration_service.ensure_default_assignments()
    return create_app(
        observed_run_service(run_service, telemetry),
        run_store=ObservedAgentRunStore(
            PostgreSqlAgentRunStore(
                PostgreSqlSessionFactory(database_url), DEMO_RUNTIME_SECURITY_CONTEXT
            ),
            telemetry,
        ),
        allowed_origins=frontend_origins,
        telemetry=telemetry,
        document_content_reader=PostgreSqlDocumentContentRepository(
            PostgreSqlSessionFactory(database_url),
            Path(os.getenv("DOCUMENT_ROOT", str(DEFAULT_DOCUMENT_ROOT))),
        ),
        model_configuration_service=model_configuration_service,
    )


def _environment_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


app = create_default_app()


def main() -> None:
    """Run the local FastAPI development server."""
    config = uvicorn.Config(
        app,
        host=os.getenv("AGENT_API_HOST", "127.0.0.1"),
        port=int(os.getenv("AGENT_API_PORT", "8000")),
    )
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(server.serve())
        return
    server.run()


if __name__ == "__main__":
    main()
