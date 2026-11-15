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
- Reviewer (P3): liest, kommentiert und setzt als einziger den Review-Status; anlegen,
  aendern, verschieben und uebernehmen darf er nicht. Gelb (rework) und rot (failed)
  schieben das Ticket zurueck in die erste Spalte, dort steht Nacharbeit vor dem Rang;
  drei rote in Folge machen es "nur fuer Menschen" (E-R3).
- Steuertickets (P6, kind=control): legt nur der Mensch an, aendert und schliesst sie. Eine offene
  Pause haelt next_task an (409 Paused mit der Pause), ein Hinweis bleibt in control_state, bis ein
  Agent ihn per Kommentar quittiert. Steuertickets werden nie per next_task vergeben.
- Anlegen: Agenten nur in die erste Spalte. Jedes Ticket traegt seine Herkunft; Anlegen,
  Tags, Position und Kommentar-Aenderungen stehen im Verlauf, Projekt-Aenderungen und
  geloeschte Tickets im Projekt-Verlauf (R9).

Geschrieben wird optimistisch (Versionsnummer): Hat seit dem Lesen jemand das Ticket
geaendert, gilt die Pruefung nicht mehr fuer den neuen Stand -> 409 statt Ueberschreiben.
``next_task`` claimt nur Tickets ohne Markierung, gepruefter Zustand und Schreiben sind eins.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Callable

from conclave.application.ports import BoardRepository
from conclave.domain.board import (
    CONTROL_SCOPES,
    CONTROL_TYPES,
    KINDS,
    POSITION_STEP,
    RED_LIMIT,
    REVIEW_RESULTS,
    Project,
    ProjectEvent,
    StatusFlow,
    Task,
    TaskComment,
    TaskEvent,
    check_field_limits,
    parse_ref,
)
from conclave.domain.errors import ConclaveError
from conclave.domain.principal import Principal

