"""MCP-Server (conclave-mcp) mit dem MCP Python SDK 2.x.

Bis v0.2.0 importierte kein Test den MCP-Server; mit mcp 2.x startete er nicht
(FastMCP wurde in MCPServer umbenannt), ohne dass es auffiel. Diese Tests
sprechen den Server ueber den echten MCP-Client an - im Prozess, gegen einen
laufenden Conclave-Server und ueber stdio wie Claude Code.
"""

import asyncio
import json
import sys
import threading
from pathlib import Path

import pytest

mcp_pkg = pytest.importorskip("mcp")
pytest.importorskip("mcp.server.mcpserver", reason="benoetigt mcp 2.x")

from mcp import Client, StdioServerParameters  # noqa: E402

import conclave.mcp_server as server  # noqa: E402

EXPECTED_TOOLS = {
    "conclave_create_conversation", "conclave_list_conversations", "conclave_get_conversation",
    "conclave_delete_conversation", "conclave_add_participant", "conclave_send_message",
    "conclave_get_messages", "conclave_invoke", "conclave_orchestrate", "conclave_list_agents",
    "conclave_get_usage", "conclave_export_conversation", "conclave_list_files",
    "conclave_read_file", "conclave_upload_file", "conclave_delete_file",
    "conclave_consult", "conclave_get_consultation",
}


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


def _text(result) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content)


@pytest.fixture
def conclave_api(tmp_path, monkeypatch):
    """Echter Conclave-Server (Token aus Token-Datei) auf einem freien Port."""
    from werkzeug.serving import make_server

    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig

    monkeypatch.delenv("CONCLAVE_API_KEY", raising=False)
    app, config = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=""))
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{srv.server_port}"
    monkeypatch.setattr(server, "API_URL", url)
    yield url, config.api_key
    srv.shutdown()
    thread.join(timeout=5)


def test_server_metadata_and_tools():
    async def check():
        async with Client(server.mcp) as client:
            tools = await client.list_tools()
            return client.server_info, {t.name for t in tools.tools}

    info, names = _run(check())
    assert info.name == "Conclave"
    assert info.version and info.version != "0.0.0"
    assert names == EXPECTED_TOOLS


def test_tools_work_against_running_server_with_token_file(conclave_api):
    url, token = conclave_api
    assert server.read_token() == token  # aus CONCLAVE_API_TOKEN_FILE, ohne CONCLAVE_API_KEY

    async def flow():
        async with Client(server.mcp) as client:
            created = await client.call_tool("conclave_create_conversation", {"topic": "MCP 2.x"})
            listed = await client.call_tool("conclave_list_conversations", {})
            return created, listed

    created, listed = _run(flow())
    assert not created.is_error, _text(created)
    payload = json.loads(_text(created))  # dict-Rueckgaben kommen in mcp 2.x als JSON-Text
    assert payload["topic"] == "MCP 2.x"
    conv_id = payload["conversation_id"]
    assert not listed.is_error
    assert conv_id in _text(listed)


def test_wrong_token_is_reported_to_the_model(conclave_api, monkeypatch):
    monkeypatch.setenv("CONCLAVE_API_KEY", "falsch")

    async def call():
        async with Client(server.mcp) as client:
            return await client.call_tool("conclave_list_conversations", {})

    result = _run(call())
    assert result.is_error
    assert "Conclave-API 401" in _text(result)
    assert "Token pruefen" in _text(result)


def test_unreachable_server_is_reported_to_the_model(monkeypatch):
    monkeypatch.setattr(server, "API_URL", "http://127.0.0.1:9")  # Port 9 (discard): keine Antwort

    async def call():
        async with Client(server.mcp) as client:
            return await client.call_tool("conclave_list_agents", {})

    result = _run(call())
    assert result.is_error
    assert "nicht erreichbar" in _text(result)


def test_starts_over_stdio_like_claude_code():
    """Wie Claude Code: Prozess starten, Handshake, Tools abfragen."""
    src = str(Path(server.__file__).resolve().parents[1])
    params = StdioServerParameters(command=sys.executable, args=["-m", "conclave.mcp_server"],
                                   env={"PYTHONPATH": src, "CONCLAVE_API_URL": "http://127.0.0.1:9"})

    async def check():
        async with Client(params) as client:
            tools = await client.list_tools()
            return {t.name for t in tools.tools}

    assert _run(check()) == EXPECTED_TOOLS


def test_dependency_pin_requires_mcp_2():
    import tomllib
    root = Path(__file__).resolve().parents[2]
    extras = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    assert "mcp>=2,<3" in extras["mcp"]
    assert "mcp>=2,<3" in extras["dev-all"]
