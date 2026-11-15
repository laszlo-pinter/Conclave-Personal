"""Ticket aus einem externen Board (z. B. Kanzo) - fremder, nicht vertrauenswuerdiger Inhalt.

Titel, Beschreibung und Kommentare gelten als Daten, nie als Anweisung.
"""

import re
from dataclasses import dataclass, field

# Ticket-Referenz wie "api#12" (Projekt-Slug + Nummer)
# \Z statt $: "$" passt auch vor einem abschliessenden Zeilenumbruch (Umgehung der Obergrenze)
TASK_REF = re.compile(r"^[a-z0-9][a-z0-9_-]*#\d+\Z")


def normalize_ref(ref: str) -> str:
    """``api#012`` -> ``api#12``: so zaehlen und finden Consultations dieselbe Referenz (R10)."""
    project, number = ref.split("#", 1)
    return f"{project}#{int(number)}"


@dataclass(frozen=True)
class TicketComment:
    author: str
    time: str
    body: str
    origin: str | None = None      # nur im eigenen Board belegt (human/agent/system/None)


@dataclass(frozen=True)
class Ticket:
    key: str                       # z. B. "api#12"
    title: str
    status: str
    human: bool                    # "for the user, not for agents"
    description: str = ""
    comments: tuple[TicketComment, ...] = field(default_factory=tuple)

    def has_marker(self, marker: str, author: str | None = None) -> bool:
        """Steht ``marker`` schon in einem Kommentar? (Erkennung doppelter Zustellungen)

        Mit ``author`` zaehlen nur Kommentare dieses Autors - ein fremder Kommentar
        mit vorweggenommener Kennung soll eine Zustellung nicht zufaellig unterdruecken.
        (Autor und Kennung sind in Kanzo trotzdem faelschbar, siehe sicherheit.md.)
        """
        return any(marker in c.body and (author is None or c.author == author) for c in self.comments)
