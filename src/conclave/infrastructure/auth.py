# src/conclave/infrastructure/auth.py

import hmac

from conclave.domain.principal import AGENT_PRINCIPAL, HUMAN_PRINCIPAL, Principal
from conclave.infrastructure.log import get_logger

logger = get_logger("infrastructure.auth")


class StaticKeyAuthService:
    """Validiert Requests gegen zwei feste Tokens: Mensch und (optional) Agent.

    Die Rolle kommt allein aus dem Token. Ohne Agent-Token gibt es keinen
    Agent-Zugang; das Mensch-Token gilt nie als Agent-Token.
    """

    def __init__(self, api_key: str, agent_key: str = "") -> None:
        self._human_key = api_key.encode("utf-8") if api_key else b""
        agent = agent_key.encode("utf-8") if agent_key else b""
        if agent and agent == self._human_key:
            logger.warning("Agent-Token ist gleich dem Mensch-Token; Agent-Zugang deaktiviert")
            agent = b""
        self._agent_key = agent

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
        if human:
            return HUMAN_PRINCIPAL
        if agent:
            return AGENT_PRINCIPAL
        return None

    def validate_token(self, token: str | None) -> bool:
        return self.authenticate(token) is not None
