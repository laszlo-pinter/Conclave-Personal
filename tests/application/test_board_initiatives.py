"""P2 (conclave#57): Vorhaben im Projekt mit eigener Nummer (``projekt/vorhaben-n``).

- ``conclave/sich-3`` und ``conclave#33`` zeigen auf dasselbe Ticket.
- Tickets eines Vorhabens werden lueckenlos fortlaufend nummeriert, auch parallel.
- Vorhaben anlegen, umbenennen, ranken und Tickets zuordnen darf nur der Mensch;
  Agenten lesen und duerfen beim Anlegen ein vorhandenes Vorhaben angeben.
- ``next_task`` sortiert nach Vorhaben-Rang, dann Ticket-Rang.
"""

import sqlite3
import threading

import pytest

from conclave.application.board import BoardError, BoardService, initiative_to_dict, task_to_dict
from conclave.domain.board import parse_any_ref
from conclave.domain.principal import AGENT_PRINCIPAL as AGENT
from conclave.domain.principal import HUMAN_PRINCIPAL as HUMAN
from conclave.domain.principal import REVIEWER_PRINCIPAL as REVIEWER
from conclave.infrastructure.sqlite.board_repository import SQLiteBoardRepository
from conclave.infrastructure.sqlite.connection import ThreadLocalConnection
from conclave.infrastructure.sqlite.schema import initialize_schema


@pytest.fixture
def board(crypto):
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    svc = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True))
    svc.create_project(HUMAN, "conclave", "Conclave")
    return svc


def _forbidden(fn, *args, **kwargs):
    with pytest.raises(BoardError) as e:
        fn(*args, **kwargs)
    assert e.value.status == 403, e.value
    return e.value


# ── Referenzen ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref, parsed", [
    ("conclave#33", ("conclave", None, 33)),
    ("conclave/sich-3", ("conclave", "sich", 3)),
    ("conclave/board-ui-12", ("conclave", "board-ui", 12)),
])
def test_both_reference_forms_parse(ref, parsed):
    assert parse_any_ref(ref) == parsed


@pytest.mark.parametrize("bad", ["conclave/sich", "conclave/sich-0", "conclave/Sich-1", "conclave/-1", "/sich-1",
                                 "conclave/sich-1/2", "conclave#0", "conclave/sich-01"])
def test_invalid_references_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_any_ref(bad)


def test_both_forms_point_to_the_same_ticket(board):
    board.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    for i in range(3):
        board.create_task(HUMAN, "conclave", f"R{i + 1}", initiative="sich")
    task = board.get_task("conclave/sich-3")
    assert task.ref == "conclave#3" and task.initiative_ref == "conclave/sich-3"
    assert board.get_task("conclave#3").id == task.id
    data = task_to_dict(task)
    assert data["ref"] == "conclave#3" and data["initiative"] == "sich" and data["initiative_ref"] == "conclave/sich-3"


def test_tickets_without_initiative_keep_working(board):
    task = board.create_task(HUMAN, "conclave", "ohne")
    assert task.initiative_ref is None and task_to_dict(task)["initiative_ref"] is None
    with pytest.raises(BoardError) as e:
        board.get_task("conclave/sich-1")
    assert e.value.status == 404


# ── Nummern ─────────────────────────────────────────────────────────────────

def test_numbers_per_initiative_are_consecutive(board):
    board.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    board.create_initiative(HUMAN, "conclave", "board", "Board")
    refs = [board.create_task(HUMAN, "conclave", t, initiative=i).initiative_ref
            for t, i in (("a", "sich"), ("b", "board"), ("c", "sich"), ("d", None), ("e", "board"), ("f", "sich"))]
    assert refs == ["conclave/sich-1", "conclave/board-1", "conclave/sich-2", None, "conclave/board-2",
                    "conclave/sich-3"]
    assert [board.get_task(f"conclave#{n}").number for n in range(1, 7)] == [1, 2, 3, 4, 5, 6]


