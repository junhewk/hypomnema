from pathlib import Path

import pytest
from pydantic import ValidationError

from hypomnema.config import Settings


class TestSettingsDefaults:
    def test_default_mode_is_local(self):
        assert Settings().mode == "local"

    def test_default_db_path(self):
        assert Settings().db_path == Path("data/hypomnema.db")

    def test_default_embedding_dim(self):
        assert Settings().embedding_dim == 384

    def test_default_llm_provider_is_mock(self):
        assert Settings().llm_provider == "mock"

    def test_default_host_is_localhost(self):
        assert Settings().host == "127.0.0.1"

    def test_default_port(self):
        assert Settings().port == 8000

    def test_default_triage_threshold(self):
        assert Settings().triage_threshold == 0.3

    def test_api_keys_default_empty(self):
        s = Settings()
        assert s.anthropic_api_key == ""
        assert s.google_api_key == ""


class TestSettingsEnvOverride:
    def test_mode_from_env(self, monkeypatch):
        monkeypatch.setenv("HYPOMNEMA_MODE", "server")
        assert Settings().mode == "server"

    def test_db_path_from_env(self, monkeypatch):
        monkeypatch.setenv("HYPOMNEMA_DB_PATH", "/tmp/test.db")
        assert Settings().db_path == Path("/tmp/test.db")

    def test_embedding_dim_from_env(self, monkeypatch):
        monkeypatch.setenv("HYPOMNEMA_EMBEDDING_DIM", "768")
        assert Settings().embedding_dim == 768

    def test_llm_provider_from_env(self, monkeypatch):
        monkeypatch.setenv("HYPOMNEMA_LLM_PROVIDER", "claude")
        assert Settings().llm_provider == "claude"

    def test_host_from_env_in_server_mode(self, monkeypatch):
        monkeypatch.setenv("HYPOMNEMA_MODE", "server")
        monkeypatch.setenv("HYPOMNEMA_HOST", "10.0.0.5")
        assert Settings().host == "10.0.0.5"

    def test_server_mode_defaults_to_all_interfaces(self, monkeypatch):
        monkeypatch.setenv("HYPOMNEMA_MODE", "server")
        assert Settings().host == "0.0.0.0"

    def test_host_forced_localhost_in_local_mode(self, monkeypatch):
        monkeypatch.setenv("HYPOMNEMA_MODE", "local")
        monkeypatch.setenv("HYPOMNEMA_HOST", "0.0.0.0")
        assert Settings().host == "127.0.0.1"

    def test_port_from_env(self, monkeypatch):
        monkeypatch.setenv("HYPOMNEMA_PORT", "9000")
        assert Settings().port == 9000

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("HYPOMNEMA_ANTHROPIC_API_KEY", "sk-test-123")
        assert Settings().anthropic_api_key == "sk-test-123"


class TestSettingsValidation:
    def test_invalid_mode_rejected(self):
        with pytest.raises(ValidationError, match="mode"):
            Settings(mode="distributed")

    def test_embedding_dim_zero_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            Settings(embedding_dim=0)

    def test_embedding_dim_negative_rejected(self):
        with pytest.raises(ValidationError, match="positive"):
            Settings(embedding_dim=-128)

    def test_invalid_llm_provider_rejected(self):
        with pytest.raises(ValidationError, match="llm_provider"):
            Settings(llm_provider="nonexistent")

    def test_triage_threshold_above_one_rejected(self):
        with pytest.raises(ValidationError, match="triage_threshold"):
            Settings(triage_threshold=1.5)

    def test_triage_threshold_negative_rejected(self):
        with pytest.raises(ValidationError, match="triage_threshold"):
            Settings(triage_threshold=-0.1)

    def test_triage_threshold_boundaries_accepted(self):
        assert Settings(triage_threshold=0.0).triage_threshold == 0.0
        assert Settings(triage_threshold=1.0).triage_threshold == 1.0
