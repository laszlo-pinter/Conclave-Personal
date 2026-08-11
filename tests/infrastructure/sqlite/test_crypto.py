# tests/infrastructure/sqlite/test_crypto.py

import os

import pytest
from pathlib import Path


def test_crypto_service_encrypt_decrypt_roundtrip():
    from cryptography.fernet import Fernet
    from conclave.infrastructure.crypto import CryptoService

    crypto = CryptoService(Fernet.generate_key())
    plaintext = "sk-ant-sehr-geheim"
    encrypted = crypto.encrypt(plaintext)

    assert encrypted != plaintext
    assert crypto.decrypt(encrypted) == plaintext


def test_crypto_service_different_keys_cannot_decrypt():
    from cryptography.fernet import Fernet
    from conclave.infrastructure.crypto import CryptoService

    crypto_a = CryptoService(Fernet.generate_key())
    crypto_b = CryptoService(Fernet.generate_key())

    encrypted = crypto_a.encrypt("geheimnis")

    with pytest.raises(Exception):
        crypto_b.decrypt(encrypted)


def test_load_or_generate_creates_key_file(tmp_path):
    from conclave.infrastructure.crypto import CryptoService

    key_path = tmp_path / "secret.key"
    crypto = CryptoService.load_or_generate(key_path)

    assert key_path.exists()
    assert crypto.decrypt(crypto.encrypt("test")) == "test"


def test_load_or_generate_reuses_existing_key(tmp_path):
    from conclave.infrastructure.crypto import CryptoService

    key_path = tmp_path / "secret.key"
    crypto_a = CryptoService.load_or_generate(key_path)
    encrypted = crypto_a.encrypt("persistenz")

    crypto_b = CryptoService.load_or_generate(key_path)
    assert crypto_b.decrypt(encrypted) == "persistenz"


@pytest.mark.skipif(os.name == "nt", reason="POSIX chmod-Bits sind unter Windows no-op; ACLs muessten separat getestet werden.")
def test_load_or_generate_sets_restrictive_permissions(tmp_path):
    import stat
    from conclave.infrastructure.crypto import CryptoService

    key_path = tmp_path / "secret.key"
    CryptoService.load_or_generate(key_path)

    mode = key_path.stat().st_mode
    # Nur Owner darf lesen/schreiben (0o600)
    assert not (mode & stat.S_IRGRP), "Gruppe darf nicht lesen"
    assert not (mode & stat.S_IROTH), "Andere dürfen nicht lesen"
