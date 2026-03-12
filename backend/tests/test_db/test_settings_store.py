"""Tests for settings store."""

from hypomnema.crypto import get_or_create_key
from hypomnema.db.settings_store import (
    get_all_settings,
    get_all_settings_masked,
    get_setting,
    set_setting,
)


class TestSettingsStore:
    async def test_set_and_get_plaintext(self, tmp_db, tmp_path):
        key = get_or_create_key(tmp_path)
        await set_setting(tmp_db, "llm_provider", "openai", fernet_key=key)
        result = await get_setting(tmp_db, "llm_provider", fernet_key=key)
        assert result == "openai"

    async def test_set_and_get_encrypted(self, tmp_db, tmp_path):
        key = get_or_create_key(tmp_path)
        await set_setting(tmp_db, "openai_api_key", "sk-secret123", fernet_key=key, encrypt_value=True)
        result = await get_setting(tmp_db, "openai_api_key", fernet_key=key)
        assert result == "sk-secret123"

    async def test_get_missing_returns_none(self, tmp_db, tmp_path):
        key = get_or_create_key(tmp_path)
        result = await get_setting(tmp_db, "nonexistent", fernet_key=key)
        assert result is None

    async def test_upsert_overwrites(self, tmp_db, tmp_path):
        key = get_or_create_key(tmp_path)
        await set_setting(tmp_db, "llm_provider", "claude", fernet_key=key)
        await set_setting(tmp_db, "llm_provider", "google", fernet_key=key)
        result = await get_setting(tmp_db, "llm_provider", fernet_key=key)
        assert result == "google"

    async def test_get_all_settings_masked(self, tmp_db, tmp_path):
        key = get_or_create_key(tmp_path)
        await set_setting(tmp_db, "llm_provider", "openai", fernet_key=key)
        await set_setting(tmp_db, "openai_api_key", "sk-secret1234", fernet_key=key, encrypt_value=True)
        result = await get_all_settings_masked(tmp_db)
        assert result["llm_provider"] == "openai"
        # Encrypted value should be masked (raw ciphertext, not decrypted)
        assert "sk-secret" not in result["openai_api_key"]

    async def test_get_all_settings_decrypted(self, tmp_db, tmp_path):
        key = get_or_create_key(tmp_path)
        await set_setting(tmp_db, "openai_api_key", "sk-abc", fernet_key=key, encrypt_value=True)
        result = await get_all_settings(tmp_db, fernet_key=key)
        assert result["openai_api_key"] == "sk-abc"
