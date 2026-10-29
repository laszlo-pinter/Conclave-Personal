"""Import eines Boards aus einem JSON-Export (Plan board.md, Abschnitt 4.5, B3).

Grundlage ist die JSON-Ausgabe von ``kanzo export -f json``: Daten des Nutzers,
kein Code. Gelesen werden nur die Felder, die der Plan nennt.

- Erst wird alles geprueft, dann geschrieben; ein fehlerhafter Export schreibt nichts.
- Idempotent: Ein Ticket, dessen Nummer im Projekt schon existiert, wird samt
  Kommentaren uebersprungen. Ein zweiter Import aendert also nichts.
- Herkunft ``None`` fuer alle Kommentare: Im Quell-Board kann jeder unter jedem
  Namen schreiben, der Import behauptet keine Herkunft. Der Autor bleibt als
  Anzeigename erhalten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from conclave.domain.board import SLUG, parse_ref

MAX_PROJECTS = 200
MAX_TASKS = 20_000
MAX_COMMENTS_PER_TASK = 2_000


class ImportFormatError(ValueError):
    """Export entspricht nicht dem erwarteten Aufbau."""


@dataclass
class ImportedComment:
    author: str
    body: str
    created_at: datetime


@dataclass
class ImportedTask:
    number: int
    title: str
    description: str
    tags: tuple[str, ...]
    human: bool
    status: str
    created_at: datetime
    updated_at: datetime
    comments: list[ImportedComment] = field(default_factory=list)


@dataclass
class ImportedProject:
    slug: str
    name: str
    tasks: list[ImportedTask] = field(default_factory=list)


def _str(value, what: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ImportFormatError(f"{what} muss Text sein")
    return value


def _time(value, what: str) -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(_str(value, what).replace("Z", "+00:00"))
    except ValueError:
        raise ImportFormatError(f"{what}: ungueltiger Zeitpunkt {value!r}") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_export(data, statuses) -> list[ImportedProject]:
    """Prueft den Export vollstaendig und liefert die zu importierenden Projekte."""
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        raise ImportFormatError("Erwartet wird ein Objekt mit einer Liste 'projects'")
    if len(data["projects"]) > MAX_PROJECTS:
        raise ImportFormatError(f"Hoechstens {MAX_PROJECTS} Projekte")
    projects, total, unknown = [], 0, set()
    for p in data["projects"]:
        if not isinstance(p, dict):
            raise ImportFormatError("Projekt muss ein Objekt sein")
        slug = _str(p.get("slug"), "Projekt-Kurzname", allow_empty=False)
        if not SLUG.match(slug):
            raise ImportFormatError(f"Ungueltiger Projekt-Kurzname: {slug!r}")
        project = ImportedProject(slug=slug, name=_str(p.get("name") or slug, f"{slug}: Name", allow_empty=False))
        tasks = p.get("tasks", [])
        if not isinstance(tasks, list):
            raise ImportFormatError(f"{slug}: 'tasks' muss eine Liste sein")
        total += len(tasks)
        if total > MAX_TASKS:
            raise ImportFormatError(f"Hoechstens {MAX_TASKS} Tickets")
        numbers = set()
        for t in tasks:
            if not isinstance(t, dict):
                raise ImportFormatError(f"{slug}: Ticket muss ein Objekt sein")
            try:
                ref_slug, number = parse_ref(t.get("key"))
            except ValueError:
                raise ImportFormatError(f"{slug}: ungueltige Ticket-Referenz {t.get('key')!r}") from None
            if ref_slug != slug or number in numbers:
                raise ImportFormatError(f"{slug}: Referenz {t.get('key')!r} passt nicht oder ist doppelt")
            numbers.add(number)
            status = _str(t.get("status"), f"{slug}#{number}: Status", allow_empty=False)
            if status not in statuses:
                unknown.add(status)
            tags = t.get("tags", [])
            if not isinstance(tags, list) or not all(isinstance(x, str) for x in tags):
                raise ImportFormatError(f"{slug}#{number}: 'tags' muss eine Liste von Texten sein")
            human = t.get("human", False)
            if not isinstance(human, bool):
                raise ImportFormatError(f"{slug}#{number}: 'human' muss true oder false sein")
            comments = t.get("comments", [])
            if not isinstance(comments, list) or len(comments) > MAX_COMMENTS_PER_TASK:
                raise ImportFormatError(f"{slug}#{number}: 'comments' muss eine Liste sein")
            task = ImportedTask(
                number=number, title=_str(t.get("title"), f"{slug}#{number}: Titel", allow_empty=False),
                description=_str(t.get("description", "") or "", f"{slug}#{number}: Beschreibung"),
                tags=tuple(tags), human=human, status=status,
                created_at=_time(t.get("created_at"), f"{slug}#{number}: created_at"),
                updated_at=_time(t.get("updated_at") or t.get("created_at"), f"{slug}#{number}: updated_at"))
            for c in comments:
                if not isinstance(c, dict):
                    raise ImportFormatError(f"{slug}#{number}: Kommentar muss ein Objekt sein")
                body = _str(c.get("body"), f"{slug}#{number}: Kommentar")
                if body.strip():
                    task.comments.append(ImportedComment(
                        author=_str(c.get("author", "") or "", f"{slug}#{number}: Autor")[:100], body=body,
                        created_at=_time(c.get("created_at"), f"{slug}#{number}: Kommentar-Zeit")))
            task.comments.sort(key=lambda c: c.created_at)
            project.tasks.append(task)
        projects.append(project)
    if unknown:
        raise ImportFormatError(f"Unbekannte Status {sorted(unknown)}; erlaubt sind {list(statuses)} "
                                "([board] statuses in config.toml)")
    return projects
