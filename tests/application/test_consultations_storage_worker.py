"""C2: Consultation-Domain, Speicherung (SQLite), Hintergrund-Worker und sein Start."""

import socket
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from conclave.application.consultation_worker import ConsultationWorker, should_start_workers
from conclave.domain.consultation import (
    DELIVERED,
    DONE,
    FAILED,
    INTERRUPTED,
    PENDING,
    QUEUED,
    RUNNING,
    Consultation,
    ConsultationDelivery,
    consultation_marker,
)
from conclave.infrastructure.migrations import run_migrations
from conclave.infrastructure.sqlite.connection import ThreadLocalConnection
from conclave.infrastructure.sqlite.consultation_repository import SQLiteConsultationRepository
from conclave.infrastructure.sqlite.schema import initialize_schema
from conclave.runtime.serve import serve, start_background_workers


def _new(ref="api#12", **kw):
    return Consultation.create(source="kanzo", source_ref=ref, question="Passt der Ansatz?",
                               reviewers=kw.pop("reviewers", ["gpt", "claude"]), **kw)


@pytest.fixture
def repo(tmp_path):
    conn = ThreadLocalConnection(tmp_path / "c.db")
    initialize_schema(conn)
    return SQLiteConsultationRepository(conn, autocommit=True)


# ── Domain ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kw", [
    {"question": " "}, {"reviewers": []}, {"channel": "mail"}, {"mode": "debate"}, {"source_ref": ""},
])
def test_consultation_validation(kw):
    base = dict(id="x", source="kanzo", source_ref="api#1", question="Frage", reviewers=("gpt",))
    base.update(kw)
    with pytest.raises(ValueError):
        Consultation(**base)


def test_marker_contains_consultation_and_reviewer():
    d = ConsultationDelivery.create(consultation_id="abc", participant_id="gpt")
    assert d.marker == consultation_marker("abc", "gpt") == "consultation abc/gpt"


# ── Repository ───────────────────────────────────────────────────────────

def test_save_get_roundtrip(repo):
    c = _new(channel="mcp", context="Zusatz", requested_by="claude-code", include_previous=True)
    repo.save(c)
    loaded = repo.get(c.id)
    assert (loaded.reviewers, loaded.channel, loaded.context, loaded.include_previous, loaded.status) == (
        ("gpt", "claude"), "mcp", "Zusatz", True, QUEUED)
    assert repo.get("gibtsnicht") is None


def test_status_update_and_lists(repo):
    a, b, other = _new(), _new(), _new(ref="api#13")
    start = datetime.now(UTC)
    for offset, c in enumerate((a, b, other)):
        c.created_at = start + timedelta(seconds=offset)   # eindeutige Reihenfolge, keine Gleichstaende
        repo.save(c)
    a.status, a.conversation_id, a.finished_at = DONE, "conv-1", datetime.now(UTC)
    repo.save(a)
    assert repo.get(a.id).conversation_id == "conv-1"
    assert {c.id for c in repo.list_by_source_ref("kanzo", "api#12")} == {a.id, b.id}
    assert [c.id for c in repo.list_by_status(QUEUED)] == [b.id, other.id]


def test_count_since_for_rate_limit(repo):
    old = _new()
    old.created_at = datetime.now(UTC) - timedelta(hours=2)
    repo.save(old)
    repo.save(_new())
    repo.save(_new())
    since = datetime.now(UTC) - timedelta(hours=1)
    assert repo.count_since("kanzo", "api#12", since) == 2
    assert repo.count_since("kanzo", "api#99", since) == 0


def test_claim_is_atomic(repo):
    c = _new()
    repo.save(c)
    assert repo.claim(c.id) is True
    assert repo.claim(c.id) is False                       # schon running
    assert repo.get(c.id).status == RUNNING


def test_claim_from_many_threads_succeeds_once(repo):
    c = _new()
    repo.save(c)
    barrier = threading.Barrier(8)
    results = []

    def grab():
        barrier.wait()
        results.append(repo.claim(c.id))

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1


def test_deliveries_roundtrip_and_update(repo):
    c = _new()
    repo.save(c)
    d = ConsultationDelivery.create(consultation_id=c.id, participant_id="gpt", message_id="m1")
    repo.save_delivery(d)
    d.status, d.attempts, d.delivered_at = DELIVERED, 1, datetime.now(UTC)
    repo.save_delivery(d)
    [loaded] = repo.list_deliveries(c.id)
    assert (loaded.status, loaded.attempts, loaded.marker, loaded.message_id) == (
        DELIVERED, 1, f"consultation {c.id}/gpt", "m1")


def test_existing_database_gets_tables_via_migration():
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    conn.execute("DROP TABLE consultation_deliveries")
    conn.execute("DROP TABLE consultations")
    conn.execute("DELETE FROM _migrations WHERE id = '009_consultations'")
    conn.commit()
    assert "009_consultations" in run_migrations(conn)
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name = 'consultations'").fetchone() == (1,)


# ── Worker ───────────────────────────────────────────────────────────────

