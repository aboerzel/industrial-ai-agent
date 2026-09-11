from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_hardware_mcp_container_excludes_runtime_demo_data() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile.hardware-mcp").read_text(encoding="utf-8")

    assert "COPY demo_factory" not in dockerfile
    assert "COPY knowledge_base" not in dockerfile
    assert "COPY database" not in dockerfile
    assert "industrial_ai_agent.infrastructure.hardware_mcp_server" in dockerfile


def test_compose_wires_hardware_mcp_only_through_its_bounded_endpoint() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "hardware-mcp:" in compose
    assert "dockerfile: Dockerfile.hardware-mcp" in compose
    assert "HARDWARE_MCP_URL: http://hardware-mcp:8006/mcp" in compose
    assert "127.0.0.1:8006:8006" in compose
