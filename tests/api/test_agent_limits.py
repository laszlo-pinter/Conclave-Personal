"""R11 (conclave#46): Kosten- und Laufgrenzen fuer Agenten, Rate-Limit nach Principal.

- Tagesbudget (Tokens) je Agent-Zugang und je Conversation; erschoepft -> 429 mit klarer Meldung.
- Hoechstens N gleichzeitige Modelllaeufe fuer Agenten.
- Rate-Limit nach Zugang und IP, eigene Grenze fuer Agenten: die UI bleibt bedienbar.
- Kreisfoermiger Agenten-Workflow (immer wieder dieselbe Conversation) endet am Budget.
"""

import sqlite3
import threading

import pytest

pytest.importorskip("flask")

from conclave.api.app import create_app  # noqa: E402
from conclave.application.adapter_registry import AdapterRegistry  # noqa: E402
from conclave.application.conversation_flow import ConversationFlowService  # noqa: E402
from conclave.cli.config import ConclaveConfig, LimitSettings  # noqa: E402
from conclave.cli.handler import CLIHandler  # noqa: E402
from conclave.domain.model_response import Completion, TokenUsage  # noqa: E402
from conclave.domain.participant import ParticipantType  # noqa: E402
from conclave.infrastructure.auth import StaticKeyAuthService  # noqa: E402
from conclave.infrastructure.sqlite.conversation_repository import SQLiteConversationRepository  # noqa: E402
from conclave.infrastructure.sqlite.message_repository import SQLiteMessageRepository  # noqa: E402
from conclave.infrastructure.sqlite.participant_repository import SQLiteParticipantRepository  # noqa: E402
from conclave.infrastructure.sqlite.run_repository import SQLiteRunRepository  # noqa: E402
from conclave.infrastructure.sqlite.schema import initialize_schema  # noqa: E402

HUMAN, AGENT = "cvh_mensch", "cva_agent"


class Model:
    """Fake-Modell: 100 Tokens je Aufruf; mit ``gate`` haelt es an, bis der Test es freigibt."""

    def __init__(self):
        self.gate = None
        self.started = threading.Event()

    def complete(self, conversation, participant):
        self.started.set()
        if self.gate is not None:
            self.gate.wait(5)
        return Completion(text="ok", usage=TokenUsage(60, 40))


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _app(limits, rate_limit="1000 per minute", conn=None):
    conn = conn or sqlite3.connect(":memory:", check_same_thread=False)
    initialize_schema(conn)
    service = ConversationFlowService(
        conversation_repository=SQLiteConversationRepository(conn, autocommit=True),
        message_repository=SQLiteMessageRepository(conn, autocommit=True),
        participant_repository=SQLiteParticipantRepository(conn, autocommit=True),
    )
    runs = SQLiteRunRepository(conn)
    service.set_run_repository(runs)
    model = Model()
    registry = AdapterRegistry()
    registry.register("m1", model)
    service.set_adapter_registry(registry)
    convs = []
    for _ in range(2):
        conv = service.create_conversation()
        service.register_participant(conversation_id=conv.id, participant_id="m1",
                                     participant_type=ParticipantType.MODEL, name="M1")
        service.add_user_message(conv.id, "Frage")
        convs.append(conv.id)
    config = ConclaveConfig(api_key=HUMAN, agent_api_key=AGENT, rate_limit=rate_limit, limits=limits)
    app = create_app(CLIHandler(service), auth_service=StaticKeyAuthService(HUMAN, AGENT), config=config,
                     service=service)
    app.config["TESTING"] = True
    app.extensions["test_runs"] = runs
    return app, convs, model


def _invoke(client, conv, token):
    return client.post(f"/conversations/{conv}/participants/m1/invoke", json={}, headers=_bearer(token))


def test_agent_budget_exhausted_returns_429_with_a_clear_message():
    app, (conv, other), _ = _app(LimitSettings(agent_tokens_per_day=250, conversation_tokens_per_day=0))
    c = app.test_client()
    for _ in range(3):                                           # 100 Tokens je Aufruf: 0, 100, 200 -> ok
        assert _invoke(c, conv if _ % 2 == 0 else other, AGENT).status_code == 200
    resp = _invoke(c, conv, AGENT)
    assert resp.status_code == 429
    body = resp.get_json()
    assert body["type"] == "AgentBudgetExceeded" and "250" in body["error"] and "Tokens" in body["error"]
    assert _invoke(c, conv, HUMAN).status_code == 200            # der Mensch arbeitet weiter


def test_conversation_budget_for_agents():
    app, (conv, other), _ = _app(LimitSettings(agent_tokens_per_day=0, conversation_tokens_per_day=150))
    c = app.test_client()
    assert _invoke(c, conv, AGENT).status_code == 200
    assert _invoke(c, conv, AGENT).status_code == 200            # 100 < 150
    resp = _invoke(c, conv, AGENT)
    assert resp.status_code == 429 and resp.get_json()["type"] == "ConversationBudgetExceeded"
    assert _invoke(c, other, AGENT).status_code == 200           # andere Conversation: eigenes Budget


