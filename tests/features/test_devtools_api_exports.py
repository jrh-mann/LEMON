from pathlib import Path


def test_frontend_api_barrel_exports_tools_module():
    content = Path("src/frontend/src/api/index.ts").read_text(encoding="utf-8")
    assert "export * from './tools'" in content
