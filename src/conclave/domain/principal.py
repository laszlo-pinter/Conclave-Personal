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
    role: Role

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
