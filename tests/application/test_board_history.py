"""R9 (conclave#44): Board - Herkunft beim Anlegen, vollstaendiger Verlauf.

- Tickets tragen Herkunft (origin, actor_id, created_by); Anlegen ist ein Verlaufseintrag.
- Tags, Position und Kommentar-Aenderungen stehen im Verlauf; geloeschte Kommentare bleiben
  als Eintrag erhalten (Soft-Delete).
- Projekt-Verlauf: Anlegen, Umbenennen, geloeschte Tickets (Tombstone).
- PATCH mit veralteter Version -> 409.
- Agenten legen Tickets nur in der ersten Spalte an.
- Wird die letzte Spalte umbenannt, ziehen erledigte Tickets mit.
"""

import sqlite3

import pytest

from conclave.application.board import BoardError, BoardService
from conclave.domain.board import StatusFlow
from conclave.domain.principal import AGENT_PRINCIPAL as AGENT
from conclave.domain.principal import HUMAN_PRINCIPAL as HUMAN
from conclave.infrastructure.sqlite.board_repository import SQLiteBoardRepository
from conclave.infrastructure.sqlite.schema import initialize_schema


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    initialize_schema(connection)
    return connection


@pytest.fixture
def board(conn, crypto):
    svc = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True))
    svc.create_project(HUMAN, "api", "API")
    return svc


def _events(board, ref):
    return [(e.field_name, e.old_value, e.new_value, e.origin) for e in board.history(ref)]


# ── Herkunft beim Anlegen ───────────────────────────────────────────────────

def test_task_records_who_created_it(board):
    board.create_task(AGENT, "api", "Vom Agenten")
    board.create_task(HUMAN, "api", "Vom Menschen")
    agent_task, human_task = board.get_task("api#1"), board.get_task("api#2")
    assert (agent_task.origin, agent_task.actor_id, agent_task.created_by) == ("agent", "agent", "agent")
    assert (human_task.origin, human_task.created_by) == ("human", "human")
    assert _events(board, "api#1") == [("created", None, "todo", "agent")]


def test_task_dict_shows_origin(board):
    from conclave.application.board import task_to_dict
    board.create_task(AGENT, "api", "Vom Agenten")
    data = task_to_dict(board.get_task("api#1"))
    assert (data["origin"], data["created_by"]) == ("agent", "agent")


def test_imported_tasks_have_a_created_event_from_the_importer(board, board_sample_export):
    board.import_export(HUMAN, board_sample_export)
    events = _events(board, "conclave#7")
    assert events[0] == ("created", None, "import", "human")
    task = board.get_task("conclave#7")
    assert task.origin is None and task.created_by == "import"


# ── Verlauf: Tags, Position, Kommentare ─────────────────────────────────────

def test_tags_and_position_changes_are_recorded(board):
    for title in ("A", "B", "C"):
        board.create_task(HUMAN, "api", title)
    for ref in ("api#1", "api#2", "api#3"):
        board.update_task(HUMAN, ref, status="doing")
    board.update_task(HUMAN, "api#1", tags=["ui", "b5"])
    board.update_task(HUMAN, "api#3", index=0)
    fields = [e[0] for e in _events(board, "api#1")]
    assert "tags" in fields
    tag_event = next(e for e in _events(board, "api#1") if e[0] == "tags")
    assert tag_event[1:] == ("[]", '["ui", "b5"]', "human")
    assert "position" in [e[0] for e in _events(board, "api#3")]


def test_editing_and_deleting_a_comment_is_recorded_and_kept(board):
    board.create_task(HUMAN, "api", "T")
    comment = board.add_comment(HUMAN, "api#1", "Erste Fassung")
    board.edit_comment(HUMAN, comment.id, "Zweite Fassung")
    board.delete_comment(HUMAN, comment.id)
    assert board.comments("api#1") == []
    comment_events = [e for e in _events(board, "api#1") if e[0] == "comment"]
    assert comment_events == [("comment", "Erste Fassung", "Zweite Fassung", "human"),
                              ("comment", "Zweite Fassung", None, "human")]
    with pytest.raises(BoardError) as e:
        board.edit_comment(HUMAN, comment.id, "wieder da?")
    assert e.value.status == 404


# ── Projekt-Verlauf ─────────────────────────────────────────────────────────

def test_project_history_records_creation_rename_and_deleted_tasks(board):
    board.rename_project(HUMAN, "api", "API-Server")
    board.create_task(AGENT, "api", "Wird geloescht")
    board.delete_task(HUMAN, "api#1")
    events = [(e.field_name, e.old_value, e.new_value, e.origin) for e in board.project_history("api")]
    assert events[0] == ("created", None, "API", "human")
    assert events[1] == ("name", "API", "API-Server", "human")
    assert events[2][0] == "task_deleted" and events[2][3] == "human"
    assert "api#1" in events[2][1] and "Wird geloescht" in events[2][1]


# ── Version ─────────────────────────────────────────────────────────────────

def test_update_with_stale_version_is_a_conflict(board):
    task = board.create_task(HUMAN, "api", "T")
    version = task.version
    board.update_task(HUMAN, "api#1", title="Neu", version=version)
    with pytest.raises(BoardError) as e:
        board.update_task(HUMAN, "api#1", title="Ueberschrieben", version=version)
    assert (e.value.status, e.value.type) == (409, "Conflict")
    assert board.get_task("api#1").title == "Neu"


def test_update_rejects_a_non_integer_version(board):
    board.create_task(HUMAN, "api", "T")
    with pytest.raises(BoardError) as e:
        board.update_task(HUMAN, "api#1", title="X", version="1")
    assert e.value.status == 400


# ── Agenten nur in die erste Spalte ─────────────────────────────────────────

@pytest.mark.parametrize("status", ["doing", "review"])
def test_agent_creates_tickets_only_in_the_first_column(board, status):
    with pytest.raises(BoardError) as e:
        board.create_task(AGENT, "api", "Gleich in Arbeit", status=status)
    assert e.value.status == 403
    assert board.list_tasks("api", include_done=True) == []
    assert board.create_task(HUMAN, "api", "Mensch darf", status=status).status == status


# ── Umbenannte letzte Spalte ────────────────────────────────────────────────

def test_renaming_the_last_column_moves_finished_tickets(conn, crypto):
    old = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True))
    old.sync_flow()
    old.create_project(HUMAN, "api", "API")
    old.create_task(HUMAN, "api", "Fertig")
    old.update_task(HUMAN, "api#1", status="done")

    new = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True),
                       StatusFlow(("todo", "doing", "review", "erledigt")))
    assert new.sync_flow() == 1
    task = new.get_task("api#1")
    assert task.status == "erledigt"
    assert _events(new, "api#1")[-1] == ("status", "done", "erledigt", "system")
    assert new.list_tasks("api") == []                          # gilt weiter als erledigt
    assert new.sync_flow() == 0                                  # nur einmal


def test_adding_a_column_after_done_does_not_move_tickets(conn, crypto):
    old = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True))
    old.sync_flow()
    old.create_project(HUMAN, "api", "API")
    old.create_task(HUMAN, "api", "Fertig")
    old.update_task(HUMAN, "api#1", status="done")
    new = BoardService(SQLiteBoardRepository(conn, crypto, autocommit=True),
                       StatusFlow(("todo", "doing", "review", "done", "archiv")))
    assert new.sync_flow() == 0
    assert new.get_task("api#1").status == "done"
