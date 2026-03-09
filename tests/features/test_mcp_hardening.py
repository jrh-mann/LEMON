from pathlib import Path


def test_update_subworkflow_mcp_injects_required_context():
    content = Path("src/backend/mcp_bridge/server.py").read_text(encoding="utf-8")
    assert 'state.setdefault("user_id", user_id or "mcp_user")' in content
    assert 'state.setdefault("repo_root", _repo_root())' in content


def test_mcp_client_caches_tool_schemas():
    content = Path("src/backend/mcp_bridge/client.py").read_text(encoding="utf-8")
    assert '_MCP_TOOLS_CACHE' in content
    assert 'Using cached MCP tools' in content
    assert 'tools_cached = url in _MCP_TOOLS_CACHE' in content
