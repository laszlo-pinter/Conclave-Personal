"""P3 (conclave#58): Reviewer-Zugang ueber die API und den MCP-Server.

Drittes Token (``cvr_``, ``reviewer.token`` / ``CONCLAVE_REVIEWER_KEY``) mit eigener, enger
Allowlist: lesen, kommentieren, Review-Status setzen. Agent- und Mensch-Token setzen keinen
Review-Status.
"""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

from conclave.cli.config import ConclaveConfig  # noqa: E402

HUMAN = "cvh_mensch"
AGENT = "cva_agent"
REVIEWER = "cvr_reviewer"
URL = "/board/projects/api/tasks"


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(tmp_path):
    from conclave.api.server import _build_app
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN, agent_api_key=AGENT,
                                       reviewer_api_key=REVIEWER))
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.post("/board/projects", json={"slug": "api", "name": "API"}, headers=_bearer(HUMAN)).status_code == 201
    assert c.post("/board/tasks", json={"project": "api", "title": "T"}, headers=_bearer(HUMAN)).status_code == 201
    assert c.patch(f"{URL}/1", json={"status": "review"}, headers=_bearer(HUMAN)).status_code == 200
    return c


def _review(client, token, **body):
    return client.post(f"{URL}/1/review", json=body, headers=_bearer(token))


def test_whoami_names_the_reviewer_role(client):
    assert client.get("/auth/whoami", headers=_bearer(REVIEWER)).get_json() == {"role": "reviewer"}


@pytest.mark.parametrize("token", [AGENT, HUMAN])
def test_agent_and_human_cannot_set_the_review_state(client, token):
    resp = _review(client, token, state="passed", comment="gruen")
    assert resp.status_code == 403
    assert client.get(f"{URL}/1", headers=_bearer(HUMAN)).get_json()["review"]["state"] == "none"


def test_reviewer_sets_rework_and_the_agent_gets_it_next_with_the_review(client):
    resp = _review(client, REVIEWER, state="rework", comment="Urteil: gelb\nB1 Test fehlt", blocking=1,
                   suggestions=0, checked="sicherheit @ a..b")
    assert resp.status_code == 200, resp.get_json()
    assert (resp.get_json()["status"], resp.get_json()["review"]["state"]) == ("todo", "rework")
    taken = client.post("/board/next", json={}, headers=_bearer(AGENT)).get_json()
    assert taken["task"]["ref"] == "api#1"
    assert taken["last_review"]["body"] == "Urteil: gelb\nB1 Test fehlt"
    assert taken["last_review"]["origin"] == "reviewer"
    detail = client.get(f"{URL}/1", headers=_bearer(AGENT)).get_json()
    assert detail["last_review"]["body"].startswith("Urteil: gelb")


@pytest.mark.parametrize("method, path, body", [
    ("PATCH", f"{URL}/1", {"status": "done"}),
    ("PATCH", f"{URL}/1", {"rank": 1}),
    ("POST", "/board/tasks", {"project": "api", "title": "Vom Reviewer"}),
    ("POST", "/board/next", {}),
    ("POST", "/workspace/x.md", {"content": "x"}),
    ("GET", "/workspace", None),
    ("POST", "/conversations", {"topic": "x"}),
    ("POST", "/consultations", {"task": "api#1", "question": "?"}),
    ("GET", "/settings", None),
    ("DELETE", f"{URL}/1", None),
])
def test_reviewer_is_limited_to_reading_commenting_and_reviewing(client, method, path, body):
    resp = client.open(path, method=method, json=body, headers=_bearer(REVIEWER))
    assert resp.status_code == 403, (method, path, resp.status_code)
    task = client.get(f"{URL}/1", headers=_bearer(HUMAN)).get_json()
    assert task["status"] == "review"


def test_reviewer_reads_and_comments(client):
    assert client.get("/board/tasks", headers=_bearer(REVIEWER)).status_code == 200
    assert client.get(f"{URL}/1/history", headers=_bearer(REVIEWER)).status_code == 200
    resp = client.post(f"{URL}/1/comments", json={"body": "Lauf gestartet"}, headers=_bearer(REVIEWER))
    assert resp.status_code == 201 and resp.get_json()["origin"] == "reviewer"


def test_review_body_is_checked(client):
    assert _review(client, REVIEWER, state="passed", comment="x", extra=1).status_code == 400
    assert _review(client, REVIEWER, state="passed", comment="x", blocking="1").status_code == 400
    assert _review(client, REVIEWER, state="passed", comment="x", checked=5).status_code == 400


# ── Review neu anfordern (conclave#145) ─────────────────────────────────────

@pytest.mark.parametrize("prefix", ["/board", "/board/v1"])
def test_human_requests_a_review_again(client, prefix):
    resp = client.post(f"{prefix}/projects/api/tasks/1/review/request", json={}, headers=_bearer(HUMAN))
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert (data["status"], data["review"]["state"]) == ("review", "requested")
    assert data["review"]["at"] and "control" in data


@pytest.mark.parametrize("token, expected", [(HUMAN, True), (AGENT, False), (REVIEWER, False)])
def test_task_detail_says_whether_this_access_may_approve(client, token, expected):
    """Die Oberflaeche zeigt "Review neu starten" nur mit dem Freigabe-Recht (Review V1)."""
    assert client.get(f"{URL}/1", headers=_bearer(token)).get_json()["can_approve"] is expected


