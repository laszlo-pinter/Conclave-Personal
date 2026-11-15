"""R10 (conclave#45): Consultations - atomares Limit, erneute human-Pruefung, Status-Uebergaenge.

- Pruefen und Speichern sind ein Schritt; gezaehlt wird die normalisierte Referenz (ticket.key),
  getrennt fuer Mensch und Agent.
- Wird das Ticket waehrend des Laufs "nur fuer Menschen", gibt es keinen Kommentar (FAILED).
- Im eigenen Board sind "eigene" Kommentare nur solche mit Herkunft system.
- Statuswechsel nur aus dem erwarteten Status; recover() unterbricht nur Laeufe mit
  abgelaufener Lease (anderer Worker oder Neustart).
"""

import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_consultation_service import FakeReviewer, env  # noqa: E402,F401 - Fixture

from conclave.application.consultation_worker import ConsultationWorker  # noqa: E402
from conclave.application.consultations import ConsultationRequestError, ConsultationRequests  # noqa: E402
from conclave.domain.consultation import (  # noqa: E402
    DONE,
    FAILED,
    INTERRUPTED,
    QUEUED,
    RUNNING,
    Consultation,
)
from conclave.domain.principal import AGENT_PRINCIPAL, HUMAN_PRINCIPAL  # noqa: E402
from conclave.domain.ticket import Ticket  # noqa: E402
from conclave.infrastructure.sqlite.connection import ThreadLocalConnection  # noqa: E402
from conclave.infrastructure.sqlite.consultation_repository import SQLiteConsultationRepository  # noqa: E402
from conclave.infrastructure.sqlite.schema import initialize_schema  # noqa: E402


@pytest.fixture
def repo(tmp_path):
    conn = ThreadLocalConnection(tmp_path / "c.db")
    initialize_schema(conn)
    return SQLiteConsultationRepository(conn, autocommit=True)


def _new(ref="api#12", channel="agent"):
    return Consultation.create(source="board", source_ref=ref, question="?", reviewers=["gpt"], channel=channel)


# ── Atomares Limit ──────────────────────────────────────────────────────────

