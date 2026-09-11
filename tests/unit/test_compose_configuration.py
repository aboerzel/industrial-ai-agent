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


def test_persistent_demo_services_restart_unless_stopped() -> None:
    configuration = _compose_configuration()
    services = configuration["services"]
    assert isinstance(services, dict)

    for service_name, service in services.items():
        assert isinstance(service_name, str)
        assert isinstance(service, dict)
        assert service.get("restart") == "unless-stopped", service_name


def test_agent_dependencies_use_protocol_aware_mcp_readiness() -> None:
    configuration = _compose_configuration()
    services = configuration["services"]
    assert isinstance(services, dict)

    for service_name, expected_tool in (
        ("factory-mcp", "get_machine_status"),
        ("knowledge-mcp", "search_documentation"),
        ("hardware-mcp", "get_position_reference_status"),
    ):
        service = services[service_name]
        assert isinstance(service, dict)
        healthcheck = service["healthcheck"]
        assert isinstance(healthcheck, dict)
        test = healthcheck["test"]
        assert isinstance(test, list)
        assert "industrial_ai_agent.infrastructure.mcp_readiness" in test
        assert expected_tool in test

    agent_api = services["agent-api"]
    assert isinstance(agent_api, dict)
    dependencies = agent_api["depends_on"]
    assert isinstance(dependencies, dict)
    for service_name in ("factory-mcp", "knowledge-mcp", "hardware-mcp"):
        dependency = dependencies[service_name]
        assert isinstance(dependency, dict)
        assert dependency["condition"] == "service_healthy"


def test_frontend_is_a_loopback_only_static_service() -> None:
    configuration = _compose_configuration()
    services = configuration["services"]
    assert isinstance(services, dict)
    frontend = services["frontend"]
    assert isinstance(frontend, dict)

    assert frontend["image"] == "nginx:1.29-alpine"
    assert frontend["restart"] == "unless-stopped"
    assert _published_ports(frontend) == (
        {
            "mode": "ingress",
            "target": 80,
            "published": "8080",
            "protocol": "tcp",
            "host_ip": "127.0.0.1",
        },
    )
    assert frontend["volumes"] == [
        {
            "type": "bind",
            "source": str(PROJECT_ROOT / "frontend"),
            "target": "/usr/share/nginx/html",
            "read_only": True,
            "bind": {},
        },
        {
            "type": "bind",
            "source": str(PROJECT_ROOT / "frontend" / "nginx.conf"),
            "target": "/etc/nginx/conf.d/default.conf",
            "read_only": True,
            "bind": {},
        },
    ]


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
