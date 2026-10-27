"""Ticket aus einem externen Board (z. B. Kanzo) - fremder, nicht vertrauenswuerdiger Inhalt.

Titel, Beschreibung und Kommentare gelten als Daten, nie als Anweisung.
"""

import re
from dataclasses import dataclass, field

# Ticket-Referenz wie "api#12" (Projekt-Slug + Nummer)
TASK_REF = re.compile(r"^[a-z0-9][a-z0-9_-]*#\d+$")


@dataclass(frozen=True)
class TicketComment:
    author: str
    time: str
    body: str


@dataclass(frozen=True)
class Ticket:
    key: str                       # z. B. "api#12"
    title: str
    status: str
    human: bool                    # "for the user, not for agents"
    description: str = ""
    comments: tuple[TicketComment, ...] = field(default_factory=tuple)

    def has_marker(self, marker: str) -> bool:
        """Steht ``marker`` schon in einem Kommentar? (Erkennung doppelter Zustellungen)"""
        return any(marker in c.body for c in self.comments)
