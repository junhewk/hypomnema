"""Pure catalog tests for settings provider defaults."""

from hypomnema.api import settings as settings_api


def test_google_gemini_is_the_base_llm_recommendation() -> None:
    assert settings_api._BASE_LLM_PROVIDER == "google"
    assert settings_api._BASE_LLM_MODEL == "gemini-2.5-flash"
    assert settings_api._DEFAULT_LLM_MODELS["google"] == "gemini-2.5-flash"
    assert settings_api._LLM_PROVIDER_CATALOG[0].id == "google"
    assert settings_api._LLM_PROVIDER_CATALOG[0].default_model == "gemini-2.5-flash"