class Recorder:
    def __init__(self, repo, fail=False):
        self.repo, self.fail = repo, fail
        self.runs, self.deliveries = [], []
        self.lock = threading.Lock()

    def run(self, c):
        with self.lock:
            self.runs.append(c.id)
        if self.fail:
            raise RuntimeError("Provider kaputt")
        c.status = DONE
        self.repo.save(c)

    def deliver_pending(self, c):
        with self.lock:
            self.deliveries.append(c.id)


def test_worker_processes_submitted_consultation(repo):
    c = _new()
    repo.save(c)
    worker = ConsultationWorker(repo, rec := Recorder(repo))
    worker.start()
    worker.submit(c.id)
    assert worker.join()
    worker.stop()
    assert rec.runs == [c.id] and repo.get(c.id).status == DONE


def test_double_submit_with_two_threads_runs_once(repo):
    c = _new()
    repo.save(c)
    worker = ConsultationWorker(repo, rec := Recorder(repo), threads=2)
    worker.start()
    for _ in range(5):
        worker.submit(c.id)
    assert worker.join()
    worker.stop()
    assert rec.runs == [c.id]


def test_processor_exception_marks_failed_and_worker_survives(repo):
    bad = _new()
    repo.save(bad)
    rec = Recorder(repo, fail=True)
    worker = ConsultationWorker(repo, rec)
    worker.start()                                         # recover() reiht "bad" ein
    assert worker.join()
    rec.fail = False
    good = _new()
    repo.save(good)
    worker.submit(good.id)
    assert worker.join()
    worker.stop()
    failed = repo.get(bad.id)
    assert failed.status == FAILED and "Provider kaputt" in failed.error and failed.finished_at
    assert repo.get(good.id).status == DONE


def test_recover_after_restart(repo):
    running_with_answer, running_without, queued = _new(), _new(), _new()
    for c in (running_with_answer, running_without, queued):
        repo.save(c)
    repo.claim(running_with_answer.id)
    repo.claim(running_without.id)
    repo.save_delivery(ConsultationDelivery.create(consultation_id=running_with_answer.id,
                                                   participant_id="gpt", message_id="m1"))

    worker = ConsultationWorker(repo, rec := Recorder(repo))
    worker.start()                                         # ruft recover() auf
    assert worker.join()
    worker.stop()

    assert repo.get(running_with_answer.id).status == INTERRUPTED
    assert repo.get(running_without.id).status == INTERRUPTED
    assert rec.deliveries == [running_with_answer.id]     # gespeicherte Antwort wird zugestellt
    assert running_without.id not in rec.runs              # kein automatischer Neuaufruf der Modelle
    assert rec.runs == [queued.id]                         # Wartende werden wieder aufgenommen


def test_recover_ignores_delivered_or_answerless_deliveries(repo):
    c = _new()
    repo.save(c)
    repo.claim(c.id)
    done = ConsultationDelivery.create(consultation_id=c.id, participant_id="gpt", message_id="m1")
    done.status = DELIVERED
    repo.save_delivery(done)
    repo.save_delivery(ConsultationDelivery.create(consultation_id=c.id, participant_id="claude"))  # ohne Antwort
    worker = ConsultationWorker(repo, rec := Recorder(repo))
    worker.start()
    assert worker.join()
    worker.stop()
    assert rec.deliveries == [] and rec.runs == []
    assert PENDING in {d.status for d in repo.list_deliveries(c.id)}


# ── Start im Server ──────────────────────────────────────────────────────

@pytest.mark.parametrize("debug, environ, expected", [
    (False, {}, True),
    (True, {}, False),                                     # Reloader-Elternprozess
    (True, {"WERKZEUG_RUN_MAIN": "true"}, True),           # Kindprozess
])
def test_should_start_workers(debug, environ, expected):
    assert should_start_workers(debug, environ) is expected


def test_start_background_workers_uses_registered_workers():
    worker = MagicMock()
    app = MagicMock(extensions={"conclave_workers": [worker]})
    assert start_background_workers(app, debug=False, environ={}) == [worker]
    worker.start.assert_called_once()
    worker.reset_mock()
    assert start_background_workers(app, debug=True, environ={}) == []
    worker.start.assert_not_called()
    assert start_background_workers(MagicMock(extensions={}), debug=False, environ={}) == []


def test_create_app_does_not_start_workers(repo):
    pytest.importorskip("flask")
    from conclave.api.app import create_app
    with pytest.MonkeyPatch.context() as mp:
        started = []
        mp.setattr(ConsultationWorker, "start", lambda self: started.append(self))
        create_app(MagicMock())
        assert started == []


def test_busy_port_does_not_start_workers():
    """Eine zweite Instanz auf belegtem Port darf laufende Consultations nicht als unterbrochen markieren."""
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    worker = MagicMock()
    app = MagicMock(extensions={"conclave_workers": [worker]})
    try:
        with pytest.raises(SystemExit):
            serve(app, "127.0.0.1", port)
    finally:
        blocker.close()
    worker.start.assert_not_called()
