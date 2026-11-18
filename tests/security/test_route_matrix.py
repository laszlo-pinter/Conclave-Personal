"""R15 (conclave#50): Routen-Matrix gegen eine Soll-Tabelle.

Jede registrierte Route steht hier mit der Rolle, die sie aufrufen darf. Die
Tabelle ist bewusst unabhaengig von ``api/access.py``: Eine neue Route ohne
Eintrag laesst den Test scheitern, ebenso eine stille Aenderung der Allowlists.

Geprueft wird jede Route mit {kein Token, Mensch, Agent, Reviewer}. Die Views
sind durch Stubs ersetzt; so pruefen die Anfragen nur die Zugriffsschicht und
loesen nichts aus (kein Backup, kein Restore, keine Modellaufrufe).

Rollen:
    public          ohne Token
    human           nur der Mensch
    agent           Mensch und Agent
    agent+reviewer  Mensch, Agent und Reviewer
    reviewer        Mensch (Zugriffsschicht) und Reviewer; der BoardService
                    nimmt das Review nur vom Reviewer an
"""

import re

import pytest

pytest.importorskip("flask")

HUMAN, AGENT, REVIEWER = "cvh_matrix-mensch", "cva_matrix-agent", "cvr_matrix-reviewer"

EXPECTED = {
    ("GET", "/"): "public",
    ("GET", "/agent-roles"): "human",
    ("GET", "/agents"): "agent",
    ("POST", "/agents"): "human",
    ("DELETE", "/agents/<agent_id>"): "human",
    ("GET", "/agents/<agent_id>"): "human",
    ("PUT", "/agents/<agent_id>"): "human",
    ("POST", "/agents/<agent_id>/test"): "human",
    ("GET", "/api-docs"): "public",
    ("GET", "/ui/board"): "public",
    ("GET", "/ui/board/static/<path:filename>"): "public",
    ("GET", "/auth/whoami"): "agent+reviewer",
    ("POST", "/backup"): "human",
    ("GET", "/backups"): "human",
    ("GET", "/board"): "human",
    ("GET", "/board/changes"): "agent+reviewer",
    ("GET", "/board/reviewer"): "human",
    ("POST", "/board/reviewer/heartbeat"): "reviewer",
    ("DELETE", "/board/comments/<comment_id>"): "human",
    ("PUT", "/board/comments/<comment_id>"): "human",
    ("POST", "/board/import"): "human",
    ("POST", "/board/next"): "agent",
    ("POST", "/board/projects"): "human",
    ("DELETE", "/board/projects/<slug>"): "human",
    ("PUT", "/board/projects/<slug>"): "human",
    ("GET", "/board/projects/<slug>/history"): "human",
    ("GET", "/board/projects/<slug>/initiatives"): "agent",
    ("POST", "/board/projects/<slug>/initiatives"): "human",
    ("PUT", "/board/projects/<slug>/initiatives/<initiative>"): "human",
    ("GET", "/board/projects/<slug>/initiatives/<initiative>/tasks/<int:number>"): "agent+reviewer",
    ("DELETE", "/board/projects/<slug>/tasks/<int:number>"): "human",
    ("GET", "/board/projects/<slug>/tasks/<int:number>"): "agent+reviewer",
    ("PATCH", "/board/projects/<slug>/tasks/<int:number>"): "agent",
    ("GET", "/board/projects/<slug>/tasks/<int:number>/comments"): "human",
    ("POST", "/board/projects/<slug>/tasks/<int:number>/comments"): "agent+reviewer",
    ("GET", "/board/projects/<slug>/tasks/<int:number>/history"): "agent+reviewer",
    ("POST", "/board/projects/<slug>/tasks/<int:number>/review"): "reviewer",
    ("GET", "/board/search"): "agent+reviewer",
    ("GET", "/board/tasks"): "agent+reviewer",
    ("POST", "/board/tasks"): "agent",
    ("GET", "/consultations"): "human",
    ("POST", "/consultations"): "agent",
    ("GET", "/consultations/<consultation_id>"): "agent",
    ("POST", "/consultations/<consultation_id>/retry"): "human",
    ("GET", "/conversations"): "agent",
    ("POST", "/conversations"): "agent",
    ("DELETE", "/conversations/<conversation_id>"): "human",
    ("GET", "/conversations/<conversation_id>"): "agent",
    ("POST", "/conversations/<conversation_id>/auto-loop"): "human",
    ("GET", "/conversations/<conversation_id>/export"): "agent",
    ("POST", "/conversations/<conversation_id>/floor/grant"): "human",
    ("POST", "/conversations/<conversation_id>/floor/invoke"): "human",
    ("POST", "/conversations/<conversation_id>/floor/revoke"): "human",
    ("POST", "/conversations/<conversation_id>/messages"): "agent",
    ("GET", "/conversations/<conversation_id>/messages/<message_id>/context"): "agent",
    ("POST", "/conversations/<conversation_id>/orchestrate"): "agent",
    ("POST", "/conversations/<conversation_id>/orchestrate-parallel"): "agent",
    ("POST", "/conversations/<conversation_id>/orchestrate-parallel-stream"): "human",
    ("POST", "/conversations/<conversation_id>/participants"): "agent",
    ("DELETE", "/conversations/<conversation_id>/participants/<participant_id>"): "human",
    ("GET", "/conversations/<conversation_id>/participants/<participant_id>/context-preview"): "human",
    ("POST", "/conversations/<conversation_id>/participants/<participant_id>/invoke"): "agent",
    ("GET", "/conversations/<conversation_id>/participants/<participant_id>/stream"): "human",
    ("GET", "/conversations/<conversation_id>/rules"): "agent",
    ("POST", "/conversations/<conversation_id>/rules"): "human",
    ("GET", "/conversations/<conversation_id>/tool-events"): "agent",
    ("POST", "/conversations/<conversation_id>/topic"): "agent",
    ("GET", "/health"): "public",
    ("GET", "/logs"): "human",
    ("GET", "/openapi.json"): "public",
    ("GET", "/presets"): "human",
    ("GET", "/providers"): "human",
    ("POST", "/restore"): "human",
    ("GET", "/runs"): "human",
    ("GET", "/runs/<run_id>"): "human",
    ("GET", "/settings"): "human",
    ("PUT", "/settings"): "human",
    ("GET", "/static/<path:filename>"): "public",
    ("GET", "/usage"): "agent",
    ("GET", "/usage/conversations"): "human",
    ("GET", "/workspace"): "agent",
    ("DELETE", "/workspace/<path:filepath>"): "human",
    ("GET", "/workspace/<path:filepath>"): "agent",
    ("POST", "/workspace/<path:filepath>"): "agent",
}

