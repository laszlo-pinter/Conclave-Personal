"""Ticket-Quellen fuer die Consultation-Tests (B6): Fake-Kanzo (MCP) und das eigene Board.

``FakeBoard`` hat dieselbe Oberflaeche wie ``FakeKanzo`` (``add``, ``tasks[key].comments``,
``calls``), damit die bestehenden Tests unveraendert gegen beide Quellen laufen.
"""

import sys
from pathlib import Path

from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "infrastructure" / "kanzo"))

from fake_kanzo import FakeKanzo, FakeTask  # noqa: E402

from conclave.application.board import BoardService  # noqa: E402
from conclave.application.board_consultations import BoardTaskSource  # noqa: E402
from conclave.domain.board import DEFAULT_STATUSES, POSITION_STEP, Project, StatusFlow, Task, TaskComment  # noqa: E402
from conclave.infrastructure.crypto import CryptoService  # noqa: E402
from conclave.infrastructure.kanzo.adapter import KanzoMcpAdapter  # noqa: E402
from conclave.infrastructure.sqlite.board_repository import SQLiteBoardRepository  # noqa: E402

BACKENDS = ["kanzo", "board"]


class _Recording:
    """Zeichnet Aufrufe auf wie FakeKanzo.calls."""

    def __init__(self, inner, calls):
        self._inner, self._calls = inner, calls

    def get_task(self, task_ref):
        self._calls.append(("get_task", {"id": task_ref}))
        return self._inner.get_task(task_ref)

    def add_comment(self, task_ref, body, author):
        self._calls.append(("add_comment", {"id": task_ref, "body": body, "author": author}))
        return self._inner.add_comment(task_ref, body, author)


class _TaskView:
    def __init__(self, board, key):
        self._board, self.key = board, key

    def __getattr__(self, name):                        # status, title, description wie FakeTask
        if name in ("status", "title", "description", "human"):
            return getattr(self._board.get_task(self.key), name)
        raise AttributeError(name)

    @property
    def comments(self):
        return [(c.author_name, c.body) for c in self._board.comments(self.key)]

    @property
    def origins(self):
        return [c.origin for c in self._board.comments(self.key)]


class _Tasks:
    def __init__(self, board):
        self._board = board

    def __getitem__(self, key):
        self._board.get_task(key)                       # BoardError, wenn es das Ticket nicht gibt
        return _TaskView(self._board, key)


class FakeBoard:
    source = "board"

    def __init__(self, conn):
        repo = SQLiteBoardRepository(conn, CryptoService(Fernet.generate_key()), autocommit=True)
        self.board = BoardService(repo, StatusFlow(DEFAULT_STATUSES))
        self.calls = []
        self.adapter = _Recording(BoardTaskSource(self.board), self.calls)
        self.tasks = _Tasks(self.board)

    def add(self, t: FakeTask) -> FakeTask:
        repo = self.board._repo
        project = repo.get_project(t.project)
        if project is None:
            project = Project.create(t.project, t.project.upper())
            repo.create_project(project)
        task = Task.create(project, t.title, t.status, description=t.description, tags=t.tags, human=t.human,
                           position=POSITION_STEP * t.id)
        task.number = t.id
        comments = [TaskComment.create(task.id, body, None, author_name=author) for author, body in t.comments]
        assert repo.import_task(task, comments)
        return t


def make_backend(name, conn):
    """(Fake, Adapter, Quellname) fuer ``kanzo`` oder ``board``."""
    if name == "board":
        fake = FakeBoard(conn)
        return fake, fake.adapter, "board"
    fake = FakeKanzo()
    return fake, KanzoMcpAdapter(fake.server), "kanzo"
