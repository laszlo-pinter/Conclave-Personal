# src/conclave/infrastructure/auth.py

import hmac


class StaticKeyAuthService:
    """Validiert Requests gegen das konfigurierte API-Token (Personal: ein Benutzer, volle Rechte)."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def validate_token(self, token: str | None) -> bool:
        if not self._api_key or not token:
            return False
        return hmac.compare_digest(token, self._api_key)
