# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

import hmac

from conclave_board.domain.principal import AGENT_PRINCIPAL, HUMAN_PRINCIPAL, REVIEWER_PRINCIPAL, Principal
from conclave_board.infrastructure.log import get_logger

logger = get_logger("infrastructure.auth")


class StaticKeyAuthService:
    """Validiert Requests gegen feste Tokens: Mensch, (optional) Agent und Reviewer (P3).

    Die Rolle kommt allein aus dem Token. Ohne Agent- bzw. Reviewer-Token gibt es
    keinen solchen Zugang; ein Token, das einem anderen gleicht, gilt nicht als
    zweite Rolle.
    """

    def __init__(self, api_key: str, agent_key: str = "", reviewer_key: str = "") -> None:
        self._human_key = api_key.encode("utf-8") if api_key else b""
        agent = agent_key.encode("utf-8") if agent_key else b""
        if agent and agent == self._human_key:
            logger.warning("Agent-Token ist gleich dem Mensch-Token; Agent-Zugang deaktiviert")
            agent = b""
        self._agent_key = agent
        reviewer = reviewer_key.encode("utf-8") if reviewer_key else b""
        if reviewer and reviewer in (self._human_key, self._agent_key):
            logger.warning("Reviewer-Token ist gleich einem anderen Token; Reviewer-Zugang deaktiviert")
            reviewer = b""
        self._reviewer_key = reviewer

    @property
    def has_agent_access(self) -> bool:
        return bool(self._agent_key)

    def authenticate(self, token: str | None) -> Principal | None:
        if not token:
            return None
        given = token.encode("utf-8", errors="replace")
        # Beide Vergleiche laufen immer, kein frueher Abbruch nach dem ersten Treffer.
        human = bool(self._human_key) and hmac.compare_digest(given, self._human_key)
        agent = bool(self._agent_key) and hmac.compare_digest(given, self._agent_key)
        reviewer = bool(self._reviewer_key) and hmac.compare_digest(given, self._reviewer_key)
        if human:
            return HUMAN_PRINCIPAL
        if agent:
            return AGENT_PRINCIPAL
        if reviewer:
            return REVIEWER_PRINCIPAL
        return None

    def validate_token(self, token: str | None) -> bool:
        return self.authenticate(token) is not None