# Unterschreitet der Abstand zweier Nachbarn diese Grenze, wird die Spalte neu nummeriert.
MIN_POSITION_GAP = 1e-6
SYSTEM_ACTOR = "conclave"
LAST_STATUS_KEY = "last_status"
REWORK_STATES = ("rework", "failed")
CHECKED_MAX = 200


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
        origin, actor_id = self.actor(principal)
        self._repo.create_project(project, ProjectEvent.create(project.id, "created", None, project.name, origin,
                                                               actor_id=actor_id))
        return project

    def rename_project(self, principal: Principal, slug: str, name: str) -> Project:
        project = self._project(slug)
        self._require_approval(principal, project)
        if not isinstance(name, str) or not name.strip():
            raise _invalid("Projektname darf nicht leer sein.")
        if name != project.name:
            origin, actor_id = self.actor(principal)
            self._repo.rename_project(slug, name, ProjectEvent.create(project.id, "name", project.name, name, origin,
                                                                      actor_id=actor_id))
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
        """Erste Spalte: Nacharbeit aus dem Review zuerst (P3), dann Prioritaet (rank, P1);
        die anderen Spalten nach Arbeitsstand (position)."""
        order = {s: i for i, s in enumerate(self.flow.statuses)}
        if task.status == self.flow.first:
            place = (0 if task.review_state in REWORK_STATES else 1, task.rank)
        else:
            place = (1, task.position)
        return (task.project_slug, order.get(task.status, len(order)), place, task.number)

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

    def project_history(self, slug: str) -> list[ProjectEvent]:
        return self._repo.list_project_events(self._project(slug).id)

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

    def _next_rank(self, project_id: str) -> float:
        """Neue Tickets ans Ende der Prioritaet: die Reihenfolge des Plans bleibt erhalten (P1)."""
        return self._repo.max_rank(project_id) + POSITION_STEP

    def _rank_at(self, task: Task, index: int) -> float:
        """Rang fuer ``index`` in der ersten Spalte (ohne das Ticket selbst); nummeriert die Raenge
        des Projekts neu, wenn zwischen den Nachbarn kein Platz mehr ist."""
        for attempt in range(2):
            ranks = sorted(t.rank for t in self.list_tasks(task.project_slug, [self.flow.first]) if t.id != task.id)
            index = max(0, min(index, len(ranks)))
            low = ranks[index - 1] if index > 0 else (ranks[0] - 2 * POSITION_STEP if ranks else 0.0)
            high = ranks[index] if index < len(ranks) else low + 2 * POSITION_STEP
            middle = (low + high) / 2
            if high - low >= MIN_POSITION_GAP and low < middle < high:
                return middle
            if attempt == 0:
                self._repo.renumber_ranks(task.project_id)
                task.rank = self._repo.get_task_by_id(task.id).rank
        raise BoardError("Prioritaet konnte nicht bestimmt werden.", 409, "PositionConflict")

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

    @staticmethod
    def _no_reviewer(principal: Principal, what: str) -> None:
        if principal.is_reviewer:
            raise _forbidden(f"Der Reviewer-Zugang darf nur lesen, kommentieren und den Review-Status setzen "
                             f"({what} nicht).")

    def _guard_write(self, principal: Principal, task: Task) -> None:
        if principal.is_agent and task.human:
            raise _forbidden("Ticket ist nur fuer Menschen: Agenten duerfen es nur lesen.")

    def _guard_edit(self, principal: Principal, task: Task) -> None:
        """Wie _guard_write, dazu: erledigte Tickets aendern Agenten nicht (kommentieren schon)."""
        self._guard_write(principal, task)
        if principal.is_agent and task.status == self.flow.last:
            raise _forbidden("Erledigte Tickets duerfen Agenten nur lesen und kommentieren.")
        if principal.is_agent and task.kind == "control":
            raise _forbidden("Steuertickets aendert und schliesst nur der Mensch; Agenten kommentieren sie.")

    def create_task(self, principal: Principal, slug: str, title: str, *, description: str = "", tags=(),
                    human: bool = False, status: str | None = None, kind: str = "task",
                    control: str | None = None, scope: str = "project") -> Task:
        self._no_reviewer(principal, "anlegen")
        if kind not in KINDS:
            raise _invalid(f"kind muss einer von {KINDS} sein.")
        if kind == "control":
            if not principal.is_human:
                raise _forbidden("Steuertickets legt nur der Mensch an.")
            if control not in CONTROL_TYPES:
                raise _invalid(f"control muss einer von {CONTROL_TYPES} sein.")
            if scope not in CONTROL_SCOPES:
                raise _invalid(f"scope muss einer von {CONTROL_SCOPES} sein.")
            status = None                               # offen = erste Spalte; geschlossen wird nach "erledigt"
        elif control is not None:
            raise _invalid("control gibt es nur bei kind=control.")
        project = self._project(slug)
        status = self.flow_check(status) if status is not None else self.flow.first
        if principal.is_agent and status != self.flow.first:
            raise _forbidden(f"Agenten legen Tickets nur in '{self.flow.first}' an; "
                             "weiter geht es ueber next_task.")
        origin, actor_id = self.actor(principal)
        try:
            check_field_limits(title=title, text=description, tags=tags)
            task = Task.create(project, title, status, description=description or "", tags=tuple(tags or ()),
                               position=self._end_position(project.id, status), human=bool(human),
                               rank=self._next_rank(project.id))
        except (ValueError, TypeError) as e:
            raise _invalid(str(e)) from None
        task.origin, task.actor_id, task.created_by = origin, actor_id, actor_id
        if kind == "control":
            task.kind, task.control, task.control_scope = kind, control, scope
        event = TaskEvent.create(task.id, "created", None, status, origin, actor_id=actor_id)
        return self._repo.create_task(task, event)

    def update_task(self, principal: Principal, ref: str, *, title: str | None = None,
                    description: str | None = None, tags=None, status: str | None = None,
                    human: bool | None = None, index: int | None = None, rank: float | None = None,
                    version: int | None = None) -> Task:
        """Aendert die uebergebenen Felder. ``index`` setzt den Platz in der (neuen) Spalte: in der
        ersten Spalte ist das die Prioritaet (rank), sonst die Position. Prioritaet aendert nur der
        Mensch (P1). ``version``: nur aendern, wenn das Ticket noch diese Version hat (R9)."""
        self._no_reviewer(principal, "Tickets aendern")
        if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
            raise _invalid("version muss eine ganze Zahl sein.")
        task = self.get_task(ref)
        if version is not None and version != task.version:
            raise BoardError(f"Ticket '{ref}' hat inzwischen Version {task.version} (erwartet {version}); "
                             "bitte neu laden.", 409, "Conflict")
        self._guard_edit(principal, task)
        if principal.is_agent and (index is not None or rank is not None):
            raise _forbidden("Die Prioritaet setzt nur der Mensch (bzw. der Plan); Agenten sortieren nicht um.")
        if rank is not None and (isinstance(rank, bool) or not isinstance(rank, (int, float))
                                 or rank != rank or rank in (float("inf"), float("-inf"))):
            raise _invalid("rank muss eine Zahl sein.")
        origin, actor_id = self.actor(principal)
        events: list[TaskEvent] = []

        if status is not None:
            status = self.flow_check(status)
            if principal.is_agent and status != task.status and self.flow.last in (status, task.status):
                raise _forbidden("Nach und aus der letzten Spalte schiebt nur, wer das Freigabe-Recht hat.")
            # Agenten uebernehmen ein Ticket sichtbar und atomar, statt "doing" zu ueberspringen (#51)
            if principal.is_agent and status != task.status and task.status == self.flow.first:
                raise _forbidden(f"Erst uebernehmen: conclave_board_next(task=\"{task.ref}\") "
                                 "bzw. POST /board/next mit task.")
        if human is not None:
            human = bool(human)
            if principal.is_agent and task.human and not human:
                raise _forbidden("Agenten duerfen die Markierung 'nur fuer Menschen' nicht entfernen.")
            # Gibt der Mensch ein Ticket frei (z. B. nach drei roten Reviews), zaehlt Rot neu (E-R3)
            if task.human and not human and task.review_red_count:
                events.append(TaskEvent.create(task.id, "review_red_count", task.review_red_count, 0, origin,
                                               actor_id=actor_id))
                task.review_red_count = 0
        if title is not None and (not isinstance(title, str) or not title.strip()):
            raise _invalid("Titel darf nicht leer sein.")
        try:
            check_field_limits(title=title, text=description, tags=tags)
        except (ValueError, TypeError) as e:
            raise _invalid(str(e)) from None

        for name, new in (("title", title), ("description", description), ("status", status), ("human", human)):
            old = getattr(task, name)
            if new is not None and new != old:
                events.append(TaskEvent.create(task.id, name, old, new, origin, actor_id=actor_id))
                setattr(task, name, new)
        if tags is not None:
            new_tags = tuple(dict.fromkeys(t.strip() for t in tags if isinstance(t, str) and t.strip()))
            if new_tags != task.tags:
                events.append(TaskEvent.create(task.id, "tags", _tags_value(task.tags), _tags_value(new_tags),
                                               origin, actor_id=actor_id))
                task.tags = new_tags

        moved_column = any(e.field_name == "status" for e in events)
        new_rank = float(rank) if rank is not None else None
        if index is not None and task.status == self.flow.first:
            new_rank = self._rank_at(task, int(index))
        elif index is not None:
            new_position = self._position_at(task, task.status, int(index))
            if new_position != task.position and not moved_column:
                events.append(TaskEvent.create(task.id, "position", task.position, new_position, origin,
                                               actor_id=actor_id))
            task.position = new_position
        if moved_column and not (index is not None and task.status != self.flow.first):
            task.position = self._end_position(task.project_id, task.status)
        if new_rank is not None and new_rank != task.rank:
            events.append(TaskEvent.create(task.id, "rank", task.rank, new_rank, origin, actor_id=actor_id))
            task.rank = new_rank
        if moved_column and task.status == self.flow.review:
            self._reset_review(task, events)            # neue Runde: Ergebnis der letzten gilt nicht mehr
        task.updated_at = self._now()
        # Ticket und Verlauf zusammen, nur wenn seit dem Lesen niemand geaendert hat
        if not self._repo.update_task(task, events):
            if self._repo.get_task_by_id(task.id) is None:
                raise BoardError(f"Ticket '{ref}' nicht gefunden.", 404, "TaskNotFound")
            raise BoardError(f"Ticket '{ref}' wurde inzwischen geaendert; bitte neu laden.", 409, "Conflict")
        return task

    def delete_task(self, principal: Principal, ref: str) -> None:
        """Loescht Ticket samt Kommentaren und Verlauf; im Projekt-Verlauf bleibt ein Eintrag."""
        self._require_approval(principal)
        task = self.get_task(ref)
        origin, actor_id = self.actor(principal)
        tombstone = ProjectEvent.create(task.project_id, "task_deleted", f"{task.ref}: {task.title} ({task.status})",
                                        None, origin, actor_id=actor_id)
        self._repo.delete_task(task.id, tombstone)

    # ── next_task ────────────────────────────────────────────────────────

    def next_task(self, principal: Principal, slug: str | None = None, task: str | None = None) -> Task | None:
        """Oberstes Ticket der ersten Spalte (ohne 'nur fuer Menschen') atomar in die zweite;
        mit ``task`` genau dieses Ticket (conclave#51).

        Ist die zweite Spalte zugleich die letzte (zwei Spalten), waere das ein Schritt nach
        "erledigt"; der braucht das Freigabe-Recht wie jede andere Bewegung dorthin (R4).
        """
        self._no_reviewer(principal, "Tickets uebernehmen")
        first, second = self.flow.first, self.flow.second
        if second == self.flow.last:
            self._require_approval(principal)
        origin, actor_id = self.actor(principal)
        if task is not None:
            ticket = self.get_task(task)                       # 400 bei ungueltiger, 404 bei fehlender Referenz
            if slug and ticket.project_slug != slug:
                raise _invalid(f"Ticket '{task}' gehoert nicht zum Projekt '{slug}'.")
            if ticket.kind == "control":
                raise _forbidden(f"'{task}' ist ein Steuerticket des Menschen und wird nicht uebernommen.")
            self._raise_if_paused(ticket.project_slug)
            return self._claim(task, origin, actor_id)
        self._raise_if_paused(slug)
        # Nacharbeit aus dem Review zuerst, auch ueber Projekte hinweg; sonst Board-Reihenfolge
        candidates = sorted(self.list_tasks(slug, [first]), key=lambda t: t.review_state not in REWORK_STATES)
        for candidate in candidates:
            if candidate.human or candidate.kind == "control":
                continue
            position = self._end_position(candidate.project_id, second)
            event = TaskEvent.create(candidate.id, "status", first, second, origin, actor_id=actor_id)
            if self._repo.claim_task(candidate.id, first, second, position, self._now(), event):
                return self._repo.get_task_by_id(candidate.id)
        return None

    def _claim(self, ref: str, origin, actor_id) -> Task:
        """Ein bestimmtes Ticket atomar uebernehmen; sonst klarer Fehler, ohne Aenderung."""
        first, second = self.flow.first, self.flow.second
        task = self.get_task(ref)
        if task.human:
            raise _forbidden(f"Ticket '{ref}' ist nur fuer Menschen und wird nicht uebernommen.")
        if task.kind == "control":
            raise _forbidden(f"'{ref}' ist ein Steuerticket des Menschen und wird nicht uebernommen.")
        if task.status != first:
            raise BoardError(f"Ticket '{ref}' steht nicht in '{first}' (sondern in '{task.status}'), "
                             "ist also schon uebernommen oder weiter.", 409, "NotClaimable")
        event = TaskEvent.create(task.id, "status", first, second, origin, actor_id=actor_id)
        if self._repo.claim_task(task.id, first, second, self._end_position(task.project_id, second),
                                 self._now(), event):
            return self._repo.get_task_by_id(task.id)
        current = self.get_task(ref)
        if current.human:
            raise _forbidden(f"Ticket '{ref}' ist nur fuer Menschen und wird nicht uebernommen.")
        raise BoardError(f"Ticket '{ref}' wurde inzwischen uebernommen.", 409, "NotClaimable")

    # ── Review (P3) ──────────────────────────────────────────────────────

    def _reset_review(self, task: Task, events: list[TaskEvent]) -> None:
        if task.review_state != "none":
            events.append(TaskEvent.create(task.id, "review_state", task.review_state, "none", "system",
                                           actor_id=SYSTEM_ACTOR))
        task.review_state, task.review_at = "none", None
        task.review_blocking = task.review_suggestions = None
        task.review_checked = ""

    def review(self, principal: Principal, ref: str, state: str, comment: str | None = "", *,
               blocking: int | None = None, suggestions: int | None = None, checked: str | None = "") -> Task:
        """Review-Status setzen, nur mit dem Reviewer-Zugang. Ergebnis, Kommentar (Herkunft
        ``reviewer``) und die Folgen (zurueck in die erste Spalte, Markierung nach drei roten)
        gehen in einem Schritt."""
        if not principal.is_reviewer:
            raise _forbidden("Den Review-Status setzt nur der Reviewer-Zugang.")
        if state not in REVIEW_RESULTS:
            raise _invalid(f"state muss einer von {REVIEW_RESULTS} sein.")
        for name, value in (("blocking", blocking), ("suggestions", suggestions)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise _invalid(f"{name} muss eine ganze Zahl ab 0 sein.")
        checked = "" if checked is None else checked
        comment = "" if comment is None else comment
        if not isinstance(checked, str) or len(checked) > CHECKED_MAX:
            raise _invalid(f"checked: Text mit hoechstens {CHECKED_MAX} Zeichen.")
        if not isinstance(comment, str):
            raise _invalid("comment muss Text sein.")
        if state != "running" and not comment.strip():
            raise _invalid("Ein Ergebnis braucht den Review-Kommentar.")
        try:
            check_field_limits(text=comment, what="Kommentar")
        except ValueError as e:
            raise _invalid(str(e)) from None

        task = self.get_task(ref)
        self._guard_write(principal, task)                   # "nur fuer Menschen": nur lesen
        if task.status != self.flow.review:
            raise BoardError(f"Ticket '{ref}' steht nicht in '{self.flow.review}' (sondern in '{task.status}').",
                             409, "NotInReview")
        origin, actor_id = self.actor(principal)
        events = [TaskEvent.create(task.id, "review_state", task.review_state, state, origin, actor_id=actor_id)]
        task.review_state, task.review_at = state, self._now()
        if state != "running":
            task.review_blocking, task.review_suggestions, task.review_checked = blocking, suggestions, checked
        if state == "passed":
            task.review_red_count = 0
        elif state == "failed":
            task.review_red_count += 1
        if state in REWORK_STATES:
            # Systemregel: Nacharbeit zurueck in die erste Spalte, dort vor dem Rang (siehe _sort_key)
            events.append(TaskEvent.create(task.id, "status", task.status, self.flow.first, "system",
                                           actor_id=SYSTEM_ACTOR))
            task.status = self.flow.first
            task.position = self._end_position(task.project_id, self.flow.first)
            if state == "failed" and task.review_red_count >= RED_LIMIT and not task.human:
                events.append(TaskEvent.create(task.id, "human", False, True, "system", actor_id=SYSTEM_ACTOR))
                task.human = True
        task.updated_at = self._now()
        note = (TaskComment.create(task.id, comment, origin, actor_id=actor_id) if comment.strip() else None)
        if not self._repo.update_task(task, events, note):
            if self._repo.get_task_by_id(task.id) is None:
                raise BoardError(f"Ticket '{ref}' nicht gefunden.", 404, "TaskNotFound")
            raise BoardError(f"Ticket '{ref}' wurde inzwischen geaendert; bitte neu laden.", 409, "Conflict")
        return task

    def last_review(self, ref: str) -> TaskComment | None:
        """Juengster Kommentar des Reviewers, z. B. fuer die Nacharbeit."""
        return self._repo.last_comment(self.get_task(ref).id, "reviewer")

    # ── Kommentare ───────────────────────────────────────────────────────

    def add_comment(self, principal: Principal, ref: str, body: str, author_name: str = "") -> TaskComment:
        task = self.get_task(ref)
        self._guard_write(principal, task)
        origin, actor_id = self.actor(principal)
        if (principal.is_agent and task.kind == "control" and task.control == "hint" and not task.control_ack_by
                and task.status != self.flow.last):
            return self._acknowledge(task, body, origin, actor_id, author_name)
        # Agenten: die Markierung wird beim Schreiben erneut geprueft (sie kann inzwischen gesetzt sein)
        return self._save_comment(task, body, origin, actor_id, author_name, only_if_not_human=principal.is_agent)

    def _acknowledge(self, task: Task, body, origin, actor_id, author_name: str) -> TaskComment:
        """Kommentar eines Agenten an einem Hinweis = Quittung; Kommentar und Quittung zusammen."""
        if not isinstance(body, str) or not body.strip():
            raise _invalid("Kommentar darf nicht leer sein.")
        try:
            check_field_limits(text=body, what="Kommentar")
        except ValueError as e:
            raise _invalid(str(e)) from None
        name = str(author_name or "")[:100]
        comment = TaskComment.create(task.id, body, origin, actor_id=actor_id, author_name=name)
        # Anzeigename ist frei waehlbar; die Rolle aus dem Token steht immer dabei
        by = f"{name} ({origin})" if name else origin
        task.control_ack_by, task.control_ack_at, task.updated_at = by, self._now(), self._now()
        event = TaskEvent.create(task.id, "control_ack", None, by, origin, actor_id=actor_id)
        if not self._repo.update_task(task, [event], comment):
            raise BoardError(f"Ticket '{task.ref}' wurde inzwischen geaendert; bitte erneut kommentieren.",
                             409, "Conflict")
        return comment

    # ── Steuertickets (P6) ───────────────────────────────────────────────

    def _open_controls(self, slug: str | None = None) -> list[Task]:
        """Offene Steuertickets mit Herkunft Mensch, die fuer ``slug`` gelten (ohne slug: alle)."""
        open_statuses = [s for s in self.flow.statuses if s != self.flow.last]
        found = []
        for task in self._repo.list_tasks(None, open_statuses, kind="control"):
            if task.kind != "control" or task.origin != "human":
                continue
            if slug is None or task.control_scope == "all" or task.project_slug == slug:
                found.append(task)
        return sorted(found, key=lambda t: (t.created_at, t.project_slug, t.number))

    @staticmethod
    def _control_entry(task: Task) -> dict:
        return {"task": task.ref, "type": task.control,
                "scope": "all" if task.control_scope == "all" else task.project_slug,
                "reason": task.title, "text": task.description, "by": task.created_by or "human",
                "at": _iso(task.created_at)}

    def control_state(self, slug: str | None = None) -> dict:
        """Offene Pausen und unquittierte Hinweise, fuer jede Board-Antwort (Feld ``control``)."""
        controls = self._open_controls(slug)
        return {"pauses": [self._control_entry(t) for t in controls if t.control == "pause"],
                "hints": [self._control_entry(t) for t in controls if t.control == "hint" and not t.control_ack_by]}

    def _raise_if_paused(self, slug: str | None) -> None:
        pauses = [t for t in self._open_controls(slug) if t.control == "pause"]
        if pauses:
            entry = self._control_entry(pauses[0])
            error = BoardError(f"Pausiert durch {entry['by']} ({entry['task']}): {entry['reason']}", 409, "Paused")
            error.pause = entry
            raise error

    def add_system_comment(self, ref: str, body: str, author_name: str) -> TaskComment:
        """Von Conclave selbst geschrieben (z. B. Consultations): Herkunft ``system``."""
        return self._save_comment(self.get_task(ref), body, "system", SYSTEM_ACTOR, author_name)

    def _save_comment(self, task: Task, body: str, origin, actor_id, author_name: str, *,
                      only_if_not_human: bool = False) -> TaskComment:
        if not isinstance(body, str) or not body.strip():
            raise _invalid("Kommentar darf nicht leer sein.")
        try:
            check_field_limits(text=body, what="Kommentar")
        except ValueError as e:
            raise _invalid(str(e)) from None
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
        try:
            check_field_limits(text=body, what="Kommentar")
        except ValueError as e:
            raise _invalid(str(e)) from None
        origin, actor_id = self.actor(principal)
        event = TaskEvent.create(comment.task_id, "comment", comment.body, body, origin, actor_id=actor_id)
        comment.body, comment.updated_at = body, self._now()
        if not self._repo.update_comment(comment, event):
            raise BoardError("Kommentar nicht gefunden.", 404, "CommentNotFound")
        return comment

    def delete_comment(self, principal: Principal, comment_id: str) -> None:
        """Soft-Delete: der Kommentar verschwindet aus der Liste, sein Inhalt bleibt im Verlauf."""
        comment = self._own_comment(principal, comment_id)
        origin, actor_id = self.actor(principal)
        event = TaskEvent.create(comment.task_id, "comment", comment.body, None, origin, actor_id=actor_id)
        if not self._repo.delete_comment(comment_id, self._now(), event):
            raise BoardError("Kommentar nicht gefunden.", 404, "CommentNotFound")

    # ── Spalten (R9) ─────────────────────────────────────────────────────

    def sync_flow(self) -> int:
        """Gleicht die gespeicherte letzte Spalte mit der Konfiguration ab. Wurde sie umbenannt
        (alter Name fehlt in den Spalten), ziehen ihre Tickets in die neue letzte Spalte mit,
        damit sie erledigt bleiben. Liefert die Zahl verschobener Tickets."""
        stored = self._repo.get_setting(LAST_STATUS_KEY)
        moved = 0
        if stored and stored != self.flow.last and stored not in self.flow.statuses:
            for task in self._repo.list_tasks(None, [stored]):
                event = TaskEvent.create(task.id, "status", stored, self.flow.last, "system", actor_id=SYSTEM_ACTOR)
                task.status = self.flow.last
                task.position = self._end_position(task.project_id, self.flow.last)
                task.updated_at = self._now()
                if self._repo.update_task(task, [event]):
                    moved += 1
        if stored != self.flow.last:
            self._repo.set_setting(LAST_STATUS_KEY, self.flow.last)
        return moved

    # ── Import ───────────────────────────────────────────────────────────

    def import_export(self, principal: Principal, data) -> dict:
        """Uebernimmt einen JSON-Export (siehe ``board_import``); nur mit Freigabe-Recht."""
        from conclave.application.board_import import ImportFormatError, parse_export

        self._require_approval(principal)
        origin, actor_id = self.actor(principal)
        try:
            projects = parse_export(data, self.flow.statuses)
        except ImportFormatError as e:
            raise BoardError(str(e), 400, "ImportFormatError") from None
        summary = {"projects_created": 0, "tasks_imported": 0, "tasks_skipped": 0, "comments_imported": 0,
                   "skipped_refs": []}
        for imported in projects:
            project = self._repo.get_project(imported.slug)
            if project is None:
                project = Project.create(imported.slug, imported.name)
                self._repo.create_project(project, ProjectEvent.create(project.id, "created", None, project.name,
                                                                       origin, actor_id=actor_id))
                summary["projects_created"] += 1
            for it in imported.tasks:
                ref = f"{project.slug}#{it.number}"
                if self._repo.get_task(project.slug, it.number) is not None:
                    summary["tasks_skipped"] += 1          # idempotent: schon vorhanden
                    summary["skipped_refs"].append(ref)
                    continue
                task = Task.create(project, it.title, it.status, description=it.description, tags=it.tags,
                                   position=self._end_position(project.id, it.status), human=it.human,
                                   rank=self._next_rank(project.id))
                task.number, task.created_at, task.updated_at = it.number, it.created_at, it.updated_at
                task.created_by = "import"                 # Herkunft des Inhalts unbekannt (origin None)
                comments = []
                for ic in it.comments:
                    comment = TaskComment.create(task.id, ic.body, None, author_name=ic.author)
                    comment.created_at = ic.created_at
                    comments.append(comment)
                event = TaskEvent.create(task.id, "created", None, "import", origin, actor_id=actor_id)
                if not self._repo.import_task(task, comments, event):    # Ticket und Kommentare zusammen
                    summary["tasks_skipped"] += 1          # Nummer inzwischen vergeben
                    summary["skipped_refs"].append(ref)
                    continue
                summary["tasks_imported"] += 1
                summary["comments_imported"] += len(comments)
        return summary


def _tags_value(tags) -> str:
    return json.dumps(list(tags), ensure_ascii=False)


# ── Darstellung fuer API und MCP ─────────────────────────────────────────

def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def project_to_dict(project: Project) -> dict:
    return {"slug": project.slug, "name": project.name, "created_at": _iso(project.created_at)}


def task_to_dict(task: Task) -> dict:
    return {
        "ref": task.ref, "project": task.project_slug, "number": task.number, "title": task.title,
        "description": task.description, "tags": list(task.tags), "status": task.status,
        "position": task.position, "rank": task.rank, "human": task.human, "assignee": task.assignee,
        "version": task.version, "origin": task.origin, "created_by": task.created_by,
        "kind": task.kind,
        "directive": ({"type": task.control, "scope": task.control_scope, "ack_by": task.control_ack_by or None,
                       "ack_at": _iso(task.control_ack_at)} if task.kind == "control" else None),
        "review": {"state": task.review_state, "at": _iso(task.review_at), "red_count": task.review_red_count,
                   "blocking": task.review_blocking, "suggestions": task.review_suggestions,
                   "checked": task.review_checked},
        "created_at": _iso(task.created_at), "updated_at": _iso(task.updated_at),
    }


def comment_to_dict(comment: TaskComment) -> dict:
    return {"id": comment.id, "body": comment.body, "origin": comment.origin, "actor_id": comment.actor_id,
            "author_name": comment.author_name, "created_at": _iso(comment.created_at),
            "updated_at": _iso(comment.updated_at)}


def event_to_dict(event: TaskEvent) -> dict:
    return {"field": event.field_name, "old": event.old_value, "new": event.new_value, "origin": event.origin,
            "actor_id": event.actor_id, "created_at": _iso(event.created_at)}


def project_event_to_dict(event: ProjectEvent) -> dict:
    return {"field": event.field_name, "old": event.old_value, "new": event.new_value, "origin": event.origin,
            "actor_id": event.actor_id, "created_at": _iso(event.created_at)}
