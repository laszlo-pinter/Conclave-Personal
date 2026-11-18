# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

"""Wer eine Anfrage stellt: Mensch, Agent oder Reviewer.

Die Rolle ergibt sich allein aus dem Token, nie aus Angaben in der Anfrage.
Der Reviewer (P3) ist ein Agent mit eigenem Token: Fuer ihn gelten alle Grenzen
eines Agenten (``is_agent``), dazu eine engere Allowlist und als einzigem das
Setzen des Review-Status (``is_reviewer``).
"""

from dataclasses import dataclass
from typing import Literal

HUMAN = "human"
AGENT = "agent"
REVIEWER = "reviewer"

Role = Literal["human", "agent", "reviewer"]


@dataclass(frozen=True)
class Principal:
    """Rolle und, wenn eine Erweiterung Konten kennt, Konto und erlaubte Projekte (T4).

    - ``actor_id``: Konto, in dessen Namen die Anfrage laeuft (bei Agenten: der Mensch,
      dem der Agent gehoert). ``None`` = ohne Konten wie in Personal; dann gilt die Rolle.
    - ``projects``: Projekte, die dieser Zugang sieht. ``None`` = alle (Personal).
    - ``name``: Anzeigename des Kontos fuer Meldungen, sonst leer.
    """
    role: Role
    actor_id: str | None = None
    projects: frozenset[str] | None = None
    name: str = ""

    def sees(self, project_slug: str) -> bool:
        """Darf dieser Zugang das Projekt sehen? Fremde Projekte gelten als nicht vorhanden."""
        return self.projects is None or project_slug in self.projects

    @property
    def is_human(self) -> bool:
        return self.role == HUMAN

    @property
    def is_agent(self) -> bool:
        """Kein Mensch: Agent oder Reviewer. Jede Agent-Grenze gilt auch fuer den Reviewer."""
        return self.role in (AGENT, REVIEWER)

    @property
    def is_reviewer(self) -> bool:
        return self.role == REVIEWER


HUMAN_PRINCIPAL = Principal(HUMAN)
AGENT_PRINCIPAL = Principal(AGENT)
REVIEWER_PRINCIPAL = Principal(REVIEWER)
