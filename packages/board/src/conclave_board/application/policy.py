# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Rechte und Regeln als Erweiterungspunkt (T5): ``BoardPolicy``.

Der BoardService fragt die Policy, bevor er etwas tut, das je nach Einsatz anders geregelt
ist. ``PersonalPolicy`` bildet die Regeln von Conclave Personal ab (ein Mensch, seine Agenten);
eine Erweiterung (z. B. Rollen je Projekt) ersetzt sie. Die festen Regeln fuer Agenten und den
Reviewer (nur erste Spalte anlegen, nicht nach "erledigt", "nur fuer Menschen" nur lesen ...)
bleiben im Dienst und gelten immer.

Lesen regelt allein ``Principal.projects`` (fremde Projekte gibt es nicht, 404); die Policy
wird dafuer nicht gefragt. Aktionen fuer ``can``:

- ``write``: Tickets anlegen, aendern, uebernehmen
- ``comment``: kommentieren (auch der Reviewer)
- ``approve``: Freigabe-Recht: nach und aus "erledigt", loeschen, Rang setzen, Vorhaben pflegen,
  "nur fuer Menschen" entfernen, Projekte umbenennen und loeschen
- ``release``: ein uebernommenes Ticket zurueck in die erste Spalte geben (haengende Tickets)
- ``control:mine``, ``control:project``, ``control:all``: Steuertickets (Pause, Hinweis) anlegen

``project`` ist der Kurzname oder ``None`` (projektuebergreifend), ``task`` das betroffene Ticket.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from conclave_board.domain.principal import Principal

if TYPE_CHECKING:  # pragma: no cover
    from conclave_board.domain.board import Task


class BoardPolicy:
    """Standard und Schnittstelle zugleich: eine Erweiterung erbt und ueberschreibt einzelne Methoden."""

    def can(self, principal: Principal, action: str, project: str | None, task: "Task | None" = None) -> bool:
        raise NotImplementedError

    def claimable(self, principal: Principal, task: "Task") -> bool:
        """Darf ``next_task`` dieses Ticket an diesen Zugang geben? (zusaetzlich zu den festen Regeln)"""
        return True

    def assignee_for(self, principal: Principal) -> str | None:
        """Zustaendiger beim Uebernehmen (``assignee``); ``None`` = unveraendert lassen."""
        return None

    def lock_key(self, principal: Principal, task: "Task", new_status: str) -> str | None:
        """Schluessel einer Sperre, unter der ``check_status_change`` und das Schreiben laufen."""
        return None

    def check_status_change(self, service, principal: Principal, task: "Task", new_status: str) -> None:
        """Weitere Regeln beim Statuswechsel; bei Verstoss ``BoardError`` werfen."""

    def record(self, principal: Principal, event: str, project: str | None, target: str, detail: dict) -> None:
        """Ereignis fuer ein Audit-Log (ohne Inhalte): approval, rank, control, release, ..."""


class PersonalPolicy(BoardPolicy):
    """Conclave Personal: Der Mensch darf alles, Agenten schreiben, nur der Mensch gibt frei."""

    def can(self, principal, action, project, task=None) -> bool:
        if action in ("write", "comment"):
            return True
        return principal.is_human            # approve, release, control:*
