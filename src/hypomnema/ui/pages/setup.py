"""Setup page — first-run wizard for embedding and LLM provider configuration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from nicegui import app, ui

from hypomnema.ui.layout import page_layout

if TYPE_CHECKING:
    from hypomnema.embeddings.base import EmbeddingModel
from hypomnema.ui.utils import (
    API_KEY_FIELD,
    DEFAULT_LLM_MODELS,
    LLM_MODELS,
    LLM_PROVIDERS,
    get_db,
)

logger = logging.getLogger(__name__)

_EMBEDDING_PROVIDERS = {
    "openai": "OpenAI Embeddings",
    "google": "Google Embeddings",
}

@ui.page("/setup")
async def setup_page() -> None:
    """First-run setup wizard."""
    db = get_db()
    fernet_key = getattr(app.state, "fernet_key", None)

    # Check if already set up — redirect to home
    if db is not None:
        cursor = await db.execute("SELECT value FROM settings WHERE key = 'setup_complete'")
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            ui.navigate.to("/")
            return

    # Wizard state
    wizard_state: dict[str, object] = {
        "emb_provider": "google",
        "emb_api_key": "",
        "emb_validated": False,
        "llm_provider": "google",
        "llm_model": "gemini-2.5-flash",
        "llm_custom_model": "",
        "llm_api_key": "",
        "llm_tested": False,
        "ollama_base_url": "http://localhost:11434",
        "openai_base_url": "",
    }

    with page_layout("Setup"):
        ui.label("hypomnema").classes(
            "text-display-lg tracking-wider uppercase text-center w-full mb-1"
        ).style("letter-spacing: 0.15em")
        ui.label("first-run setup").classes(
            "text-xs text-center w-full mb-6"
        ).style("color: #3d4252; letter-spacing: 0.1em")

        with ui.stepper().props('dark vertical header-nav').classes("w-full") as stepper:

            # ── Step 1: Embedding Provider ──────────────────────
            with ui.step("Embedding Provider").props('icon="memory"'):
                ui.label(
                    "Choose how document and engram embeddings are computed. "
                    "An API key is required."
                ).classes("text-xs mb-4").style("color: #636978")

                emb_provider_radio = ui.radio(
                    options=_EMBEDDING_PROVIDERS,
                    value="google",
                ).props('dark color="grey-7"').classes("mb-3")

                # API key for cloud providers
                emb_key_input = ui.input(
                    label="API Key",
                    placeholder="Enter API key for embedding provider...",
                    password=True,
                    password_toggle_button=True,
                ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")
                emb_key_input.set_visibility(True)

                emb_status = ui.label("").classes("text-xs mb-3").style("color: #636978")

                def _on_emb_provider_change(e: object) -> None:
                    provider = emb_provider_radio.value
                    wizard_state["emb_provider"] = provider
                    wizard_state["emb_validated"] = False
                    emb_status.set_text("")

                emb_provider_radio.on("update:model-value", _on_emb_provider_change)

                async def _validate_embedding() -> None:
                    """Validate the embedding provider connection."""
                    provider = str(wizard_state["emb_provider"])

                    api_key = emb_key_input.value or ""
                    if not api_key:
                        emb_status.style("color: #e06c75")
                        emb_status.set_text("API key is required for cloud providers.")
                        return

                    wizard_state["emb_api_key"] = api_key
                    emb_status.style("color: #636978")
                    emb_status.set_text("Validating...")

                    try:
                        from hypomnema.embeddings.factory import EMBEDDING_DEFAULTS

                        _, default_model = EMBEDDING_DEFAULTS[provider]

                        emb_model: EmbeddingModel
                        if provider == "openai":
                            from hypomnema.embeddings.openai import OpenAIEmbeddingModel

                            emb_model = OpenAIEmbeddingModel(api_key=api_key, model=default_model)
                        elif provider == "google":
                            from hypomnema.embeddings.google import GoogleEmbeddingModel

                            emb_model = GoogleEmbeddingModel(api_key=api_key, model=default_model)
                        else:
                            emb_status.style("color: #e06c75")
                            emb_status.set_text(f"Unknown provider: {provider}")
                            return

                        # Test with a simple embed call
                        await asyncio.to_thread(emb_model.embed, ["wired"])

                        wizard_state["emb_validated"] = True
                        emb_status.style("color: #56c9a0")
                        emb_status.set_text(f"{default_model} is reachable.")
                    except Exception as exc:
                        wizard_state["emb_validated"] = False
                        emb_status.style("color: #e06c75")
                        emb_status.set_text(f"Validation failed: {exc}")

                ui.button(
                    "Validate",
                    on_click=_validate_embedding,
                ).props('flat dense color="grey-5"').classes("text-xs mb-4")

                with ui.stepper_navigation():
                    async def _next_step_1() -> None:
                        if not wizard_state["emb_validated"]:
                            emb_status.style("color: #e06c75")
                            emb_status.set_text(
                                "Please validate your embedding provider before continuing."
                            )
                            return

                        wizard_state["emb_api_key"] = emb_key_input.value or ""
                        if not wizard_state["emb_api_key"]:
                            emb_status.style("color: #e06c75")
                            emb_status.set_text("API key is required.")
                            return

                        stepper.next()

                    ui.button("Next", on_click=_next_step_1).props(
                        'flat dense color="grey-5"'
                    ).classes("text-xs")

            # ── Step 2: LLM Provider ────────────────────────────
            with ui.step("LLM Provider").props('icon="smart_toy"'):
                ui.label(
                    "Choose the LLM that powers ontology extraction, "
                    "entity normalization, and edge generation."
                ).classes("text-xs mb-4").style("color: #636978")

                llm_provider_select = ui.select(
                    options=LLM_PROVIDERS,
                    value="google",
                    label="Provider",
                ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")

                llm_model_select = ui.select(
                    options=LLM_MODELS["google"],
                    value="gemini-2.5-flash",
                    label="Model",
                ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")

                llm_custom_model_input = ui.input(
                    label="Custom model name",
                    placeholder="e.g. llama3.1",
                ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")
                llm_custom_model_input.set_visibility(False)

                llm_key_input = ui.input(
                    label="API Key",
                    placeholder="Enter API key...",
                    password=True,
                    password_toggle_button=True,
                ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")

                llm_ollama_url = ui.input(
                    label="Ollama Base URL",
                    value="http://localhost:11434",
                    placeholder="http://localhost:11434",
                ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")
                llm_ollama_url.set_visibility(False)

                llm_openai_url = ui.input(
                    label="OpenAI Base URL (optional)",
                    placeholder="Leave empty for default",
                ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")
                llm_openai_url.set_visibility(False)

                llm_status = ui.label("").classes("text-xs mb-3").style("color: #636978")

                def _on_llm_provider_change(e: object) -> None:
                    provider = llm_provider_select.value
                    wizard_state["llm_provider"] = provider
                    wizard_state["llm_tested"] = False
                    models = LLM_MODELS.get(provider, [])

                    if models:
                        llm_model_select.options = models
                        llm_model_select.value = DEFAULT_LLM_MODELS.get(provider, models[0])
                        llm_model_select.set_visibility(True)
                    else:
                        llm_model_select.options = ["(custom)"]
                        llm_model_select.value = "(custom)"
                        llm_model_select.set_visibility(provider != "ollama")

                    llm_custom_model_input.set_visibility(provider == "ollama")
                    llm_custom_model_input.value = DEFAULT_LLM_MODELS.get(provider, "")
                    llm_key_input.set_visibility(provider in API_KEY_FIELD)
                    llm_key_input.value = ""
                    llm_ollama_url.set_visibility(provider == "ollama")
                    llm_openai_url.set_visibility(provider == "openai")
                    llm_status.set_text("")

                llm_provider_select.on("update:model-value", _on_llm_provider_change)

                async def _test_llm_connection() -> None:
                    """Test the selected LLM connection."""
                    provider = str(llm_provider_select.value)
                    model = (
                        llm_custom_model_input.value
                        if provider == "ollama"
                        else llm_model_select.value
                    )
                    if model == "(custom)":
                        model = ""
                    model = model or DEFAULT_LLM_MODELS.get(provider, "")
                    api_key = llm_key_input.value or ""

                    if provider in API_KEY_FIELD and not api_key:
                        llm_status.style("color: #e06c75")
                        llm_status.set_text("API key is required.")
                        return

                    llm_status.style("color: #636978")
                    llm_status.set_text("Testing connection...")

                    try:
                        from hypomnema.llm.factory import build_llm

                        base_url = ""
                        if provider == "ollama":
                            base_url = llm_ollama_url.value or "http://localhost:11434"
                        elif provider == "openai":
                            base_url = llm_openai_url.value or ""

                        llm = build_llm(
                            provider,
                            api_key=api_key,
                            model=model,
                            base_url=base_url,
                        )
                        await llm.complete(
                            "Reply with exactly wired.",
                            system="You are a connectivity probe. Reply with exactly wired.",
                        )

                        wizard_state["llm_tested"] = True
                        wizard_state["llm_provider"] = provider
                        wizard_state["llm_model"] = model
                        wizard_state["llm_api_key"] = api_key
                        wizard_state["ollama_base_url"] = (
                            llm_ollama_url.value or "http://localhost:11434"
                        )
                        wizard_state["openai_base_url"] = llm_openai_url.value or ""

                        llm_status.style("color: #56c9a0")
                        llm_status.set_text(f"Connected: {model} is reachable.")
                    except Exception as exc:
                        wizard_state["llm_tested"] = False
                        llm_status.style("color: #e06c75")
                        llm_status.set_text(f"Connection failed: {exc}")

                ui.button(
                    "Test Connection",
                    on_click=_test_llm_connection,
                ).props('flat dense color="grey-5"').classes("text-xs mb-4")

                with ui.stepper_navigation():
                    ui.button("Back", on_click=stepper.previous).props(
                        'flat dense color="grey-7"'
                    ).classes("text-xs")

                    async def _complete_setup() -> None:
                        """Persist all settings and complete setup."""
                        if db is None or fernet_key is None:
                            ui.notify("Database not ready", type="negative")
                            return

                        # Gather final values from widgets
                        provider = str(llm_provider_select.value)
                        model = (
                            llm_custom_model_input.value
                            if provider == "ollama"
                            else llm_model_select.value
                        )
                        if model == "(custom)":
                            model = DEFAULT_LLM_MODELS.get(provider, "")
                        model = model or DEFAULT_LLM_MODELS.get(provider, "")
                        api_key = llm_key_input.value or ""
                        ollama_base_url = llm_ollama_url.value or "http://localhost:11434"
                        openai_base_url = llm_openai_url.value or ""

                        if provider in API_KEY_FIELD and not api_key:
                            llm_status.style("color: #e06c75")
                            llm_status.set_text(
                                "Please enter an API key and test the connection first."
                            )
                            return

                        if not wizard_state["llm_tested"]:
                            llm_status.style("color: #d4b06a")
                            llm_status.set_text(
                                "Please test the connection before completing setup."
                            )
                            return

                        llm_status.style("color: #636978")
                        llm_status.set_text("Completing setup...")

                        try:
                            from hypomnema.db.settings_store import get_all_settings, set_setting
                            from hypomnema.embeddings.factory import EMBEDDING_DEFAULTS, build_embeddings

                            # ── Save embedding settings ──
                            emb_provider = str(wizard_state["emb_provider"])
                            emb_dim, emb_model = EMBEDDING_DEFAULTS[emb_provider]

                            await set_setting(
                                db, "embedding_provider", emb_provider,
                                fernet_key=fernet_key, encrypt_value=False,
                            )
                            await set_setting(
                                db, "embedding_dim", str(emb_dim),
                                fernet_key=fernet_key, encrypt_value=False,
                            )
                            await set_setting(
                                db, "embedding_model", emb_model,
                                fernet_key=fernet_key, encrypt_value=False,
                            )

                            # Save embedding API key if cloud
                            emb_api_key = str(wizard_state.get("emb_api_key", ""))
                            if emb_api_key:
                                if emb_provider == "openai":
                                    await set_setting(
                                        db, "openai_api_key", emb_api_key,
                                        fernet_key=fernet_key, encrypt_value=True,
                                    )
                                elif emb_provider == "google":
                                    await set_setting(
                                        db, "google_api_key", emb_api_key,
                                        fernet_key=fernet_key, encrypt_value=True,
                                    )

                            # ── Save LLM settings ──
                            await set_setting(
                                db, "llm_provider", provider,
                                fernet_key=fernet_key, encrypt_value=False,
                            )
                            await set_setting(
                                db, "llm_model", model,
                                fernet_key=fernet_key, encrypt_value=False,
                            )

                            # Save LLM API key
                            if api_key:
                                key_field = API_KEY_FIELD.get(provider, "")
                                if key_field:
                                    await set_setting(
                                        db, key_field, api_key,
                                        fernet_key=fernet_key, encrypt_value=True,
                                    )

                            # Save base URLs
                            if provider == "ollama":
                                await set_setting(
                                    db, "ollama_base_url", ollama_base_url,
                                    fernet_key=fernet_key, encrypt_value=False,
                                )
                            if provider == "openai" and openai_base_url:
                                await set_setting(
                                    db, "openai_base_url", openai_base_url,
                                    fernet_key=fernet_key, encrypt_value=False,
                                )

                            # ── Create vec tables ──
                            from hypomnema.db.schema import ensure_vec_tables

                            await ensure_vec_tables(db, emb_dim)

                            # ── Reload settings and initialize services ──
                            from hypomnema.config import Settings
                            from hypomnema.llm.factory import (
                                api_key_for_provider,
                                base_url_for_provider,
                                build_llm,
                            )

                            db_settings = await get_all_settings(db, fernet_key=fernet_key)
                            new_settings = Settings.with_db_overrides(app.state.settings, db_settings)
                            app.state.settings = new_settings

                            # Initialize embeddings
                            app.state.embeddings = build_embeddings(new_settings)

                            # Initialize LLM
                            resolved_key = api_key_for_provider(provider, new_settings)
                            resolved_url = base_url_for_provider(provider, new_settings)
                            async with app.state.llm_lock:
                                app.state.llm = build_llm(
                                    provider,
                                    api_key=resolved_key,
                                    model=new_settings.llm_model,
                                    base_url=resolved_url,
                                )

                            # Start feed scheduler
                            from hypomnema.scheduler.cron import FeedScheduler

                            scheduler = FeedScheduler(
                                new_settings.db_path,
                                sqlite_vec_path=new_settings.sqlite_vec_path,
                                triage_threshold=new_settings.triage_threshold,
                                feed_timeout=new_settings.feed_fetch_timeout,
                                embeddings=app.state.embeddings,
                            )
                            await scheduler.load_jobs()
                            scheduler.start()
                            app.state.scheduler = scheduler

                            # Start ontology queue
                            from hypomnema.ontology.queue import OntologyQueue

                            old_queue = getattr(app.state, "ontology_queue", None)
                            if old_queue is not None:
                                await old_queue.shutdown()
                            ontology_queue = OntologyQueue(app)
                            ontology_queue.start()
                            app.state.ontology_queue = ontology_queue

                            # ── Mark setup complete ──
                            await set_setting(
                                db, "setup_complete", "1",
                                fernet_key=fernet_key, encrypt_value=False,
                            )

                            ui.notify("Setup complete!", type="positive")
                            ui.navigate.to("/")

                        except Exception as exc:
                            logger.exception("Setup failed")
                            llm_status.style("color: #e06c75")
                            llm_status.set_text(f"Setup failed: {exc}")
                            ui.notify(f"Setup failed: {exc}", type="negative")

                    ui.button("Complete Setup", on_click=_complete_setup).props(
                        'flat dense color="grey-5"'
                    ).classes("text-xs")
