from argparse import Namespace
from pathlib import Path

from mcp.client.stdio import StdioServerParameters

from scripts.smoke_test_langgraph import PROJECT_ROOT, _mcp_servers_from_args


def test_local_stdio_smoke_passes_canonical_knowledge_root_to_bm25_subprocess() -> None:
    servers = _mcp_servers_from_args(
        Namespace(mcp_transport="stdio", mcp_url="", knowledge_mcp_url="")
    )
    knowledge = next(server for server in servers if server.server_id == "knowledge")

    assert isinstance(knowledge.transport, StdioServerParameters)
    assert knowledge.transport.env == {
        "KNOWLEDGE_ROOT": str(PROJECT_ROOT / "knowledge_base")
    }
    assert "InMemoryBm25KnowledgeRetriever" in knowledge.transport.args[1]
    assert "/app/data/knowledge" not in knowledge.transport.args[1]
    assert Path(knowledge.transport.env["KNOWLEDGE_ROOT"]).is_dir()
