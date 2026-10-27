"""Parser fuer die Textausgabe von Kanzos MCP-Tool ``get_task``.

Kanzo liefert kein JSON, sondern Text (``task_detail`` in ``src/mcp.rs``):

    api#12 Titel {tag1, tag2}
    status: todo, human: for the user, not for agents, created 2026-10-27 10:00 UTC, updated ...

    Beschreibung ...

    Images: /pfad/a.png

    Comments (2):
    - Autor, 2026-10-27 10:05 UTC: Text
    - Autor, 2026-10-27 10:06 UTC: Text

Der Parser ist bewusst eng: Passt die Statuszeile nicht genau, scheitert er
(``TaskFormatError``), statt zu raten - sonst koennte ein Agent ein Ticket
bearbeiten, das nur fuer Menschen gedacht ist.
"""

from __future__ import annotations

import re

from conclave.domain.errors import TaskFormatError
from conclave.domain.ticket import Ticket, TicketComment

TASK_REF = re.compile(r"^[a-z0-9][a-z0-9_-]*#\d+$")

_HEADER = re.compile(r"^(?P<key>[a-z0-9][a-z0-9_-]*#\d+) (?P<rest>.*)$")
_TAGS = re.compile(r" \{[^{}]*\}$")
_TIME = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC"
_STATUS = re.compile(
    rf"^status: (?P<status>[^,\n]+)(?P<human>, human: for the user, not for agents)?, created {_TIME}"
    rf"(?:, updated {_TIME})?$"
)
_COMMENTS = re.compile(r"\n\nComments \((?P<count>\d+)\):\n")
_COMMENT = re.compile(rf"^- (?P<author>.*?), (?P<time>{_TIME}):(?: (?P<body>.*))?$")
_IMAGES = re.compile(r"\n\nImages: [^\n]*$")


def parse_kanzo_task(text: str) -> Ticket:
    lines = text.split("\n")
    if len(lines) < 2:
        raise TaskFormatError("Kanzo get_task: unerwartet kurze Antwort")
    header = _HEADER.match(lines[0])
    status = _STATUS.match(lines[1])
    if not header or not status:
        raise TaskFormatError("Kanzo get_task: Kopf- oder Statuszeile hat ein unbekanntes Format")

    rest = "\n".join(lines[2:])
    description_part, comments = rest, ()
    # Letzter Kommentarblock, dessen Anzahl zu den gefundenen Kommentaren passt
    # (die Beschreibung koennte selbst eine Zeile "Comments (n):" enthalten).
    for block in reversed(list(_COMMENTS.finditer("\n" + rest))):
        parsed = _parse_comments(("\n" + rest)[block.end():])
        if len(parsed) == int(block.group("count")):
            description_part, comments = ("\n" + rest)[:block.start()], tuple(parsed)
            break

    # Eine zweite Statuszeile vor den Kommentaren waere mehrdeutig: im Zweifel ablehnen.
    if any(_STATUS.match(line) for line in description_part.split("\n")):
        raise TaskFormatError("Kanzo get_task: mehrdeutige Statuszeile")

    description = _IMAGES.sub("", description_part.rstrip()).strip("\n")
    return Ticket(
        key=header.group("key"),
        title=_TAGS.sub("", header.group("rest")).strip(),
        status=status.group("status").strip(),
        human=status.group("human") is not None,
        description=description,
        comments=comments,
    )


def _parse_comments(block: str) -> list[TicketComment]:
    comments: list[TicketComment] = []
    for line in block.split("\n"):
        match = _COMMENT.match(line)
        if match:
            comments.append(TicketComment(author=match.group("author"), time=match.group("time"),
                                          body=match.group("body") or ""))
        elif comments:
            # Mehrzeiliger Kommentar: Folgezeilen gehoeren zum vorigen Kommentar
            last = comments[-1]
            comments[-1] = TicketComment(author=last.author, time=last.time, body=last.body + "\n" + line)
    return comments