def test_parallel_creates_do_not_exceed_the_limit(repo):
    since = datetime.now(UTC) - timedelta(hours=1)
    results, barrier = [], threading.Barrier(12)

    def attempt():
        barrier.wait()
        results.append(repo.create_if_under_limit(_new(), since, 3))

    threads = [threading.Thread(target=attempt) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 3
    assert repo.count_since("board", "api#12", since, channel="agent") == 3


def test_human_and_agent_have_separate_quotas(repo):
    since = datetime.now(UTC) - timedelta(hours=1)
    for _ in range(2):
        assert repo.create_if_under_limit(_new(channel="agent"), since, 2)
    assert not repo.create_if_under_limit(_new(channel="agent"), since, 2)
    assert repo.create_if_under_limit(_new(channel="human"), since, 2)


class _Source:
    """Normalisiert wie das Board: api#012 und api#12 sind dasselbe Ticket."""

    def get_task(self, ref):
        project, number = ref.split("#")
        return Ticket(key=f"{project}#{int(number)}", title="T", status="todo", human=False)


class _Worker:
    def __init__(self):
        self.submitted = []

    def submit(self, cid):
        self.submitted.append(cid)


def test_limit_counts_the_normalized_reference(repo):
    requests = ConsultationRequests(repo, _Worker(), _Source(), allowed_reviewers=["gpt"], max_per_hour=2,
                                    source="board")
    for ref in ("api#12", "api#012"):
        data = requests.create({"task": ref, "question": "?"}, AGENT_PRINCIPAL)
        assert data["task"] == "api#12"
    with pytest.raises(ConsultationRequestError) as e:
        requests.create({"task": "api#0012", "question": "?"}, AGENT_PRINCIPAL)
    assert e.value.status == 429
    requests.create({"task": "api#12", "question": "?"}, HUMAN_PRINCIPAL)          # eigenes Kontingent


# ── Erneute Pruefung "nur fuer Menschen" ────────────────────────────────────

def _mark_human(env):
    if env.backend == "board":
        env.kanzo.board.update_task(HUMAN_PRINCIPAL, "api#12", human=True)
    else:
        env.kanzo.tasks["api#12"].human = True


def test_ticket_marked_human_during_the_run_gets_no_comment(env, monkeypatch):
    before = list(env.kanzo.tasks["api#12"].comments)
    original = env.svc._ask_reviewers

    def ask_then_mark(c, conversation_id):
        errors = original(c, conversation_id)
        _mark_human(env)                                        # der Mensch markiert waehrend des Laufs
        return errors

    monkeypatch.setattr(env.svc, "_ask_reviewers", ask_then_mark)
    c = env.new(channel="agent")
    env.svc.run(c)
    assert list(env.kanzo.tasks["api#12"].comments) == before
    done = env.repo.get(c.id)
    assert done.status == FAILED and "nur fuer Menschen" in done.error
    assert all(d.status == FAILED for d in env.repo.list_deliveries(c.id))


# ── Eigene Kommentare im Board nur mit Herkunft system ─────────────────────

def test_agent_comment_with_marker_text_stays_in_the_prompt(env):
    if env.backend != "board":
        pytest.skip("nur fuer das eigene Board")
    marker = "consultation 11111111-2222-3333-4444-555555555555/gpt"
    env.kanzo.board.add_comment(AGENT_PRINCIPAL, "api#12", f"Wichtiger Befund · {marker}", author_name="cc")
    env.svc.run(env.new(reviewers=("gpt",)))
    assert "Wichtiger Befund" in env.reviewers["gpt"].prompts[0]


# ── Statusuebergaenge und Lease ─────────────────────────────────────────────

def test_finish_does_not_overwrite_a_status_set_meanwhile(repo):
    c = _new()
    repo.save(c)
    assert repo.claim(c.id, owner="w1", lease_until=datetime.now(UTC) + timedelta(minutes=2))
    running = repo.get(c.id)
    assert repo.transition(running, RUNNING, INTERRUPTED, error="unterbrochen")
    assert not repo.transition(running, RUNNING, DONE)               # alter Stand: kein Ueberschreiben
    assert repo.get(c.id).status == INTERRUPTED


def test_recover_keeps_runs_with_a_live_lease_of_another_worker(repo):
    alive, dead = _new(), _new()
    for c in (alive, dead):
        repo.save(c)
    repo.claim(alive.id, owner="other", lease_until=datetime.now(UTC) + timedelta(minutes=5))
    repo.claim(dead.id, owner="other", lease_until=datetime.now(UTC) - timedelta(seconds=1))

    class Nothing:
        def run(self, c):
            pass

        def deliver_pending(self, c):
            pass

    worker = ConsultationWorker(repo, Nothing())
    worker.recover()
    assert repo.get(alive.id).status == RUNNING
    assert repo.get(dead.id).status == INTERRUPTED


def test_worker_holds_the_lease_while_running(repo, monkeypatch):
    c = _new()
    repo.save(c)
    started, release = threading.Event(), threading.Event()
    leases = []

    class Slow:
        def run(self, consultation):
            started.set()
            release.wait(5)

        def deliver_pending(self, consultation):
            pass

    worker = ConsultationWorker(repo, Slow(), lease_seconds=1.0, heartbeat_seconds=0.2)
    worker.start()
    worker.submit(c.id)
    assert started.wait(5)
    for _ in range(3):
        leases.append(repo.get(c.id).lease_until)
        threading.Event().wait(0.4)
    release.set()
    assert worker.join()
    worker.stop()
    assert leases == sorted(leases) and leases[-1] > leases[0]          # verlaengert, nicht abgelaufen
    assert repo.get(c.id).status == RUNNING                             # Slow beendet nicht selbst


def test_migration_018_adds_the_lease_to_existing_consultations(tmp_path):
    import sqlite3

    from conclave.infrastructure.migrations import MIGRATIONS, run_migrations
    conn = sqlite3.connect(tmp_path / "alt.db")
    for table in ("conversations (id TEXT PRIMARY KEY, status TEXT)", "agents (id TEXT PRIMARY KEY)",
                  "audit_log (id TEXT PRIMARY KEY)", "messages (id TEXT PRIMARY KEY, content TEXT)"):
        conn.execute(f"CREATE TABLE {table}")
    run_migrations(conn, migrations=[m for m in MIGRATIONS if m.id != "018_consultation_lease"])
    old = _new()
    conn.execute("INSERT INTO consultations (id, source, source_ref, question, reviewers_json, channel, mode, "
                 "status, created_at) VALUES (?, 'board', 'api#12', '?', '[\"gpt\"]', 'agent', 'independent', "
                 "'running', ?)", (old.id, datetime.now(UTC).isoformat()))
    conn.commit()
    run_migrations(conn)
    repo = SQLiteConsultationRepository(conn, autocommit=True)
    assert repo.get(old.id).lease_until is None
    assert [c.id for c in repo.list_expired_running(datetime.now(UTC))] == [old.id]   # alte Laeufe gelten als ohne Lease