@pytest.mark.parametrize("token", [AGENT, REVIEWER])
def test_agent_and_reviewer_cannot_request_a_review(client, token):
    resp = client.post(f"{URL}/1/review/request", json={}, headers=_bearer(token))
    assert resp.status_code == 403
    assert client.get(f"{URL}/1", headers=_bearer(HUMAN)).get_json()["review"]["state"] == "none"


def test_request_body_must_be_empty_and_a_running_review_is_refused(client):
    assert client.post(f"{URL}/1/review/request", json={"x": 1}, headers=_bearer(HUMAN)).status_code == 400
    assert _review(client, REVIEWER, state="running").status_code == 200
    resp = client.post(f"{URL}/1/review/request", json={}, headers=_bearer(HUMAN))
    assert (resp.status_code, resp.get_json()["type"]) == (409, "ReviewRunning")


# ── Token und Anmeldung ─────────────────────────────────────────────────────

def test_reviewer_token_is_created_like_the_agent_token(tmp_path):
    from conclave.api.server import _build_app
    _, config = _build_app(ConclaveConfig(db_path=tmp_path / "d.db", api_key=HUMAN, agent_api_key=AGENT))
    token = (tmp_path / "reviewer.token").read_text(encoding="utf-8").strip()
    assert token.startswith("cvr_") and config.reviewer_api_key == token


@pytest.mark.parametrize("same_as", ["human", "agent"])
def test_reviewer_token_equal_to_another_token_is_disabled(same_as):
    from conclave.infrastructure.auth import StaticKeyAuthService
    other = HUMAN if same_as == "human" else AGENT
    auth = StaticKeyAuthService(HUMAN, AGENT, reviewer_key=other)
    assert auth.authenticate(other).role == same_as


def test_reviewer_token_file_is_protected_in_the_workspace(tmp_path, monkeypatch):
    from conclave.application import workspace_security as ws
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "r.token").write_text("cvr_x", encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_REVIEWER_TOKEN_FILE", str(workspace / "r.token"))
    assert ws.resolve_workspace_path("r.token", root=workspace) is None


# ── MCP: eigener Reviewer-Server ───────────────────────────────────────────

mcp_pkg = pytest.importorskip("mcp")


def _mcp_tools(srv):
    import asyncio
    from mcp import Client

    async def names():
        async with Client(srv) as client:
            return {t.name for t in (await client.list_tools()).tools}
    return asyncio.run(asyncio.wait_for(names(), 60))


def test_agent_mcp_has_no_review_tool_and_reviewer_mcp_only_three():
    import conclave.mcp_server as server
    assert "conclave_board_review" not in _mcp_tools(server.mcp)
    assert _mcp_tools(server.reviewer_mcp) == {"conclave_board_get", "conclave_board_list", "conclave_board_review"}


def test_reviewer_mcp_uses_only_the_reviewer_token(tmp_path, monkeypatch):
    import conclave.mcp_server as server
    (tmp_path / "agent.token").write_text("cva_falsch", encoding="utf-8")
    (tmp_path / "reviewer.token").write_text("cvr_richtig", encoding="utf-8")
    monkeypatch.setattr(server, "MODE", "reviewer")
    assert server.read_token() == "cvr_richtig"
    monkeypatch.setattr(server, "MODE", "agent")
    assert server.read_token() == "cva_falsch"


@pytest.mark.parametrize("mode, role, ok", [
    ("reviewer", "reviewer", True), ("reviewer", "agent", False), ("reviewer", "human", False),
    ("agent", "reviewer", False), ("agent", "agent", True),
])
def test_mcp_mode_must_match_the_token_role(monkeypatch, mode, role, ok):
    import httpx
    import conclave.mcp_server as server
    from mcp.server.mcpserver.exceptions import ToolError
    monkeypatch.setattr(server, "MODE", mode)
    monkeypatch.setattr(server, "_confirmed_token", None)
    monkeypatch.setenv("CONCLAVE_REVIEWER_KEY", "cvr_x")
    monkeypatch.setenv("CONCLAVE_AGENT_KEY", "cva_x")
    monkeypatch.setattr(server.httpx, "get", lambda url, **kw: httpx.Response(
        200, json={"role": role}, request=httpx.Request("GET", url)))
    if ok:
        server._check_role()
    else:
        with pytest.raises(ToolError):
            server._check_role()


def test_review_tool_posts_state_and_comment_in_one_call(monkeypatch):
    import httpx
    import conclave.mcp_server as server
    sent = []
    monkeypatch.setattr(server, "MODE", "reviewer")
    monkeypatch.setattr(server, "_confirmed_token", None)
    monkeypatch.setenv("CONCLAVE_REVIEWER_KEY", "cvr_x")
    monkeypatch.setattr(server.httpx, "get", lambda url, **kw: httpx.Response(
        200, json={"role": "reviewer"}, request=httpx.Request("GET", url)))

    def fake_request(method, url, **kw):
        sent.append((method, httpx.URL(url).raw_path.decode(), kw.get("json")))
        return httpx.Response(200, json={"ref": "api#1", "title": "T", "status": "todo", "tags": [],
                                         "human": False, "review": {"state": "rework"}},
                              request=httpx.Request(method, url))

    monkeypatch.setattr(server.httpx, "request", fake_request)
    out = server.conclave_board_review("api#1", "rework", "Urteil: gelb", blocking=1, suggestions=2,
                                       checked="b @ 1..2")
    assert sent == [("POST", "/board/v1/projects/api/tasks/1/review",
                     {"state": "rework", "comment": "Urteil: gelb", "blocking": 1, "suggestions": 2,
                      "checked": "b @ 1..2"})]
    assert out["review_state"] == "rework"
