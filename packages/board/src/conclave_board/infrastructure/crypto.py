# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Laszlo Pinter

from __future__ import annotations

from pathlib import Path
from conclave_board.runtime.env import env_secret

try:
    from cryptography.fernet import Fernet, InvalidToken, MultiFernet  # noqa: F401 - InvalidToken fuer Aufrufer
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
    """Symmetrische Verschlüsselung für sensible Felder (Fernet / AES-128-CBC + HMAC-SHA256).

    Verschluesselt wird mit ``key``; entschluesselt auch mit ``old_keys`` (nach
    einem Schluesselwechsel, R13).
    """

    def __init__(self, key: bytes, old_keys: list[bytes] | None = None) -> None:
        self._fernet = MultiFernet([Fernet(k) for k in [key, *(old_keys or [])]])

    def encrypt(self, plaintext: str) -> str:
        """Verschlüsselt einen Klartext-String und gibt Base64-Token zurück."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Entschlüsselt ein Fernet-Token und gibt den Klartext zurück."""
        return self._fernet.decrypt(ciphertext.encode()).decode()

    @staticmethod
    def load_or_generate(key_path: Path) -> CryptoService:
        """Lädt die Schluessel aus ``key_path`` oder legt einen neuen an.

        Vorrang hat die Umgebungsvariable CONCLAVE_SECRET_KEY (Base64-Fernet-Key).
        Die Datei entsteht exklusiv und nur fuer den Benutzer lesbar; fremde Rechte
        an einer vorhandenen Datei werden entfernt.
        """
        env_key = env_secret("CONCLAVE_SECRET_KEY")
        if env_key:
            return CryptoService(env_key.encode())
        current, old = load_key_files(key_path)
        return CryptoService(current, old)


class MultiKeyCryptoService(CryptoService):
    """Frueherer Name: verschluesselt mit ``current_key``, entschluesselt mit allen."""

    def __init__(self, current_key: bytes, old_keys: list[bytes] | None = None) -> None:
        super().__init__(current_key, old_keys)


def key_file_paths(key_path: Path) -> tuple[Path, list[Path]]:
    """(Pfad eines begonnenen Wechsels, abgeloeste Schluessel neueste zuerst)."""
    retired = sorted(key_path.parent.glob(key_path.name + ".old-*"), reverse=True)
    return key_path.with_name(key_path.name + ".new"), retired


def load_key_files(key_path: Path) -> tuple[bytes, list[bytes]]:
    """Aktueller Schluessel und alle aelteren (Wechsel, R13)."""
    from conclave_board.runtime.file_security import create_exclusive, harden

    pending, retired = key_file_paths(key_path)
    if not key_path.exists() and not pending.exists():
        create_exclusive(key_path, Fernet.generate_key())
    keys = []
    for path in [pending, key_path, *retired]:      # ein begonnener Wechsel ist der aktuelle Schluessel
        if path.exists():
            harden(path)
            keys.append(path.read_bytes().strip())
    return keys[0], keys[1:]
