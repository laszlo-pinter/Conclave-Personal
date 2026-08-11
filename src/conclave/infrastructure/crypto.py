# src/conclave/infrastructure/crypto.py

from __future__ import annotations

import os
import stat
from pathlib import Path

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    raise ImportError(
        "Das 'cryptography'-Paket ist nicht installiert. "
        "Bitte installieren mit: pip install conclave[crypto]"
    )


class NullCryptoService:
    """Identity-Verschluesselung: gibt Klartext zurueck. Fuer Entwicklung/Tests."""

    def encrypt(self, plaintext: str) -> str:
        return plaintext

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext


class CryptoService:
    """Symmetrische Verschlüsselung für sensible Felder (Fernet / AES-128-CBC + HMAC-SHA256)."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """Verschlüsselt einen Klartext-String und gibt Base64-Token zurück."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Entschlüsselt ein Fernet-Token und gibt den Klartext zurück."""
        return self._fernet.decrypt(ciphertext.encode()).decode()

    @staticmethod
    def load_or_generate(key_path: Path) -> CryptoService:
        """Lädt einen bestehenden Key oder generiert und speichert einen neuen.

        Die Key-Datei wird mit Berechtigungen 0o600 (nur Owner) angelegt.
        Vorrang hat die Umgebungsvariable CONCLAVE_SECRET_KEY (Base64-Fernet-Key).
        """
        env_key = os.environ.get("CONCLAVE_SECRET_KEY")
        if env_key:
            return CryptoService(env_key.encode())

        if key_path.exists():
            return CryptoService(key_path.read_bytes())

        key = Fernet.generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key)
        key_path.chmod(0o600)
        return CryptoService(key)


class MultiKeyCryptoService:
    """Unterstuetzt Key-Rotation: verschluesselt mit aktuellem Key, entschluesselt mit allen."""

    def __init__(self, current_key: bytes, old_keys: list[bytes] | None = None):
        self._current = Fernet(current_key)
        self._all = [self._current] + [Fernet(k) for k in (old_keys or [])]

    def encrypt(self, plaintext: str) -> str:
        return self._current.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        data = ciphertext.encode()
        for fernet in self._all:
            try:
                return fernet.decrypt(data).decode()
            except InvalidToken:
                continue
        raise InvalidToken("Kein Key konnte den Ciphertext entschluesseln.")