# T5: haengende Tickets anzeigen und freigeben (nur Mensch)
EXPECTED[("GET", "/board/stuck")] = "human"
EXPECTED[("POST", "/board/projects/<slug>/tasks/<int:number>/release")] = "human"

# T3: Jede Board-Route gibt es auch unter /board/v1 mit derselben Rolle; /board bleibt als Alias.
EXPECTED.update({(method, "/board/v1" + rule[len("/board"):]): role for (method, rule), role in list(EXPECTED.items())
                 if rule == "/board" or rule.startswith("/board/")})
EXPECTED[("GET", "/board/versions")] = "public"

ALLOWED = {
    "public": {"none", "human", "agent", "reviewer"},
    "human": {"human"},
    "agent": {"human", "agent"},
    "agent+reviewer": {"human", "agent", "reviewer"},
    "reviewer": {"human", "reviewer"},
}
TOKENS = {"none": None, "human": HUMAN, "agent": AGENT, "reviewer": REVIEWER}


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig, LimitSettings

    root = tmp_path_factory.mktemp("matrix")
    with pytest.MonkeyPatch.context() as mp:
        for name, file in (("CONCLAVE_SECRET_KEY_FILE", "secret.key"), ("CONCLAVE_API_TOKEN_FILE", "api.token"),
                           ("CONCLAVE_AGENT_TOKEN_FILE", "agent.token"),
                           ("CONCLAVE_REVIEWER_TOKEN_FILE", "reviewer.token")):
            mp.setenv(name, str(root / file))
        mp.setenv("CONCLAVE_WORKSPACE", str(root / "workspace"))
        mp.setenv("CONCLAVE_BACKUP_DIR", str(root / "backups"))
        config = ConclaveConfig(db_path=root / "c.db", api_key=HUMAN, agent_api_key=AGENT,
                                reviewer_api_key=REVIEWER, rate_limit="off",
                                limits=LimitSettings(agent_rate_limit="off"))
        app, _ = _build_app(config)
    app.config["TESTING"] = True
    # Nur die Zugriffsschicht pruefen: jede View antwortet 204, ohne etwas auszuloesen
    for endpoint in list(app.view_functions):
        app.view_functions[endpoint] = lambda **_: ("", 204)
    return app


def registered(app):
    return {(method, rule.rule) for rule in app.url_map.iter_rules()
            for method in rule.methods - {"HEAD", "OPTIONS"}}


def _url(rule):
    rule = re.sub(r"<path:[^>]+>", "matrix/datei.txt", rule)
    rule = re.sub(r"<int:[^>]+>", "999", rule)
    return re.sub(r"<(?:[^:>]+:)?([^>]+)>", lambda m: f"{m.group(1)}-matrix", rule)


def test_every_route_is_in_the_table(app):
    routes = registered(app)
    assert sorted(routes - set(EXPECTED)) == [], "Route ohne Eintrag in der Soll-Tabelle"
    assert sorted(set(EXPECTED) - routes) == [], "Eintrag in der Soll-Tabelle ohne Route"


def test_a_new_route_without_entry_fails(app):
    """Abnahme: eine neue Route ohne Eintrag laesst die Pruefung scheitern."""
    from flask import Flask
    other = Flask("neu")
    other.add_url_rule("/neu", "neu", lambda: "", methods=["GET"])
    assert ("GET", "/neu") in registered(other) - set(EXPECTED)


@pytest.mark.parametrize("who", list(TOKENS))
@pytest.mark.parametrize("method, rule", sorted(EXPECTED))
def test_route_matrix(app, method, rule, who):
    token = TOKENS[who]
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    kwargs = {} if method == "GET" else {"json": {}}
    status = app.test_client().open(_url(rule), method=method, headers=headers, **kwargs).status_code
    if who in ALLOWED[EXPECTED[(method, rule)]]:
        assert status == 204, f"{who} {method} {rule}: erwartet erlaubt, bekam {status}"
    else:
        assert status == (401 if who == "none" else 403), f"{who} {method} {rule}: erwartet abgelehnt, bekam {status}"
