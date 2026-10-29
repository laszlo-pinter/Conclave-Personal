"""Board: Projekte, Tickets, Kommentare und Ticket-Verlauf (Plan board.md, B1).

Eigene Umsetzung nach der Funktionsbeschreibung im Plan, kein Code aus anderen
Boards. Ein Ticket heisst nach aussen ``slug#nummer``; die Nummer ist je Projekt
fortlaufend und wird vom Repository vergeben.

Herkunft (``origin``) von Kommentaren und Verlaufseintraegen:
``human``/``agent`` aus dem Token, ``system`` fuer Eintraege, die Conclave selbst
schreibt (z. B. Consultations), ``None`` fuer Importiertes oder Unbekanntes.
``actor_id`` bereitet den Mehrbenutzerbetrieb vor (Plan, Abschnitt 6).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
REF = re.compile(r"([a-z0-9][a-z0-9-]{0,39})#([1-9][0-9]{0,8})\Z")
DEFAULT_STATUSES = ("todo", "doing", "review", "done")
ORIGINS = ("human", "agent", "system")
# Verlaufseintraege fuer diese Felder (Plan 2, "Ticket-Verlauf")
TRACKED_FIELDS = ("status", "title", "description", "human")
POSITION_STEP = 1024.0      # Abstand der Karten nach dem Neunummerieren


def _now() -> datetime:
    return datetime.now(UTC)


def _id() -> str:
    return str(uuid.uuid4())


def parse_ref(ref: str) -> tuple[str, int]:
    """``api#12`` -> (``api``, 12); alles andere ist ein ``ValueError``."""
    m = REF.match(ref) if isinstance(ref, str) else None
    if not m:
        raise ValueError(f"Ticket-Referenz muss wie 'projekt#12' aussehen: {ref!r}")
    return m.group(1), int(m.group(2))


def check_origin(origin: str | None) -> str | None:
    if origin is not None and origin not in ORIGINS:
        raise ValueError(f"origin muss einer von {ORIGINS} oder None sein")
    return origin


def event_value(value) -> str | None:
    """Wert fuer den Verlauf, vollstaendig (Entscheidung Laszlo, 29.10.2026): Nur so ist
    sichtbar, *was* sich an einer Abnahme geaendert hat. Verschluesselt wird im Repository."""
    if value is None:
        return None
    return str(value)


@dataclass(frozen=True)
class StatusFlow:
    """Die Spalten des Boards; neue Tickets in die erste, die letzte gilt als erledigt."""
    statuses: tuple[str, ...] = DEFAULT_STATUSES

    def __post_init__(self) -> None:
        if len(self.statuses) < 2 or len(set(self.statuses)) != len(self.statuses):
            raise ValueError("Es braucht mindestens zwei verschiedene Status")
        for s in self.statuses:
            if not SLUG.match(s):
                raise ValueError(f"Ungueltiger Status: {s!r}")

    @property
    def first(self) -> str:
        return self.statuses[0]

    @property
    def second(self) -> str:
        return self.statuses[1]

    @property
    def last(self) -> str:
        return self.statuses[-1]

    def check(self, status: str) -> str:
        if status not in self.statuses:
            raise ValueError(f"Status muss einer von {self.statuses} sein")
        return status


@dataclass
class Project:
    id: str
    slug: str
    name: str
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not SLUG.match(self.slug or ""):
            raise ValueError("Projekt-Kurzname: Kleinbuchstaben, Ziffern und '-', hoechstens 40 Zeichen")
        if not self.name.strip():
            raise ValueError("Projektname darf nicht leer sein")

    @staticmethod
    def create(slug: str, name: str) -> "Project":
        return Project(id=_id(), slug=slug, name=name)


@dataclass
class Task:
    id: str
    project_id: str
    project_slug: str
    number: int | None              # vom Repository beim Anlegen vergeben
    title: str
    status: str
    description: str = ""
    tags: tuple[str, ...] = ()
    position: float = 0.0
    human: bool = False
    assignee: str | None = None     # Mehrbenutzerbetrieb, vorerst leer
    version: int = 1                # optimistische Sperre: jede Aenderung erhoeht sie
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("Titel darf nicht leer sein")
        self.tags = tuple(dict.fromkeys(t.strip() for t in self.tags if t and t.strip()))

    @property
    def ref(self) -> str:
        if self.number is None:
            raise ValueError("Ticket hat noch keine Nummer (erst nach dem Speichern)")
        return f"{self.project_slug}#{self.number}"

    @staticmethod
    def create(project: Project, title: str, status: str, *, description: str = "", tags=(),
               position: float = 0.0, human: bool = False) -> "Task":
        return Task(id=_id(), project_id=project.id, project_slug=project.slug, number=None, title=title,
                    status=status, description=description, tags=tuple(tags), position=position, human=human)


@dataclass
class TaskComment:
    id: str
    task_id: str
    body: str
    origin: str | None
    actor_id: str | None = None
    author_name: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        check_origin(self.origin)
        if not self.body.strip():
            raise ValueError("Kommentar darf nicht leer sein")

    @staticmethod
    def create(task_id: str, body: str, origin: str | None, *, actor_id: str | None = None,
               author_name: str = "") -> "TaskComment":
        return TaskComment(id=_id(), task_id=task_id, body=body, origin=origin, actor_id=actor_id,
                           author_name=author_name)


@dataclass
class TaskEvent:
    id: str
    task_id: str
    field_name: str
    old_value: str | None
    new_value: str | None
    origin: str | None
    actor_id: str | None = None
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        check_origin(self.origin)
        if self.field_name not in TRACKED_FIELDS:
            raise ValueError(f"Verlauf nur fuer {TRACKED_FIELDS}")

    @staticmethod
    def create(task_id: str, field_name: str, old, new, origin: str | None, *,
               actor_id: str | None = None) -> "TaskEvent":
        return TaskEvent(id=_id(), task_id=task_id, field_name=field_name, old_value=event_value(old),
                         new_value=event_value(new), origin=origin, actor_id=actor_id)