def test_circular_agent_workflow_stops_at_the_budget():
    """Ein Agent, der dieselbe Conversation immer wieder orchestrieren laesst, laeuft nicht endlos."""
    app, (conv, _), _ = _app(LimitSettings(agent_tokens_per_day=1000, conversation_tokens_per_day=0))
    c = app.test_client()
    statuses = [c.post(f"/conversations/{conv}/orchestrate", json={"sequence": ["m1", "m1"]},
                       headers=_bearer(AGENT)).status_code for _ in range(20)]
    assert 429 in statuses
    assert statuses.index(429) <= 6                              # 200 Tokens je Runde, Budget 1000
    assert all(s == 429 for s in statuses[statuses.index(429):])


def test_concurrent_agent_runs_are_limited():
    app, (conv, other), model = _app(LimitSettings(agent_concurrent_runs=1, agent_tokens_per_day=0,
                                                   conversation_tokens_per_day=0))
    model.gate = threading.Event()
    results = {}

    def first():
        with app.test_client() as c:
            results["first"] = _invoke(c, conv, AGENT).status_code

    t = threading.Thread(target=first)
    t.start()
    assert model.started.wait(5)
    with app.test_client() as c:
        second = _invoke(c, other, AGENT)
        assert second.status_code == 429 and second.get_json()["type"] == "TooManyAgentRuns"
        model.gate.set()
        t.join(5)
        assert results["first"] == 200
        assert _invoke(c, other, AGENT).status_code == 200      # wieder frei


def test_agent_rate_limit_does_not_slow_down_the_ui():
    app, (conv, _), _ = _app(LimitSettings(agent_rate_limit="3 per minute"), rate_limit="100 per minute")
    c = app.test_client()
    codes = [c.get("/conversations", headers=_bearer(AGENT)).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert all(c.get("/conversations", headers=_bearer(HUMAN)).status_code == 200 for _ in range(10))


def test_limits_are_read_from_config_toml(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[limits]\nagent_tokens_per_day = 5000\nconversation_tokens_per_day = 700\n'
                    'agent_concurrent_runs = 3\nagent_rate_limit = "30 per minute"\n', encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_CONFIG_FILE", str(path))
    limits = ConclaveConfig.from_sources().limits
    assert (limits.agent_tokens_per_day, limits.conversation_tokens_per_day, limits.agent_concurrent_runs,
            limits.agent_rate_limit) == (5000, 700, 3, "30 per minute")


@pytest.mark.parametrize("section", ['agent_tokens_per_day = -1', 'agent_concurrent_runs = "viele"',
                                     'agent_rate_limit = "schnell"'])
def test_invalid_limits_are_rejected(tmp_path, monkeypatch, section):
    path = tmp_path / "config.toml"
    path.write_text(f"[limits]\n{section}\n", encoding="utf-8")
    monkeypatch.setenv("CONCLAVE_CONFIG_FILE", str(path))
    with pytest.raises(ValueError):
        ConclaveConfig.from_sources()


# ── Nacharbeit aus dem Review (B1, V2) ──────────────────────────────────────

def test_agent_rate_limit_applies_when_the_general_limit_is_off():
    """B1: Das Limit der Agenten haengt nicht am allgemeinen Schalter."""
    app, _, _ = _app(LimitSettings(agent_rate_limit="3 per minute"), rate_limit="off")
    c = app.test_client()
    codes = [c.get("/conversations", headers=_bearer(AGENT)).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert all(c.get("/conversations", headers=_bearer(HUMAN)).status_code == 200 for _ in range(10))


def test_human_run_during_an_agent_request_does_not_count_against_the_agents(tmp_path):
    """V2: Herkunft beim Speichern; ein gleichzeitiger Lauf des Menschen bleibt beim Menschen."""
    from datetime import UTC, datetime, timedelta

    from conclave.infrastructure.sqlite.connection import ThreadLocalConnection

    # Zwei Laeufe gleichzeitig: wie im Server eine Verbindung je Thread
    app, (conv, _), model = _app(LimitSettings(agent_tokens_per_day=0, conversation_tokens_per_day=0,
                                               agent_concurrent_runs=0),
                                 conn=ThreadLocalConnection(tmp_path / "limits.db"))
    model.gate = threading.Event()
    results = {}

    def agent_call():
        with app.test_client() as c:
            results["agent"] = _invoke(c, conv, AGENT).status_code

    t = threading.Thread(target=agent_call)
    t.start()
    assert model.started.wait(5)
    def human_call():
        with app.test_client() as c:
            results["human"] = _invoke(c, conv, HUMAN).status_code

    human = threading.Thread(target=human_call)
    human.start()
    model.gate.set()
    human.join(5)
    t.join(5)
    assert results == {"agent": 200, "human": 200}
    runs = app.extensions["test_runs"]
    since = datetime.now(UTC) - timedelta(days=1)
    assert runs.tokens_since(since, origin="agent") == 100                  # nur der Lauf des Agenten
    assert runs.tokens_since(since) == 200