def test_parallel_creates_are_gapless(tmp_path, crypto):
    conn = ThreadLocalConnection(tmp_path / "b.db")
    initialize_schema(conn)
    svc = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True))
    svc.create_project(HUMAN, "conclave", "Conclave")
    svc.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    barrier, errors = threading.Barrier(10), []

    def create(i):
        try:
            barrier.wait()
            for j in range(3):
                svc.create_task(AGENT, "conclave", f"T{i}-{j}", initiative="sich")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=create, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    numbers = sorted(t.initiative_number for t in svc.list_tasks("conclave"))
    assert numbers == list(range(1, 31))


def test_assigning_existing_tickets_numbers_them_in_order(board):
    for title in ("R1", "R2", "R3"):
        board.create_task(HUMAN, "conclave", title)
    board.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    for ref in ("conclave#3", "conclave#1", "conclave#2"):
        board.assign_initiative(HUMAN, ref, "sich")
    assert [board.get_task(f"conclave/sich-{n}").title for n in (1, 2, 3)] == ["R3", "R1", "R2"]
    events = [e for e in board.history("conclave#3") if e.field_name == "initiative"]
    assert [(e.old_value, e.new_value) for e in events] == [(None, "conclave/sich-1")]


def test_moving_a_ticket_gives_it_the_next_number_of_the_new_initiative(board):
    board.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    board.create_initiative(HUMAN, "conclave", "board", "Board")
    board.create_task(HUMAN, "conclave", "a", initiative="sich")
    board.create_task(HUMAN, "conclave", "b", initiative="board")
    moved = board.assign_initiative(HUMAN, "conclave#1", "board")
    assert moved.initiative_ref == "conclave/board-2"
    assert board.assign_initiative(HUMAN, "conclave#1", None).initiative_ref is None
    assert board.create_task(HUMAN, "conclave", "c", initiative="sich").initiative_ref == "conclave/sich-2"


# ── Rechte ──────────────────────────────────────────────────────────────────

def test_agent_cannot_create_rename_rank_or_assign(board):
    _forbidden(board.create_initiative, AGENT, "conclave", "sich", "Sicherheit")
    _forbidden(board.create_initiative, REVIEWER, "conclave", "sich", "Sicherheit")
    board.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    _forbidden(board.update_initiative, AGENT, "conclave", "sich", title="Neu")
    _forbidden(board.update_initiative, AGENT, "conclave", "sich", rank=-5)
    board.create_task(AGENT, "conclave", "T")
    _forbidden(board.assign_initiative, AGENT, "conclave#1", "sich")


def test_agent_can_read_and_create_into_an_existing_initiative(board):
    board.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    assert board.create_task(AGENT, "conclave", "T", initiative="sich").initiative_ref == "conclave/sich-1"
    assert [i.slug for i in board.list_initiatives("conclave")] == ["sich"]
    with pytest.raises(BoardError) as e:
        board.create_task(AGENT, "conclave", "T", initiative="gibtsnicht")
    assert e.value.status == 404


@pytest.mark.parametrize("slug", ["Sich", "-x", "x" * 21, "a_b", "a/b", ""])
def test_invalid_initiative_slugs(board, slug):
    with pytest.raises(BoardError) as e:
        board.create_initiative(HUMAN, "conclave", slug, "X")
    assert e.value.status == 400


def test_duplicate_initiative_is_a_conflict(board):
    board.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    with pytest.raises(BoardError) as e:
        board.create_initiative(HUMAN, "conclave", "sich", "Doppelt")
    assert e.value.status == 409


def test_rename_and_rank_are_recorded(board):
    board.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    ini = board.update_initiative(HUMAN, "conclave", "sich", title="Sicherheit v0.7", rank=-1)
    assert (ini.title, ini.rank) == ("Sicherheit v0.7", -1)
    assert initiative_to_dict(ini)["title"] == "Sicherheit v0.7"
    fields = [e.field_name for e in board.project_history("conclave")]
    assert fields.count("initiative") >= 2                    # angelegt, geaendert


