"""Board-Dienst: Regeln fuer Mensch und Agent, Verlauf, next_task (Plan board.md, B2).

Rechte (Plan, Abschnitt 3). "Freigabe-Recht" ist eine eigene Pruefung
(``can_approve``), heute gleichbedeutend mit "Mensch", spaeter eine Rolle im Projekt.

- Lesen, Verlauf, ``next_task``: Mensch und Agent.
- Anlegen, bearbeiten, kommentieren: beide; Agenten aber nicht bei Tickets
  "nur fuer Menschen" (die duerfen sie nur lesen).
- Status: Agenten nicht in die letzte Spalte und nicht aus ihr heraus. Tickets in der
  letzten Spalte sind fuer Agenten nur lesbar und kommentierbar (Entscheidung Laszlo,
  29.10.2026): mit "erledigt" hat der Mensch entschieden.
- Markierung "nur fuer Menschen": Agenten duerfen sie setzen, nicht entfernen.
- Kommentare: nur eigene Kommentare des Menschen sind aenderbar; Kommentare von
  Agenten und von Conclave (``system``) sind unveraenderlich.
- Projekte anlegen/umbenennen/loeschen und Tickets loeschen: nur mit Freigabe-Recht.

Geschrieben wird optimistisch (Versionsnummer): Hat seit dem Lesen jemand das Ticket
geaendert, gilt die Pruefung nicht mehr fuer den neuen Stand -> 409 statt Ueberschreiben.
``next_task`` claimt nur Tickets ohne Markierung, gepruefter Zustand und Schreiben sind eins.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from conclave.application.ports import BoardRepository
from conclave.domain.board import POSITION_STEP, Project, StatusFlow, Task, TaskComment, TaskEvent, parse_ref
from conclave.domain.errors import ConclaveError
from conclave.domain.principal import Principal

# Unterschreitet der Abstand zweier Nachbarn diese Grenze, wird die Spalte neu nummeriert.
MIN_POSITION_GAP = 1e-6
SYSTEM_ACTOR = "conclave"


class BoardError(ConclaveError):
    """Fehler fuer API und MCP; ``status`` ist der HTTP-Status, ``type`` der Fehlertyp."""

    def __init__(self, message: str, status: int, error_type: str):
        self.status, self.type = status, error_type
        super().__init__(message)


def _forbidden(message: str) -> BoardError:
    return BoardError(message, 403, "HumanOnly")


def _invalid(message: str) -> BoardError:
    return BoardError(message, 400, "ValidationError")


class BoardService:
    def __init__(self, repository: BoardRepository, flow: StatusFlow | None = None,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._repo = repository
        self.flow = flow or StatusFlow()
        self._now = now

    # ── Wer handelt ──────────────────────────────────────────────────────

    @staticmethod
    def actor(principal: Principal) -> tuple[str, str]:
        """(origin, actor_id); actor_id bereitet den Mehrbenutzerbetrieb vor."""
        return principal.role, principal.role

    @staticmethod
    def can_approve(principal: Principal, project: Project | None = None) -> bool:
        return principal.is_human

    def _require_approval(self, principal: Principal, project: Project | None = None) -> None:
        if not self.can_approve(principal, project):
            raise _forbidden("Nur mit Freigabe-Recht (heute: Mensch).")

    # ── Projekte ─────────────────────────────────────────────────────────

    def list_projects(self) -> list[Project]:
        return self._repo.list_projects()

    def _project(self, slug: str) -> Project:
        project = self._repo.get_project(slug)
        if project is None:
            raise BoardError(f"Projekt '{slug}' nicht gefunden.", 404, "ProjectNotFound")
        return project

    def create_project(self, principal: Principal, slug: str, name: str) -> Project:
        self._require_approval(principal)
        try:
            project = Project.create(slug, name)
        except ValueError as e:
            raise _invalid(str(e)) from None
        if self._repo.get_project(slug) is not None:
            raise BoardError(f"Projekt '{slug}' gibt es schon.", 409, "ProjectExists")
        self._repo.create_project(project)
        return project

    def rename_project(self, principal: Principal, slug: str, name: str) -> Project:
        project = self._project(slug)
        self._require_approval(principal, project)
        if not isinstance(name, str) or not name.strip():
            raise _invalid("Projektname darf nicht leer sein.")
        self._repo.rename_project(slug, name)
        return self._project(slug)

    def delete_project(self, principal: Principal, slug: str) -> None:
        project = self._project(slug)
        self._require_approval(principal, project)
        self._repo.delete_project(slug)

    # ── Tickets lesen ────────────────────────────────────────────────────

    def get_task(self, ref: str) -> Task:
        try:
            slug, number = parse_ref(ref)
        except ValueError as e:
            raise _invalid(str(e)) from None
        task = self._repo.get_task(slug, number)
        if task is None:
            raise BoardError(f"Ticket '{ref}' nicht gefunden.", 404, "TaskNotFound")
        return task

    def _sort_key(self, task: Task):
        order = {s: i for i, s in enumerate(self.flow.statuses)}
        return (task.project_slug, order.get(task.status, len(order)), task.position, task.number)

    def list_tasks(self, slug: str | None = None, statuses=None, include_done: bool = False) -> list[Task]:
        """In Board-Reihenfolge (Spalten wie konfiguriert); erledigte nur auf Wunsch."""
        if slug is not None:
            self._project(slug)
        if statuses is None:
            statuses = [s for s in self.flow.statuses if include_done or s != self.flow.last]
        else:
            statuses = [self.flow_check(s) for s in statuses]
        return sorted(self._repo.list_tasks(slug, statuses), key=self._sort_key)

    def flow_check(self, status: str) -> str:
        try:
            return self.flow.check(status)
        except ValueError as e:
            raise _invalid(str(e)) from None

    def comments(self, ref: str) -> list[TaskComment]:
        return self._repo.list_comments(self.get_task(ref).id)

    def history(self, ref: str) -> list[TaskEvent]:
        return self._repo.list_events(self.get_task(ref).id)

    def change_token(self) -> int:
        return self._repo.change_token()

    def search(self, query: str, slug: str | None = None, include_done: bool = True) -> list[Task]:
        """Suche in Titel, Tags, Beschreibung und Kommentaren (im Speicher, Inhalte sind verschluesselt)."""
        needle = (query or "").strip().casefold()
        if not needle:
            raise _invalid("Suchbegriff darf nicht leer sein.")
        hits = []
        for task in self.list_tasks(slug, include_done=include_done):
            haystack = [task.title, task.description, *task.tags]
            if any(needle in text.casefold() for text in haystack) or any(
                    needle in c.body.casefold() for c in self._repo.list_comments(task.id)):
                hits.append(task)
        return hits

    # ── Positionen ───────────────────────────────────────────────────────

    def _end_position(self, project_id: str, status: str) -> float:
        column = self._repo.column_positions(project_id, status)
        return (column[-1][1] + POSITION_STEP) if column else POSITION_STEP

    def _position_at(self, task: Task, status: str, index: int) -> float:
        """Position fuer ``index`` in der Spalte (ohne das Ticket selbst); nummeriert neu,
        wenn zwischen den Nachbarn kein Platz mehr ist."""
        for attempt in range(2):
            column = [pos for tid, pos in self._repo.column_positions(task.project_id, status) if tid != task.id]
            index = max(0, min(index, len(column)))
            low = column[index - 1] if index > 0 else 0.0
            high = column[index] if index < len(column) else low + 2 * POSITION_STEP
            middle = (low + high) / 2
            if high - low >= MIN_POSITION_GAP and low < middle < high:
                return middle
            if attempt == 0:
                self._repo.renumber_column(task.project_id, status)
        raise BoardError("Position konnte nicht bestimmt werden.", 409, "PositionConflict")

    # ── Tickets schreiben ────────────────────────────────────────────────

    def _guard_write(self, principal: Principal, task: Task) -> None:
        if principal.is_agent and task.human:
            raise _forbidden("Ticket ist nur fuer Menschen: Agenten duerfen es nur lesen.")

    def _guard_edit(self, principal: Principal, task: Task) -> None:
        """Wie _guard_write, dazu: erledigte Tickets aendern Agenten nicht (kommentieren schon)."""
        self._guard_write(principal, task)
        if principal.is_agent and task.status == self.flow.last:
            raise _forbidden("Erledigte Tickets duerfen Agenten nur lesen und kommentieren.")

    def create_task(self, principal: Principal, slug: str, title: str, *, description: str = "", tags=(),
                    human: bool = False, status: str | None = None) -> Task:
        project = self._project(slug)
        status = self.flow_check(status) if status is not None else self.flow.first
        if principal.is_agent and status == self.flow.last:
            raise _forbidden("Agenten legen keine erledigten Tickets an.")
        try:
            task = Task.create(project, title, status, description=description or "", tags=tuple(tags or ()),
                               position=self._end_position(project.id, status), human=bool(human))
        except (ValueError, TypeError) as e:
            raise _invalid(str(e)) from None
        return self._repo.create_task(task)

    def update_task(self, principal: Principal, ref: str, *, title: str | None = None,
                    description: str | None = None, tags=None, status: str | None = None,
                    human: bool | None = None, index: int | None = None) -> Task:
        """Aendert die uebergebenen Felder. ``index`` setzt die Position in der (neuen) Spalte."""
        task = self.get_task(ref)
        self._guard_edit(principal, task)
        origin, actor_id = self.actor(principal)
        events: list[TaskEvent] = []

        if status is not None:
            status = self.flow_check(status)
            if principal.is_agent and status != task.status and self.flow.last in (status, task.status):
                raise _forbidden("Nach und aus der letzten Spalte schiebt nur, wer das Freigabe-Recht hat.")
        if human is not None:
            human = bool(human)
            if principal.is_agent and task.human and not human:
                raise _forbidden("Agenten duerfen die Markierung 'nur fuer Menschen' nicht entfernen.")
        if title is not None and (not isinstance(title, str) or not title.strip()):
            raise _invalid("Titel darf nicht leer sein.")

        for name, new in (("title", title), ("description", description), ("status", status), ("human", human)):
            old = getattr(task, name)
            if new is not None and new != old:
                events.append(TaskEvent.create(task.id, name, old, new, origin, actor_id=actor_id))
                setattr(task, name, new)
        if tags is not None:
            task.tags = tuple(dict.fromkeys(t.strip() for t in tags if isinstance(t, str) and t.strip()))

        moved_column = any(e.field_name == "status" for e in events)
        if index is not None:
            task.position = self._position_at(task, task.status, int(index))
        elif moved_column:
            task.position = self._end_position(task.project_id, task.status)
        task.updated_at = self._now()
        # Ticket und Verlauf zusammen, nur wenn seit dem Lesen niemand geaendert hat
        if not self._repo.update_task(task, events):
            if self._repo.get_task_by_id(task.id) is None:
                raise BoardError(f"Ticket '{ref}' nicht gefunden.", 404, "TaskNotFound")
            raise BoardError(f"Ticket '{ref}' wurde inzwischen geaendert; bitte neu laden.", 409, "Conflict")
        return task

    def delete_task(self, principal: Principal, ref: str) -> None:
        self._require_approval(principal)
        task = self.get_task(ref)
        self._repo.delete_task(task.id)

    # ── next_task ────────────────────────────────────────────────────────

    def next_task(self, principal: Principal, slug: str | None = None) -> Task | None:
        """Oberstes Ticket der ersten Spalte (ohne 'nur fuer Menschen') atomar in die zweite."""
        first, second = self.flow.first, self.flow.second
        origin, actor_id = self.actor(principal)
        for candidate in self.list_tasks(slug, [first]):
            if candidate.human:
                continue
            position = self._end_position(candidate.project_id, second)
            event = TaskEvent.create(candidate.id, "status", first, second, origin, actor_id=actor_id)
            if self._repo.claim_task(candidate.id, first, second, position, self._now(), event):
                return self._repo.get_task_by_id(candidate.id)
        return None

    # ── Kommentare ───────────────────────────────────────────────────────

    def add_comment(self, principal: Principal, ref: str, body: str, author_name: str = "") -> TaskComment:
        task = self.get_task(ref)
        self._guard_write(principal, task)
        origin, actor_id = self.actor(principal)
        # Agenten: die Markierung wird beim Schreiben erneut geprueft (sie kann inzwischen gesetzt sein)
        return self._save_comment(task, body, origin, actor_id, author_name, only_if_not_human=principal.is_agent)

    def add_system_comment(self, ref: str, body: str, author_name: str) -> TaskComment:
        """Von Conclave selbst geschrieben (z. B. Consultations): Herkunft ``system``."""
        return self._save_comment(self.get_task(ref), body, "system", SYSTEM_ACTOR, author_name)

    def _save_comment(self, task: Task, body: str, origin, actor_id, author_name: str, *,
                      only_if_not_human: bool = False) -> TaskComment:
        if not isinstance(body, str) or not body.strip():
            raise _invalid("Kommentar darf nicht leer sein.")
        comment = TaskComment.create(task.id, body, origin, actor_id=actor_id, author_name=str(author_name or "")[:100])
        if not self._repo.add_comment_checked(comment, only_if_not_human=only_if_not_human):
            if self._repo.get_task_by_id(task.id) is None:
                raise BoardError(f"Ticket '{task.ref}' nicht gefunden.", 404, "TaskNotFound")
            raise _forbidden("Ticket ist nur fuer Menschen: Agenten duerfen es nur lesen.")
        return comment

    def _own_comment(self, principal: Principal, comment_id: str) -> TaskComment:
        comment = self._repo.get_comment(comment_id)
        if comment is None:
            raise BoardError("Kommentar nicht gefunden.", 404, "CommentNotFound")
        if not principal.is_human or comment.origin != "human":
            raise _forbidden("Nur eigene Kommentare des Menschen sind aenderbar; "
                             "Kommentare von Agenten und Conclave sind unveraenderlich.")
        return comment

    def edit_comment(self, principal: Principal, comment_id: str, body: str) -> TaskComment:
        comment = self._own_comment(principal, comment_id)
        if not isinstance(body, str) or not body.strip():
            raise _invalid("Kommentar darf nicht leer sein.")
        comment.body, comment.updated_at = body, self._now()
        self._repo.update_comment(comment)
        return comment

    def delete_comment(self, principal: Principal, comment_id: str) -> None:
        self._own_comment(principal, comment_id)
        self._repo.delete_comment(comment_id)
