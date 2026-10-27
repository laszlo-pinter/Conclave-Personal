"""C4: Consultation-Endpunkte, Grenzen, MCP-Tool und Verdrahtung im Server."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("flask")
pytest.importorskip("mcp")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "infrastructure" / "kanzo"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application"))

from fake_kanzo import FakeKanzo, FakeTask  # noqa: E402
from test_consultation_service import FakeReviewer  # noqa: E402

from conclave.api.app import create_app  # noqa: E402
from conclave.application.adapter_registry import AdapterRegistry  # noqa: E402
from conclave.application.consultation_service import ConsultationService  # noqa: E402
from conclave.application.consultation_worker import ConsultationWorker  # noqa: E402
from conclave.application.consultations import ConsultationRequests  # noqa: E402
from conclave.cli.handler import CLIHandler  # noqa: E402
from conclave.domain.consultation import DELIVERED, DONE, FAILED  # noqa: E402
from conclave.infrastructure.kanzo.adapter import KanzoMcpAdapter  # noqa: E402
from conclave.infrastructure.sqlite.consultation_repository import SQLiteConsultationRepository  # noqa: E402


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    from conclave.cli.bootstrap import build_service
    from conclave.cli.config import ConclaveConfig
    from conclave.infrastructure.sqlite.connection import ThreadLocalConnection
    from conclave.infrastructure.sqlite.schema import initialize_schema

    monkeypatch.setenv("CONCLAVE_WORKSPACE", str(tmp_path / "ws"))
    conn = ThreadLocalConnection(tmp_path / "c.db")
    initialize_schema(conn)
    flow = build_service(config=ConclaveConfig(db_path=tmp_path / "c.db"), connection=conn)
    registry = AdapterRegistry()
    reviewers = {"gpt": FakeReviewer("openai", "gpt-5.6"), "claude": FakeReviewer("anthropic", "claude-sonnet-5")}
    for pid, adapter in reviewers.items():
        registry.register(pid, adapter)
    flow.set_adapter_registry(registry)

    kanzo = FakeKanzo()
    kanzo.add(FakeTask("api", 12, "Login bleibt leer", description="Seite leer"))
    kanzo.add(FakeTask("api", 20, "Privat", human=True))
    adapter = KanzoMcpAdapter(kanzo.server)
    repo = SQLiteConsultationRepository(conn, autocommit=True)
    processor = ConsultationService(flow, repo, adapter, adapter, reviewer_name=str.upper)
    worker = ConsultationWorker(repo, processor)
    requests = ConsultationRequests(repo, worker, adapter, allowed_reviewers=("gpt", "claude"),
                                    max_per_hour=3, provider_label=processor.provider_label)
    app = create_app(CLIHandler(flow), consultations=requests)
    app.config["TESTING"] = True
    worker.start()

    e = Env()
    e.client, e.kanzo, e.repo, e.worker, e.reviewers, e.requests = (
        app.test_client(), kanzo, repo, worker, reviewers, requests)
    yield e
    worker.stop()


def _create(env, **body):
    return env.client.post("/consultations", json={"task": "api#12", "question": "Passt das?", **body})


# ── Anlegen ──────────────────────────────────────────────────────────────

def test_create_returns_202_and_discloses_providers(env):
    resp = _create(env)
    assert resp.status_code == 202
    data = resp.get_json()
    assert data["status"] == "queued" and data["channel"] == "rest"
    assert data["reviewers"] == [{"id": "gpt", "provider": "openai, gpt-5.6"},
                                 {"id": "claude", "provider": "anthropic, claude-sonnet-5"}]
    assert env.worker.join()
    done = env.client.get(f"/consultations/{data['id']}").get_json()
    assert done["status"] == DONE and {d["status"] for d in done["deliveries"]} == {DELIVERED}
    assert len(env.kanzo.tasks["api#12"].comments) == 2


def test_subset_of_reviewers(env):
    data = _create(env, reviewers=["claude"]).get_json()
    assert [r["id"] for r in data["reviewers"]] == ["claude"]


@pytest.mark.parametrize("body, error_type", [
    ({"task": "api"}, "ValidationError"),
    ({"task": "api#12; rm"}, "ValidationError"),
    ({"question": ""}, "ValidationError"),
    ({"question": "x" * 4001}, "ValidationError"),
    ({"context": "x" * 8001}, "ValidationError"),
    ({"channel": "mail"}, "ValidationError"),
    ({"include_previous": "ja"}, "ValidationError"),
    ({"reviewers": ["gpt", "gpt"]}, "ValidationError"),
    ({"reviewers": ["gemini"]}, "ReviewerNotAllowed"),
])
def test_invalid_requests(env, body, error_type):
    resp = _create(env, **body)
    assert resp.status_code == 400 and resp.get_json()["type"] == error_type
    assert env.repo.list_by_source_ref("kanzo", "api#12") == []


def test_body_must_be_json_object(env):
    resp = env.client.post("/consultations", json=["api#12"])
    assert resp.status_code == 400


def test_limit_per_ticket_and_hour_counted_at_post(env):
    for _ in range(3):
        assert _create(env).status_code == 202
    resp = _create(env)
    assert resp.status_code == 429 and resp.get_json()["type"] == "ConsultationLimit"
    assert _create(env, task="api#20").status_code == 202        # anderes Ticket, eigene Grenze


def test_unknown_ticket_is_404_before_anything_is_stored(env):
    resp = _create(env, task="api#99")
    assert resp.status_code == 404
    assert env.repo.list_by_source_ref("kanzo", "api#99") == []


def test_human_ticket_rejected_for_mcp_but_allowed_for_rest(env):
    resp = _create(env, task="api#20", channel="mcp")
    assert resp.status_code == 403 and resp.get_json()["type"] == "HumanOnlyTicket"
    assert _create(env, task="api#20").status_code == 202


def test_kanzo_down_is_502(env):
    env.requests._source = KanzoMcpAdapter("http://127.0.0.1:9/mcp", timeout=3)
    resp = _create(env)
    assert resp.status_code == 502 and "mcp_http" in resp.get_json()["error"]


def test_disabled_without_reviewer_list(env):
    env.requests._allowed = ()
    resp = _create(env)
    assert resp.status_code == 503 and resp.get_json()["type"] == "ConsultationsDisabled"


def test_disabled_without_consultations_object():
    client = create_app(CLIHandler(None)).test_client()
    assert client.post("/consultations", json={"task": "api#1", "question": "?"}).status_code == 503


# ── Abfragen ─────────────────────────────────────────────────────────────

def test_get_and_list(env):
    cid = _create(env).get_json()["id"]
    assert env.client.get(f"/consultations/{cid}").status_code == 200
    assert env.client.get("/consultations/gibtsnicht").status_code == 404
    listed = env.client.get("/consultations?source_ref=api%2312").get_json()["consultations"]
    assert [c["id"] for c in listed] == [cid]
    assert env.client.get("/consultations?source_ref=kaputt").status_code == 400


# ── Retry ────────────────────────────────────────────────────────────────

def test_retry_delivers_failed_comments_without_calling_models(env):
    class Down:
        def add_comment(self, *a, **k):
            raise ConnectionError("Kanzo weg")

    sink = env.worker._processor._sink
    env.worker._processor._sink = Down()
    cid = _create(env, reviewers=["gpt"]).get_json()["id"]
    assert env.worker.join()
    failed = env.client.get(f"/consultations/{cid}").get_json()
    assert failed["status"] == FAILED and failed["retry_possible"]
    calls_before = len(env.reviewers["gpt"].prompts)

    env.worker._processor._sink = sink
    assert env.client.post(f"/consultations/{cid}/retry", json={}).status_code == 202
    assert env.worker.join()
    done = env.client.get(f"/consultations/{cid}").get_json()
    assert done["status"] == DONE and done["deliveries"][0]["attempts"] == 2
    assert len(env.reviewers["gpt"].prompts) == calls_before          # kein neuer Modellaufruf
    assert len(env.kanzo.tasks["api#12"].comments) == 1


def test_retry_without_answers_needs_rerun(env):
    env.reviewers["gpt"].fail = True
    cid = _create(env, reviewers=["gpt"]).get_json()["id"]
    assert env.worker.join()
    resp = env.client.post(f"/consultations/{cid}/retry", json={})
    assert resp.status_code == 409 and resp.get_json()["type"] == "NothingToDeliver"

    env.reviewers["gpt"].fail = False
    resp = env.client.post(f"/consultations/{cid}/retry", json={"rerun": True})
    assert resp.status_code == 202
    new_id = resp.get_json()["id"]
    assert new_id != cid
    assert env.worker.join()
    assert env.client.get(f"/consultations/{new_id}").get_json()["status"] == DONE


def test_retry_of_running_consultation_is_409(env):
    cid = _create(env).get_json()["id"]
    assert env.worker.join()
    c = env.repo.get(cid)
    c.status = "running"
    env.repo.save(c)
    assert env.client.post(f"/consultations/{cid}/retry", json={}).status_code == 409
    assert env.client.post(f"/consultations/{cid}/retry", json={"rerun": "ja"}).status_code == 400


# ── MCP-Tool und Server ──────────────────────────────────────────────────

def test_mcp_tool_always_sends_channel_mcp():
    import conclave.mcp_server as server
    with patch.object(server, "_post", return_value={"id": "x"}) as post:
        server.conclave_consult("api#12", "Passt das?", reviewers=["gpt"])
    path, body = post.call_args.args
    assert path == "/consultations" and body["channel"] == "mcp" and body["reviewers"] == ["gpt"]


def test_build_app_registers_worker_without_starting_it(tmp_path, monkeypatch):
    from conclave.api.server import _build_app
    from conclave.cli.config import ConclaveConfig, KanzoSettings

    for name, value in (("CONCLAVE_WORKSPACE", tmp_path / "ws"), ("CONCLAVE_SECRET_KEY_FILE", tmp_path / "k"),
                        ("CONCLAVE_API_TOKEN_FILE", tmp_path / "t")):
        monkeypatch.setenv(name, str(value))
    started = []
    monkeypatch.setattr(ConsultationWorker, "start", lambda self: started.append(self))
    config = ConclaveConfig(db_path=tmp_path / "c.db", kanzo=KanzoSettings(reviewers=("gpt",)))
    app, _ = _build_app(config)
    [worker] = app.extensions["conclave_workers"]
    assert isinstance(worker, ConsultationWorker) and started == []
    client = app.test_client()
    headers = {"Authorization": f"Bearer {(tmp_path / 't').read_text().strip()}"}
    assert client.get("/consultations?source_ref=api%231", headers=headers).status_code == 200
