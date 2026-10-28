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
    "conclave_add_participant", "conclave_send_message",
    "conclave_get_messages", "conclave_invoke", "conclave_orchestrate", "conclave_list_agents",
    "conclave_get_usage", "conclave_export_conversation", "conclave_list_files",
    "conclave_read_file", "conclave_upload_file",
    "conclave_consult", "conclave_get_consultation",
}                                    # 16 Tools: Loeschen nur fuer den Menschen (E2)


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


def _text(result) -> str:
    return " ".join(getattr(block, "text", "") for block in result.content)


@pytest.fixture(autouse=True)
def fresh_role_check(monkeypatch):
    monkeypatch.setattr(server, "_role_checked", False)


@pytest.fixture
def conclave_api(tmp_path, monkeypatch):
    """Echter Conclave-Server (Tokens aus den Token-Dateien) auf einem freien Port.

    Liefert (url, Mensch-Token, Agent-Token)."""
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
    yield url, config.api_key, config.agent_api_key
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
    url, human, agent = conclave_api
    assert server.read_token() == agent  # aus agent.token, nie aus api.token
    assert agent != human

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
    monkeypatch.setenv("CONCLAVE_AGENT_KEY", "falsch")

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


# ── Z5: Agent-Token, Warnung bei Mensch-Token ─────────────────────────────

def _call(name, args=None):
    async def call():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, args or {})
    return _run(call())


def test_never_reads_the_human_token_file(tmp_path, monkeypatch):
    monkeypatch.delenv("CONCLAVE_API_KEY", raising=False)     # CI setzt die Variable global
    (tmp_path / "api.token").write_text("cvh_mensch\n", encoding="utf-8")   # CONCLAVE_API_TOKEN_FILE (conftest)
    assert server.read_token() == ""                                         # kein agent.token, keine Variablen
    (tmp_path / "agent.token").write_text("cva_agent\n", encoding="utf-8")
    assert server.read_token() == "cva_agent"
    monkeypatch.setenv("CONCLAVE_API_KEY", "cvh_alt")
    assert server.read_token() == "cva_agent"                                # Agent-Token hat Vorrang
    monkeypatch.setenv("CONCLAVE_AGENT_KEY", "cva_env")
    assert server.read_token() == "cva_env"


def test_all_remaining_tools_work_with_agent_token(conclave_api, capsys):
    """Abnahme Z5: jedes verbliebene Tool gegen einen echten Server, ohne 401/403 und ohne Warnung."""
    created = _call("conclave_create_conversation", {"topic": "Z5"})
    assert not created.is_error, _text(created)
    conv = json.loads(_text(created))["conversation_id"]
    calls = [
        ("conclave_list_conversations", {}), ("conclave_get_conversation", {"conversation_id": conv}),
        ("conclave_add_participant", {"conversation_id": conv, "agent_id": "p1"}),
        ("conclave_list_agents", {}), ("conclave_send_message", {"conversation_id": conv, "content": "Hallo"}),
        ("conclave_get_messages", {"conversation_id": conv}),
        ("conclave_invoke", {"conversation_id": conv, "participant_id": "p1"}),
        ("conclave_orchestrate", {"conversation_id": conv, "sequence": ["p1"]}),
        ("conclave_export_conversation", {"conversation_id": conv}), ("conclave_get_usage", {}),
        ("conclave_upload_file", {"filepath": "z5/notiz.md", "content": "x"}), ("conclave_list_files", {}),
        ("conclave_read_file", {"filepath": "z5/notiz.md"}),
        ("conclave_consult", {"task": "conclave#1", "question": "?"}),
        ("conclave_get_consultation", {"consultation_id": "gibtsnicht"}),
    ]
    assert {name for name, _ in calls} | {"conclave_create_conversation"} == EXPECTED_TOOLS
    for name, args in calls:
        result = _call(name, args)
        text = _text(result)
        # fachliche Fehler (kein Provider, keine Consultations eingerichtet) sind erlaubt, Zugangsfehler nicht
        assert "API 401" not in text and "API 403" not in text, (name, text)
    first = _call("conclave_get_messages", {"conversation_id": conv}).content[0]   # ein Block je Nachricht
    assert json.loads(first.text)["origin"] == "agent"
    assert "WARNUNG" not in capsys.readouterr().err


@pytest.mark.parametrize("variable", ["CONCLAVE_AGENT_KEY", "CONCLAVE_API_KEY"])
def test_human_token_triggers_warning(conclave_api, monkeypatch, tmp_path, capsys, variable):
    _url, human, _agent = conclave_api
    if variable == "CONCLAVE_API_KEY":
        (tmp_path / "agent.token").unlink()          # alte Einrichtung: nur CONCLAVE_API_KEY
    monkeypatch.setenv(variable, human)
    assert not _call("conclave_list_conversations").is_error
    assert not _call("conclave_list_conversations").is_error
    err = capsys.readouterr().err
    assert err.count("WARNUNG: conclave-mcp nutzt das Mensch-Token") == 1    # einmal pro Prozess
    assert human not in err


def test_old_server_without_roles_is_reported(monkeypatch, capsys):
    import httpx

    def fake_get(url, **kw):
        return httpx.Response(404, json={"error": "nicht gefunden"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(server.httpx, "get", fake_get)
    monkeypatch.setattr(server, "API_URL", "http://127.0.0.1:9")
    _call("conclave_list_agents")
    assert "aelter als v0.5.0" in capsys.readouterr().err


def test_delete_tools_are_gone():
    assert not hasattr(server, "conclave_delete_conversation")
    assert not hasattr(server, "conclave_delete_file")


def test_role_check_is_repeated_after_401(conclave_api, monkeypatch, tmp_path, capsys):
    """Falsches Token zuerst: der Check gilt nicht als erledigt, die Warnung kommt spaeter noch."""
    _url, human, _agent = conclave_api
    monkeypatch.setenv("CONCLAVE_AGENT_KEY", "falsch")
    assert _call("conclave_list_conversations").is_error
    monkeypatch.setenv("CONCLAVE_AGENT_KEY", human)
    assert not _call("conclave_list_conversations").is_error
    assert "WARNUNG: conclave-mcp nutzt das Mensch-Token" in capsys.readouterr().err
