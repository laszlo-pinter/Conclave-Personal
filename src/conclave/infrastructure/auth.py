# src/conclave/infrastructure/auth.py


class StaticKeyAuthService:
    """Validiert Requests gegen einen konfigurierten API-Key."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def validate_token(self, token: str | None) -> bool:
        if not self._api_key or not token:
            return False
        return token == self._api_key

    def get_role(self, token: str | None) -> str | None:
        if self.validate_token(token):
            return "owner"  # StaticKey hat volle Rechte
        return None

    def check_permission(self, role: str, method: str, path: str) -> bool:
        return True  # StaticKey hat volle Rechte


# ── Rollen-Berechtigungen ──────────────────────────────────────────────

_ROLE_PERMISSIONS = {
    "viewer": {
        "GET": True,
        "POST": False,
        "PUT": False,
        "DELETE": False,
    },
    "operator": {
        "GET": True,
        "POST": True,
        "PUT": True,
        "DELETE": True,
    },
    "owner": {
        "GET": True,
        "POST": True,
        "PUT": True,
        "DELETE": True,
    },
    "key_admin": {
        "GET": True,
        "POST": True,
        "PUT": True,
        "DELETE": True,
    },
}


class RoleBasedAuthService:
    """Validiert Requests gegen API-Key-zu-Rolle-Mapping."""

    def __init__(self, key_role_map: dict[str, str]) -> None:
        self._key_role_map = key_role_map

    def validate_token(self, token: str | None) -> bool:
        if not token:
            return False
        return token in self._key_role_map

    def get_role(self, token: str | None) -> str | None:
        if not token:
            return None
        return self._key_role_map.get(token)

    def check_permission(self, role: str, method: str, path: str) -> bool:
        perms = _ROLE_PERMISSIONS.get(role)
        if perms is None:
            return False

        # Pfad-basierte Deny-Liste pruefen
        deny_paths = perms.get("_deny_paths", set())
        for denied in deny_paths:
            if path.startswith(denied):
                return False

        return perms.get(method, False)
