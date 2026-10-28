"""Wer eine Anfrage stellt: Mensch oder Agent.

Die Rolle ergibt sich allein aus dem Token, nie aus Angaben in der Anfrage.
"""

from dataclasses import dataclass
from typing import Literal

HUMAN = "human"
AGENT = "agent"

Role = Literal["human", "agent"]


@dataclass(frozen=True)
class Principal:
    role: Role

    @property
    def is_human(self) -> bool:
        return self.role == HUMAN

    @property
    def is_agent(self) -> bool:
        return self.role == AGENT


HUMAN_PRINCIPAL = Principal(HUMAN)
AGENT_PRINCIPAL = Principal(AGENT)
