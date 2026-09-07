"""Static local-demo network guarantees from the resolved Compose configuration."""

import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _compose_configuration() -> dict[str, object]:
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _published_ports(service: dict[str, object]) -> tuple[dict[str, object], ...]:
    ports = service.get("ports", [])
    assert isinstance(ports, list)
    return tuple(port for port in ports if isinstance(port, dict))


def test_host_published_demo_ports_are_loopback_only() -> None:
    configuration = _compose_configuration()
    services = configuration["services"]
    assert isinstance(services, dict)

    for service_name, service in services.items():
        assert isinstance(service_name, str)
        assert isinstance(service, dict)
        for port in _published_ports(service):
            assert port.get("host_ip") == "127.0.0.1", service_name


def test_internal_services_have_no_host_published_ports() -> None:
    configuration = _compose_configuration()
    services = configuration["services"]
    assert isinstance(services, dict)
    for service_name in (
        "otel-collector",
        "langfuse-clickhouse",
        "langfuse-postgres",
        "langfuse-redis",
        "langfuse-worker",
    ):
        service = services[service_name]
        assert isinstance(service, dict)
        assert _published_ports(service) == (), service_name


def test_grafana_anonymous_demo_access_is_viewer_only() -> None:
    configuration = _compose_configuration()
    services = configuration["services"]
    assert isinstance(services, dict)
    grafana = services["grafana"]
    assert isinstance(grafana, dict)
    environment = grafana["environment"]
    assert isinstance(environment, dict)

    assert environment["GF_AUTH_ANONYMOUS_ENABLED"] == "true"
    assert environment["GF_AUTH_ANONYMOUS_ORG_ROLE"] == "Viewer"
