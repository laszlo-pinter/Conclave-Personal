# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Ereignisse als Erweiterungspunkt (T9, Plan board-team.md 2.3 und 8).

Nach jedem erfolgreichen Schreiben meldet der ``BoardService`` die passenden Ereignisse an alle
Empfaenger, die mit ``BoardService.add_listener`` eingehaengt sind (z. B. Webhooks im Team-Paket).
Ein Ereignis traegt **keine Inhalte**: kein Titel, keine Beschreibung, kein Kommentartext, nur
Referenz, Art, Herkunft, Konto, Zeit und kleine Metadaten (alter und neuer Status, Review-Ergebnis,
Zustaendigkeit, ID eines Kommentars).

Regeln fuer Empfaenger:

- **Schnell zurueckkehren.** Der Aufruf geschieht im Ablauf der Anfrage; Netzwerk oder langsame
  Arbeit gehoert in einen eigenen Thread (Warteschlange).
- **Fehler bleiben beim Empfaenger.** Eine Ausnahme wird protokolliert und nie an die Anfrage
  weitergegeben; das Schreiben ist zu diesem Zeitpunkt schon gespeichert.

Typen:

| Typ | Wann | ``data`` |
|---|---|---|
| ``task.created`` / ``control.created`` | Ticket bzw. Steuerticket angelegt | ``status``; bei Steuertickets ``control``, ``scope`` |
| ``task.status_changed`` / ``control.status_changed`` | Spalte gewechselt | ``old``, ``new`` |
| ``task.review_result`` | Ergebnis des Reviewers | ``state`` (passed/rework/failed), ``blocking``, ``suggestions``, ``comment_id`` (das Review) |
| ``task.assigned`` | Zustaendigkeit geaendert | ``old``, ``new`` (Konto-IDs oder ``null``) |
| ``task.commented`` | Kommentar geschrieben | ``comment_id`` |
| ``control.acknowledged`` | Hinweis von einem Agenten quittiert | ``comment_id`` |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

EVENT_TYPES = (
    "task.created", "control.created",
    "task.status_changed", "control.status_changed",
    "task.review_result",
    "task.assigned",
    "task.commented",
    "control.acknowledged",
)
RESULT_STATES = ("passed", "rework", "failed")        # running und none sind keine Ergebnisse


@dataclass(frozen=True)
class BoardEvent:
    type: str
    ref: str                    # z. B. "conclave#77"
    project: str
    task_id: str
    origin: str | None          # human | agent | reviewer | system
    actor_id: str | None        # Konto (Team) bzw. Rolle (Personal)
    at: datetime
    data: dict = field(default_factory=dict)


Listener = Callable[[BoardEvent], None]


def events_for(task, history, at: datetime, comment=None) -> list[BoardEvent]:
    """Ereignisse zu einem gespeicherten Schreiben: Verlaufseintraege und ggf. ein neuer Kommentar."""
    prefix = "control" if task.kind == "control" else "task"
    result = []

    def add(kind: str, origin, actor_id, data: dict) -> None:
        result.append(BoardEvent(type=kind, ref=task.ref, project=task.project_slug, task_id=task.id,
                                 origin=origin, actor_id=actor_id, at=at, data=data))

    covered = False                                   # Kommentar gehoert zu Review bzw. Quittung
    for entry in history:
        name = entry.field_name
        if name == "created":
            data = {"status": entry.new_value}
            if task.kind == "control":
                data.update(control=task.control, scope=task.control_scope)
            add(f"{prefix}.created", entry.origin, entry.actor_id, data)
        elif name == "status":
            add(f"{prefix}.status_changed", entry.origin, entry.actor_id, {"old": entry.old_value, "new": entry.new_value})
        elif name == "review_state" and entry.new_value in RESULT_STATES:
            data = {"state": entry.new_value, "blocking": task.review_blocking, "suggestions": task.review_suggestions}
            if comment is not None:
                covered = True
                data["comment_id"] = comment.id
            add("task.review_result", entry.origin, entry.actor_id, data)
        elif name == "assignee":
            add("task.assigned", entry.origin, entry.actor_id, {"old": entry.old_value, "new": entry.new_value})
        elif name == "control_ack" and comment is not None:
            covered = True
            add("control.acknowledged", entry.origin, entry.actor_id, {"comment_id": comment.id})
    if comment is not None and not covered:
        add("task.commented", comment.origin, comment.actor_id, {"comment_id": comment.id})
    return result
