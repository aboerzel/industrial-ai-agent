from pathlib import Path

from industrial_ai_agent.agent.llm import LLMReasoningEffort, ModelProfile
from industrial_ai_agent.agent.run_classification_policy import (
    AgentRunClassificationPolicy,
    AgentRunProfile,
)
from industrial_ai_agent.infrastructure.llm.configuration import load_llm_configuration
from industrial_ai_agent.infrastructure.troubleshooting_run_composition import (
    _mcp_server_configurations,
    _restricted_ollama_reasoning_effort,
    _system_message_for,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_public_run_connects_only_to_its_authorized_read_only_servers(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MCP_INDUSTRIAL_AGENT_PUBLIC_TOKEN", "test-public-token")
    policy = AgentRunClassificationPolicy().resolve(AgentRunProfile.PUBLIC_INFORMATION)

    servers = _mcp_server_configurations(
        mcp_transport="http",
        factory_mcp_url="http://factory.example/mcp",
        knowledge_mcp_url="http://knowledge.example/mcp",
        hardware_mcp_url="http://hardware.example/mcp",
        factory_database_url=None,
        run_policy=policy,
    )

    assert [server.server_id for server in servers] == ["factory", "knowledge"]
    assert servers[0].allowed_tool_names == frozenset(
        {
            "list_stations",
            "get_station_overview",
            "list_products",
            "get_product_overview",
            "get_product_history",
            # A ticket lookup is bounded and read-only. The public MCP identity and
            # PostgreSQL RLS still return the same neutral result for hidden tickets.
            "get_maintenance_ticket",
        }
    )
    assert servers[1].allowed_tool_names == frozenset({"search_documentation"})


def test_restricted_ollama_agent_disables_thinking_without_changing_profile() -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    policy = AgentRunClassificationPolicy().resolve(
        AgentRunProfile.RESTRICTED_TROUBLESHOOTING
    )

    effort = _restricted_ollama_reasoning_effort(
        configuration=configuration,
        profile=ModelProfile("local_quality"),
        run_policy=policy,
    )

    assert effort is LLMReasoningEffort.NONE


def test_confidential_run_does_not_override_its_profile_reasoning_policy() -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )
    policy = AgentRunClassificationPolicy().resolve(
        AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
    )

    effort = _restricted_ollama_reasoning_effort(
        configuration=configuration,
        profile=ModelProfile("local_quality"),
        run_policy=policy,
    )

    assert effort is None


def test_restricted_information_uses_the_bounded_operations_system_message() -> None:
    policy = AgentRunClassificationPolicy().resolve(
        AgentRunProfile.RESTRICTED_INFORMATION
    )

    message = _system_message_for(policy)

    assert "read-only tool" in message
    assert "maintenance ticket" not in message


def test_restricted_information_does_not_open_knowledge_mcp_for_station_status(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "MCP_INDUSTRIAL_AGENT_RESTRICTED_TOKEN", "test-restricted-agent-token"
    )
    policy = AgentRunClassificationPolicy().resolve(
        AgentRunProfile.RESTRICTED_INFORMATION
    )

    servers = _mcp_server_configurations(
        mcp_transport="http",
        factory_mcp_url="http://factory.example/mcp",
        knowledge_mcp_url="http://knowledge.example/mcp",
        hardware_mcp_url="http://hardware.example/mcp",
        factory_database_url=None,
        run_policy=policy,
    )

    assert [server.server_id for server in servers] == ["factory"]
    assert servers[0].allowed_tool_names == frozenset(
        {"list_stations", "get_station_overview", "get_machine_status"}
    )


def test_confidential_run_registers_only_bounded_hardware_recovery_tools(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MCP_INDUSTRIAL_AGENT_TOKEN", "test-industrial-agent-token")
    policy = AgentRunClassificationPolicy().resolve(
        AgentRunProfile.CONFIDENTIAL_TROUBLESHOOTING
    )

    servers = _mcp_server_configurations(
        mcp_transport="http",
        factory_mcp_url="http://factory.example/mcp",
        knowledge_mcp_url="http://knowledge.example/mcp",
        hardware_mcp_url="http://hardware.example/mcp",
        factory_database_url=None,
        run_policy=policy,
    )

    hardware = next(server for server in servers if server.server_id == "hardware")

    assert [server.server_id for server in servers] == [
        "factory",
        "knowledge",
        "hardware",
    ]
    assert hardware.allowed_tool_names == frozenset(
        {
            "get_position_reference_status",
            "prepare_reference_calibration",
            "execute_reference_calibration",
        }
    )


def test_confidential_recovery_registers_only_hardware_recovery_tools(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MCP_INDUSTRIAL_AGENT_TOKEN", "test-industrial-agent-token")
    policy = AgentRunClassificationPolicy().resolve(
        AgentRunProfile.CONFIDENTIAL_RECOVERY
    )

    servers = _mcp_server_configurations(
        mcp_transport="http",
        factory_mcp_url="http://factory.example/mcp",
        knowledge_mcp_url="http://knowledge.example/mcp",
        hardware_mcp_url="http://hardware.example/mcp",
        factory_database_url=None,
        run_policy=policy,
    )

    assert [server.server_id for server in servers] == ["hardware"]
    assert servers[0].allowed_tool_names == frozenset(
        {
            "get_position_reference_status",
            "prepare_reference_calibration",
            "execute_reference_calibration",
        }
    )


def test_lower_classification_profiles_do_not_authorize_hardware_recovery_tools() -> (
    None
):
    policy = AgentRunClassificationPolicy()
    hardware_tools = {
        "get_position_reference_status",
        "prepare_reference_calibration",
        "execute_reference_calibration",
    }

    for profile in (
        AgentRunProfile.PUBLIC_INFORMATION,
        AgentRunProfile.INTERNAL_DIAGNOSTIC,
        AgentRunProfile.RESTRICTED_INFORMATION,
    ):
        assert not hardware_tools & policy.resolve(profile).allowed_tool_names


def test_restricted_information_uses_a_bounded_local_generation_budget() -> None:
    configuration = load_llm_configuration(
        PROJECT_ROOT / "config" / "model_profiles.toml"
    )

    assert configuration.get_profile("local_fast").max_output_tokens == 192
