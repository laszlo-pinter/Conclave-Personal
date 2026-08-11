# tests/infrastructure/test_key_rotation.py

"""Key-Rotation: Neuer Key verschluesselt, alter Key entschluesselt."""

import pytest
from cryptography.fernet import Fernet

from conclave.infrastructure.crypto import CryptoService, MultiKeyCryptoService


class TestMultiKeyCryptoService:
    def test_encrypts_with_current_key(self):
        key1 = Fernet.generate_key()
        multi = MultiKeyCryptoService(current_key=key1)
        ciphertext = multi.encrypt("Hallo")
        # Entschluesseln mit dem gleichen Key muss funktionieren
        single = CryptoService(key1)
        assert single.decrypt(ciphertext) == "Hallo"

    def test_decrypts_with_current_key(self):
        key1 = Fernet.generate_key()
        multi = MultiKeyCryptoService(current_key=key1)
        ciphertext = multi.encrypt("Test")
        assert multi.decrypt(ciphertext) == "Test"

    def test_decrypts_with_old_key(self):
        old_key = Fernet.generate_key()
        new_key = Fernet.generate_key()

        # Mit altem Key verschluesseln
        old_crypto = CryptoService(old_key)
        ciphertext = old_crypto.encrypt("Altdaten")

        # MultiKey mit neuem Key + altem als Fallback
        multi = MultiKeyCryptoService(current_key=new_key, old_keys=[old_key])
        assert multi.decrypt(ciphertext) == "Altdaten"

    def test_new_encryption_uses_new_key(self):
        old_key = Fernet.generate_key()
        new_key = Fernet.generate_key()

        multi = MultiKeyCryptoService(current_key=new_key, old_keys=[old_key])
        ciphertext = multi.encrypt("Neudaten")

        # Neuer Key muss entschluesseln koennen
        new_crypto = CryptoService(new_key)
        assert new_crypto.decrypt(ciphertext) == "Neudaten"

        # Alter Key darf NICHT entschluesseln koennen
        old_crypto = CryptoService(old_key)
        with pytest.raises(Exception):
            old_crypto.decrypt(ciphertext)

    def test_multiple_old_keys(self):
        key1 = Fernet.generate_key()
        key2 = Fernet.generate_key()
        key3 = Fernet.generate_key()

        # Mit key1 verschluesselt
        crypto1 = CryptoService(key1)
        ct1 = crypto1.encrypt("Von Key1")

        # Mit key2 verschluesselt
        crypto2 = CryptoService(key2)
        ct2 = crypto2.encrypt("Von Key2")

        # MultiKey mit key3 aktiv, key1+key2 als Fallback
        multi = MultiKeyCryptoService(current_key=key3, old_keys=[key1, key2])
        assert multi.decrypt(ct1) == "Von Key1"
        assert multi.decrypt(ct2) == "Von Key2"

    def test_decrypt_fails_with_unknown_key(self):
        key1 = Fernet.generate_key()
        unknown = Fernet.generate_key()

        crypto_unknown = CryptoService(unknown)
        ciphertext = crypto_unknown.encrypt("Geheim")

        multi = MultiKeyCryptoService(current_key=key1)
        with pytest.raises(Exception):
            multi.decrypt(ciphertext)

    def test_empty_string_roundtrip(self):
        multi = MultiKeyCryptoService(current_key=Fernet.generate_key())
        assert multi.decrypt(multi.encrypt("")) == ""
