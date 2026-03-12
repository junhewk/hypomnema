"""Settings API — manage LLM provider config and API keys."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from hypomnema.api.deps import AppSettings, DB, FernetKey, LLMLock
from hypomnema.api.schemas import (
    EmbeddingProviderInfo,
    ProviderInfo,
    ProvidersResponse,
    SettingsResponse,
    SettingsUpdate,
)
from hypomnema.crypto import mask_key
from hypomnema.db.settings_store import get_all_settings, set_setting
from hypomnema.llm.factory import api_key_for_provider, base_url_for_provider, build_llm

router = APIRouter(prefix="/api/settings", tags=["settings"])

_ENCRYPTED_KEYS = {"anthropic_api_key", "google_api_key", "openai_api_key"}
_VALID_LLM_PROVIDERS = {"claude", "google", "openai", "ollama"}


def _build_response(settings: AppSettings, masked_keys: dict[str, str]) -> SettingsResponse:
    return SettingsResponse(
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        anthropic_api_key=masked_keys.get("anthropic_api_key", mask_key(settings.anthropic_api_key) if settings.anthropic_api_key else ""),
        google_api_key=masked_keys.get("google_api_key", mask_key(settings.google_api_key) if settings.google_api_key else ""),
        openai_api_key=masked_keys.get("openai_api_key", mask_key(settings.openai_api_key) if settings.openai_api_key else ""),
        ollama_base_url=settings.ollama_base_url,
        openai_base_url=settings.openai_base_url,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
    )


@router.get("", response_model=SettingsResponse)
async def get_settings(
    settings: AppSettings,
    db: DB,
) -> SettingsResponse:
    """Return current settings with masked API keys."""
    from hypomnema.db.settings_store import get_all_settings_masked

    db_masked = await get_all_settings_masked(db)
    # Merge: for API key fields, prefer DB masked values if present
    masked_keys: dict[str, str] = {}
    for key in _ENCRYPTED_KEYS:
        if key in db_masked:
            masked_keys[key] = db_masked[key]
    return _build_response(settings, masked_keys)


@router.put("", response_model=SettingsResponse)
async def update_settings(
    body: SettingsUpdate,
    request: Request,
    settings: AppSettings,
    db: DB,
    fernet_key: FernetKey,
    llm_lock: LLMLock,
) -> SettingsResponse:
    """Update LLM-related settings. Hot-swaps the LLM client."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Reject embedding changes
    embedding_fields = {"embedding_provider", "embedding_model", "embedding_dim"}
    if embedding_fields & set(updates):
        raise HTTPException(status_code=400, detail="Embedding config cannot be changed at runtime")

    # Validate LLM provider
    if "llm_provider" in updates and updates["llm_provider"] not in _VALID_LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid LLM provider: {updates['llm_provider']}")

    # Persist each field to DB
    for key, value in updates.items():
        await set_setting(
            db, key, value,
            fernet_key=fernet_key,
            encrypt_value=key in _ENCRYPTED_KEYS,
        )

    # Reload full settings from DB
    db_settings = await get_all_settings(db, fernet_key=fernet_key)

    from hypomnema.config import Settings

    new_settings = Settings.with_db_overrides(settings, db_settings)
    request.app.state.settings = new_settings

    # Hot-swap LLM
    provider = new_settings.llm_provider
    if provider != "mock":
        api_key = api_key_for_provider(provider, new_settings)
        base_url = base_url_for_provider(provider, new_settings)
        new_llm = build_llm(provider, api_key=api_key, model=new_settings.llm_model, base_url=base_url)
        async with llm_lock:
            request.app.state.llm = new_llm

    # Build masked response from already-decrypted settings
    masked_keys = {
        k: mask_key(v) for k, v in db_settings.items() if k in _ENCRYPTED_KEYS and v
    }
    return _build_response(new_settings, masked_keys)


@router.get("/providers", response_model=ProvidersResponse)
async def get_providers() -> ProvidersResponse:
    """Return available provider metadata (excludes mock)."""
    return ProvidersResponse(
        llm=[
            ProviderInfo(id="claude", name="Anthropic Claude", requires_key=True, default_model="claude-sonnet-4-20250514"),
            ProviderInfo(id="google", name="Google Gemini", requires_key=True, default_model="gemini-2.0-flash"),
            ProviderInfo(id="openai", name="OpenAI", requires_key=True, default_model="gpt-4o"),
            ProviderInfo(id="ollama", name="Ollama (local)", requires_key=False, default_model="llama3.1"),
        ],
        embedding=[
            EmbeddingProviderInfo(id="local", name="Local (sentence-transformers)", default_dimension=384, requires_key=False),
            EmbeddingProviderInfo(id="openai", name="OpenAI Embeddings", default_dimension=1536, requires_key=True),
            EmbeddingProviderInfo(id="google", name="Google Embeddings", default_dimension=768, requires_key=True),
        ],
    )


