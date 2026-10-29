"""Consultations gegen das eigene Board (Plan board.md, B6): ``TaskSource`` und ``CommentSink``.

Antworten aus Consultations schreibt Conclave selbst, daher Herkunft ``system`` -
auch wenn ein Mensch die Consultation angefordert hat. Die Pruefung "nur fuer
Menschen" bleibt im ConsultationService (Kanal aus dem Token).
"""

from __future__ import annotations

from conclave.application.board import BoardError, BoardService
from conclave.domain.board import TaskComment
from conclave.domain.errors import TaskNotFound, TaskSourceError
from conclave.domain.ticket import Ticket, TicketComment

SYSTEM = "system"


def _author(c: TaskComment) -> str:
    """Anzeigename fuer den Prompt. ``Ticket.has_marker`` vergleicht den Autor: Ein fremder
    Kommentar, dessen Name nach Conclave aussieht, bekommt die Herkunft angehaengt und kann
    so keine Zustellung vortaeuschen (in Kanzo ist der Autor faelschbar, hier nicht)."""
    name = c.author_name or (c.origin or "unbekannt")
    if c.origin != SYSTEM and "conclave" in name.casefold():
        return f"{name} [{c.origin or 'unbekannt'}]"
    return name


class BoardTaskSource:
    """``TaskSource`` und ``CommentSink`` auf dem ``BoardService``."""

    def __init__(self, board: BoardService) -> None:
        self._board = board

    def get_task(self, task_ref: str) -> Ticket:
        task = self._call(task_ref, lambda: self._board.get_task(task_ref))
        comments = self._call(task_ref, lambda: self._board.comments(task_ref))
        return Ticket(
            key=task.ref, title=task.title, status=task.status, human=task.human, description=task.description,
            comments=tuple(TicketComment(author=_author(c), time=c.created_at.isoformat() if c.created_at else "",
                                         body=c.body) for c in comments),
        )

    def add_comment(self, task_ref: str, body: str, author: str) -> None:
        self._call(task_ref, lambda: self._board.add_system_comment(task_ref, body, author))

    @staticmethod
    def _call(task_ref: str, action):
        try:
            return action()
        except BoardError as e:
            if e.status == 404:
                raise TaskNotFound(task_ref, str(e)) from None
            if e.type == "ValidationError":
                raise ValueError(str(e)) from None                # wie der Kanzo-Adapter bei falscher Referenz
            raise TaskSourceError(f"Board: {e}") from None
