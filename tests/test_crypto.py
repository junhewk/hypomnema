"""Tests for crypto module."""

import pytest
from cryptography.fernet import InvalidToken

from hypomnema.crypto import decrypt, encrypt, get_or_create_key, mask_key


class TestGetOrCreateKey:
    def test_creates_file(self, tmp_path):
        key = get_or_create_key(tmp_path)
        assert (tmp_path / ".hypomnema_key").exists()
        assert len(key) > 0

    def test_idempotent(self, tmp_path):
        key1 = get_or_create_key(tmp_path)
        key2 = get_or_create_key(tmp_path)
        assert key1 == key2


class TestEncryptDecrypt:
    def test_roundtrip(self, tmp_path):
        key = get_or_create_key(tmp_path)
        plaintext = "sk-ant-api03-secret"
        ciphertext = encrypt(plaintext, key)
        assert ciphertext != plaintext
        assert decrypt(ciphertext, key) == plaintext

    def test_decrypt_wrong_key_raises(self, tmp_path):
        key1 = get_or_create_key(tmp_path)
        from cryptography.fernet import Fernet

        key2 = Fernet.generate_key()
        ciphertext = encrypt("secret", key1)
        with pytest.raises(InvalidToken):
            decrypt(ciphertext, key2)


class TestMaskKey:
    def test_long_key(self):
        assert mask_key("sk-ant-api03-abcdef") == "****cdef"

    def test_short_key(self):
        assert mask_key("ab") == "****"

    def test_exact_4(self):
        assert mask_key("abcd") == "****abcd"

    def test_empty(self):
        assert mask_key("") == "****"
