"""Z2: Allowlist fuer den Agent-Zugang (Default deny), 403 HumanOnly."""

import re

import pytest
pytest.importorskip("flask")
pytest.importorskip("mcp")

from conclave.api.access import AGENT_ALLOWED, HUMAN_ONLY, HUMAN_ONLY_ERROR, PUBLIC, agent_may
from conclave.cli.config import ConclaveConfig

HUMAN = "cvh_mensch-token"
AGENT = "cva_agent-token"


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app(tmp_path):
    from conclave.api.server import _build_app
    app, _ = _build_app(ConclaveConfig(db_path=tmp_path / "c.db", api_key=HUMAN, agent_api_key=AGENT))
    app.config["TESTING"] = True
    return app


def _registered(app):
    pairs = set()
    for rule in app.url_map.iter_rules():
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            pairs.add((method, rule.rule))
    return pairs


def _url(rule):
    """Beispiel-URL zu einem Routen-Muster: <x> -> x1, <path:p> -> a/b.txt."""
    rule = re.sub(r"<path:[^>]+>", "a/b.txt", rule)
    return re.sub(r"<(?:[^:>]+:)?([^>]+)>", lambda m: f"{m.group(1)}1", rule)


# ── Vollstaendigkeit ──────────────────────────────────────────────────────

def test_every_route_is_assigned_exactly_once(app):
    registered = _registered(app)
    assigned = AGENT_ALLOWED | HUMAN_ONLY | PUBLIC
    assert not registered - assigned, "Route ohne Zuordnung in api/access.py"
    assert not assigned - registered, "Eintrag in api/access.py ohne Route"
    assert not AGENT_ALLOWED & HUMAN_ONLY
    assert not (AGENT_ALLOWED | HUMAN_ONLY) & PUBLIC


def test_new_unassigned_route_fails_the_completeness_check(app):
    app.add_url_rule("/neu", "neu", lambda: "x", methods=["GET"])
    assert _registered(app) - (AGENT_ALLOWED | HUMAN_ONLY | PUBLIC) == {("GET", "/neu")}
    # und Agenten kommen nicht durch (Default deny)
    assert app.test_client().get("/neu", headers=_bearer(AGENT)).status_code == 403
    assert app.test_client().get("/neu", headers=_bearer(HUMAN)).status_code == 200


def test_no_delete_for_agents():
    assert not [pair for pair in AGENT_ALLOWED if pair[0] == "DELETE"]      # E2


# ── Antworten ─────────────────────────────────────────────────────────────

def test_put_settings_agent_403_human_200(app):
    c = app.test_client()
    resp = c.put("/settings", json={}, headers=_bearer(AGENT))
    assert resp.status_code == 403
    assert resp.get_json() == HUMAN_ONLY_ERROR == {"type": "HumanOnly", "error": "Nur für den Menschen-Zugang."}
    assert c.put("/settings", json={}, headers=_bearer(HUMAN)).status_code == 200


@pytest.mark.parametrize("method, rule", sorted(HUMAN_ONLY))
def test_every_human_only_route_is_403_for_agents(app, method, rule):
    resp = app.test_client().open(_url(rule), method=method, json={}, headers=_bearer(AGENT))
    assert resp.status_code == 403, (method, rule)
    assert resp.get_json()["type"] == "HumanOnly"


@pytest.mark.parametrize("method, rule", sorted(HUMAN_ONLY))
def test_human_only_routes_are_not_blocked_for_humans(app, method, rule):
    if rule == "/restore":
        pytest.skip("Restore ersetzt die Datenbank; fuer den Zugang genuegt die Agent-Seite")
    resp = app.test_client().open(_url(rule), method=method, json={}, headers=_bearer(HUMAN))
    assert resp.status_code != 403 or resp.get_json().get("type") != "HumanOnly", (method, rule)


def test_retry_with_rerun_is_403_for_agents(app):
    resp = app.test_client().post("/consultations/x1/retry", json={"rerun": True}, headers=_bearer(AGENT))
    assert resp.status_code == 403