# ── Reihenfolge ─────────────────────────────────────────────────────────────

def test_next_task_sorts_by_initiative_rank_then_ticket_rank(board):
    board.create_initiative(HUMAN, "conclave", "spaeter", "Spaeter", rank=10)
    board.create_initiative(HUMAN, "conclave", "zuerst", "Zuerst", rank=1)
    board.create_task(HUMAN, "conclave", "ohne Vorhaben")
    board.create_task(HUMAN, "conclave", "spaeter-1", initiative="spaeter")
    board.create_task(HUMAN, "conclave", "zuerst-1", initiative="zuerst")
    board.create_task(HUMAN, "conclave", "zuerst-2", initiative="zuerst")
    order = [board.next_task(AGENT, "conclave").title for _ in range(4)]
    assert order == ["zuerst-1", "zuerst-2", "spaeter-1", "ohne Vorhaben"]


def test_next_task_accepts_the_initiative_reference(board):
    board.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    board.create_task(HUMAN, "conclave", "R1", initiative="sich")
    assert board.next_task(AGENT, task="conclave/sich-1").status == "doing"


def test_migration_020_adds_initiatives_to_an_existing_board(crypto):
    """Bestehende DB ohne Vorhaben: Migration 020 legt Tabelle, Spalten und Index an."""
    from conclave.infrastructure.migrations import run_migrations
    conn = sqlite3.connect(":memory:")
    initialize_schema(conn)
    svc = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True))
    svc.create_project(HUMAN, "conclave", "Conclave")
    svc.create_task(HUMAN, "conclave", "alt")
    for statement in ("DROP INDEX idx_board_tasks_initiative", "ALTER TABLE board_tasks DROP COLUMN initiative_number",
                      "ALTER TABLE board_tasks DROP COLUMN initiative_id", "DROP TABLE board_initiatives",
                      "DELETE FROM _migrations WHERE id = '020_board_initiatives'"):
        conn.execute(statement)
    conn.commit()
    assert "020_board_initiatives" in run_migrations(conn, is_postgres=False)
    assert svc.get_task("conclave#1").initiative_ref is None                # altes Ticket ohne Vorhaben
    svc.create_initiative(HUMAN, "conclave", "sich", "Sicherheit")
    assert svc.assign_initiative(HUMAN, "conclave#1", "sich").initiative_ref == "conclave/sich-1"
    index = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'idx_board_tasks_initiative'").fetchone()
    assert index and "UNIQUE" in index[0]


def test_cli_creates_initiatives_and_assigns_in_order(tmp_path, monkeypatch, capsys):
    """Fuer die Migration der vorhandenen Tickets: der Mensch ordnet per CLI zu (Reihenfolge = Nummern)."""
    from conclave.cli.main import run
    monkeypatch.setenv("CONCLAVE_DB_PATH", str(tmp_path / "c.db"))
    from conclave.cli.config import ConclaveConfig
    from conclave.cli.main import _open_board
    board, close = _open_board(ConclaveConfig.from_sources())
    board.create_project(HUMAN, "conclave", "Conclave")
    for title in ("R1", "R2", "R3"):
        board.create_task(HUMAN, "conclave", title)
    close()
    assert run(["board", "initiative", "add", "conclave", "sich", "Sicherheit"]) == 0
    assert run(["board", "initiative", "assign", "conclave", "sich", "conclave#2", "3", "conclave#1"]) == 0
    out = capsys.readouterr().out
    assert "conclave#2 -> conclave/sich-1" in out and "conclave#1 -> conclave/sich-3" in out
    assert run(["board", "initiative", "add", "conclave", "sich", "doppelt"]) == 1
    assert run(["board", "initiative", "list", "conclave"]) == 0
    assert "conclave/sich" in capsys.readouterr().out