def test_head_counts_like_get():
    assert agent_may("HEAD", "/conversations")
    assert not agent_may("HEAD", "/settings")


def test_unknown_route_answers_agents_like_humans(app):
    # /<path:path> nimmt nur OPTIONS an (CORS), daher 405 statt 404 – fuer beide gleich.
    c = app.test_client()
    agent = c.get("/gibt-es-nicht", headers=_bearer(AGENT))
    assert agent.status_code == c.get("/gibt-es-nicht", headers=_bearer(HUMAN)).status_code
    assert agent.status_code in (404, 405)


def test_wrong_method_on_allowed_route_is_405_or_403_never_200(app):
    resp = app.test_client().put("/conversations", json={}, headers=_bearer(AGENT))
    assert resp.status_code in (403, 405)


def test_public_paths_need_no_token(app):
    c = app.test_client()
    for _method, rule in PUBLIC - {("GET", "/static/<path:filename>")}:
        assert c.get(rule).status_code == 200, rule


# ── MCP-Tools mit dem Agent-Token ─────────────────────────────────────────

@pytest.fixture
def mcp_via_app(app, monkeypatch):
    """Leitet die HTTP-Aufrufe des MCP-Servers mit dem Agent-Token an die App."""
    import conclave.mcp_server as server
    from mcp.server.mcpserver.exceptions import ToolError

    client = app.test_client()
    adapter = app.url_map.bind("localhost")
    hits = []

    def fake_request(method, path, *, timeout, **kwargs):
        rule, _ = adapter.match(path.split("?")[0], method=method, return_rule=True)
        resp = client.open(path, method=method, json=kwargs.get("json"),
                           query_string=kwargs.get("params"), headers=_bearer(AGENT))
        hits.append((method, rule.rule, resp.status_code))
        if resp.status_code >= 400:
            body = resp.get_json(silent=True) or {}
            raise ToolError(f"Conclave-API {resp.status_code}: {body.get('error')}")
        return resp.get_json(silent=True) or {}

    monkeypatch.setattr(server, "_request", fake_request)
    return server, hits, ToolError


def test_every_mcp_tool_route_works_with_agent_token(mcp_via_app):
    server, hits, ToolError = mcp_via_app

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            return None              # fachliche Fehler (z. B. fehlender Provider) sind hier egal

    conv = server.conclave_create_conversation("Z2")["conversation_id"]
    call(server.conclave_list_conversations)
    call(server.conclave_get_conversation, conv)
    call(server.conclave_add_participant, conv, "p1")
    call(server.conclave_list_agents)
    call(server.conclave_send_message, conv, "Hallo")
    call(server.conclave_get_messages, conv)
    call(server.conclave_invoke, conv, "p1")
    call(server.conclave_orchestrate, conv, ["p1"])
    call(server.conclave_orchestrate, conv, ["p1"], parallel=True)
    call(server.conclave_export_conversation, conv)
    call(server.conclave_get_usage)
    call(server.conclave_upload_file, "z2/notiz.md", "x")
    call(server.conclave_list_files)
    call(server.conclave_read_file, "z2/notiz.md")
    call(server.conclave_consult, "conclave#1", "Frage?")
    call(server.conclave_get_consultation, "gibtsnicht")

    blocked = [(m, r, s) for m, r, s in hits if s in (401, 403)]
    assert not blocked, blocked
    used = {(m, r) for m, r, _ in hits}
    # Die Allowlist ist genau das, was die Tools brauchen, plus whoami (Z5).
    assert used | {("GET", "/auth/whoami")} == AGENT_ALLOWED


def test_mcp_delete_tools_are_refused_for_agents(mcp_via_app):
    server, hits, ToolError = mcp_via_app
    conv = server.conclave_create_conversation("Z2")["conversation_id"]
    with pytest.raises(ToolError, match="403"):
        server.conclave_delete_conversation(conv)
    with pytest.raises(ToolError, match="403"):
        server.conclave_delete_file("z2/notiz.md")
    assert server.conclave_get_conversation(conv)["id"] == conv       # nichts geloescht
