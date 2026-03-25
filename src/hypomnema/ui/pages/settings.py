"""Settings page — LLM provider config, embedding info, and feed management."""

from __future__ import annotations

import asyncio
import logging

from nicegui import app, ui

from hypomnema.ui.layout import page_layout
from hypomnema.ui.utils import (
    API_KEY_FIELD,
    DEFAULT_LLM_MODELS,
    LLM_MODELS,
    LLM_PROVIDERS,
)

logger = logging.getLogger(__name__)

_FEED_TYPES = ["rss", "scrape", "youtube"]


@ui.page("/settings")
async def settings_page() -> None:
    """Settings management page."""
    db = app.state.db
    fernet_key = getattr(app.state, "fernet_key", None)
    settings = getattr(app.state, "settings", None)

    # Load current settings from DB (masked)
    masked_settings: dict[str, str] = {}
    if db is not None:
        from hypomnema.db.settings_store import get_all_settings_masked

        masked_settings = await get_all_settings_masked(db)

    # Determine current values
    current_provider = (
        masked_settings.get("llm_provider")
        or (settings.llm_provider if settings else "mock")
    )
    current_model = (
        masked_settings.get("llm_model")
        or (settings.llm_model if settings else "")
    )

    with page_layout("Settings"):
        ui.label("Settings").classes("text-lg font-medium mb-6")

        # ── LLM Provider Section ────────────────────────────────
        ui.label("LLM Provider").classes(
            "text-xs tracking-wider uppercase mb-3"
        ).style("color: #7eb8da; letter-spacing: 0.1em")

        with ui.card().classes("w-full mb-6").style("background: #111"):
            # Provider selector
            provider_select = ui.select(
                options=LLM_PROVIDERS,
                value=current_provider,
                label="Provider",
            ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")

            # Model selector
            model_options = LLM_MODELS.get(current_provider, [])
            model_select = ui.select(
                options=model_options if model_options else ["(custom)"],
                value=current_model if current_model in model_options else (
                    model_options[0] if model_options else "(custom)"
                ),
                label="Model",
            ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")

            # Custom model input for ollama
            custom_model_input = ui.input(
                label="Custom model name",
                value=current_model if current_provider == "ollama" else "",
                placeholder="e.g. llama3.1",
            ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")
            custom_model_input.set_visibility(current_provider == "ollama")

            # API key input
            api_key_input = ui.input(
                label="API Key",
                placeholder="Enter API key...",
                password=True,
                password_toggle_button=True,
            ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")
            api_key_input.set_visibility(current_provider in API_KEY_FIELD)

            # Ollama base URL
            ollama_url_input = ui.input(
                label="Ollama Base URL",
                value=masked_settings.get("ollama_base_url", "http://localhost:11434"),
                placeholder="http://localhost:11434",
            ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")
            ollama_url_input.set_visibility(current_provider == "ollama")

            # OpenAI base URL (for compatible APIs)
            openai_url_input = ui.input(
                label="OpenAI Base URL (optional, for compatible APIs)",
                value=masked_settings.get("openai_base_url", ""),
                placeholder="Leave empty for default",
            ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")
            openai_url_input.set_visibility(current_provider == "openai")

            # Status line
            llm_status = ui.label("").classes("text-xs mb-3").style("color: #6b6b6b")

            def _on_provider_change(e: object) -> None:
                """Update model options when provider changes."""
                provider = provider_select.value
                models = LLM_MODELS.get(provider, [])

                if models:
                    model_select.options = models
                    model_select.value = DEFAULT_LLM_MODELS.get(provider, models[0])
                else:
                    model_select.options = ["(custom)"]
                    model_select.value = "(custom)"
                model_select.update()

                api_key_input.set_visibility(provider in API_KEY_FIELD)
                api_key_input.value = ""
                custom_model_input.set_visibility(provider == "ollama")
                ollama_url_input.set_visibility(provider == "ollama")
                openai_url_input.set_visibility(provider == "openai")
                llm_status.set_text("")

            provider_select.on("update:model-value", _on_provider_change)

            with ui.row().classes("gap-2"):
                async def _test_connection() -> None:
                    """Test the selected LLM provider connection."""
                    provider = provider_select.value
                    if provider == "mock":
                        llm_status.style("color: #4caf50")
                        llm_status.set_text("Mock provider requires no connection.")
                        return

                    llm_status.style("color: #6b6b6b")
                    llm_status.set_text("Testing connection...")

                    model = (
                        custom_model_input.value
                        if provider == "ollama"
                        else model_select.value
                    )
                    if model == "(custom)":
                        model = ""

                    api_key = api_key_input.value or ""

                    # Resolve API key: use entered value, or fall back to stored
                    if not api_key and fernet_key and db:
                        from hypomnema.db.settings_store import get_setting

                        key_field = API_KEY_FIELD.get(provider, "")
                        if key_field:
                            stored = await get_setting(db, key_field, fernet_key=fernet_key)
                            if stored:
                                api_key = stored

                    try:
                        from hypomnema.llm.factory import build_llm

                        base_url = ""
                        if provider == "ollama":
                            base_url = ollama_url_input.value or "http://localhost:11434"
                        elif provider == "openai":
                            base_url = openai_url_input.value or ""

                        llm = build_llm(
                            provider,
                            api_key=api_key,
                            model=model or DEFAULT_LLM_MODELS.get(provider, ""),
                            base_url=base_url,
                        )
                        await llm.complete(
                            "Reply with exactly wired.",
                            system="You are a connectivity probe. Reply with exactly wired.",
                        )
                        llm_status.style("color: #4caf50")
                        llm_status.set_text(
                            f"Connected: {model or DEFAULT_LLM_MODELS.get(provider, provider)} is reachable."
                        )
                    except Exception as exc:
                        llm_status.style("color: #ef5350")
                        llm_status.set_text(f"Connection failed: {exc}")

                ui.button(
                    "Test Connection",
                    on_click=_test_connection,
                ).props('flat dense color="grey-5"').classes("text-xs")

                async def _save_llm_settings() -> None:
                    """Persist LLM settings to DB and hot-swap the client."""
                    if db is None or fernet_key is None:
                        ui.notify("Database not ready", type="negative")
                        return

                    from hypomnema.db.settings_store import set_setting

                    provider = provider_select.value
                    model = (
                        custom_model_input.value
                        if provider == "ollama"
                        else model_select.value
                    )
                    if model == "(custom)":
                        model = DEFAULT_LLM_MODELS.get(provider, "")

                    # Save provider and model
                    await set_setting(db, "llm_provider", provider, fernet_key=fernet_key, encrypt_value=False)
                    await set_setting(db, "llm_model", model, fernet_key=fernet_key, encrypt_value=False)

                    # Save API key if entered (non-empty, not masked)
                    api_key = api_key_input.value or ""
                    key_field = API_KEY_FIELD.get(provider, "")
                    if api_key and key_field and not api_key.startswith("****"):
                        await set_setting(db, key_field, api_key, fernet_key=fernet_key, encrypt_value=True)

                    # Save base URLs
                    if provider == "ollama":
                        await set_setting(
                            db, "ollama_base_url",
                            ollama_url_input.value or "http://localhost:11434",
                            fernet_key=fernet_key, encrypt_value=False,
                        )
                    if provider == "openai" and openai_url_input.value:
                        await set_setting(
                            db, "openai_base_url",
                            openai_url_input.value,
                            fernet_key=fernet_key, encrypt_value=False,
                        )

                    # Reload settings and hot-swap LLM
                    from hypomnema.config import Settings
                    from hypomnema.db.settings_store import get_all_settings
                    from hypomnema.llm.factory import (
                        api_key_for_provider,
                        base_url_for_provider,
                        build_llm,
                    )

                    db_settings = await get_all_settings(db, fernet_key=fernet_key)
                    new_settings = Settings.with_db_overrides(app.state.settings, db_settings)
                    app.state.settings = new_settings

                    if provider != "mock":
                        resolved_key = api_key_for_provider(provider, new_settings)
                        resolved_url = base_url_for_provider(provider, new_settings)
                        new_llm = build_llm(
                            provider,
                            api_key=resolved_key,
                            model=new_settings.llm_model,
                            base_url=resolved_url,
                        )
                        llm_lock = getattr(app.state, "llm_lock", None)
                        if llm_lock:
                            async with llm_lock:
                                app.state.llm = new_llm
                        else:
                            app.state.llm = new_llm
                    else:
                        from hypomnema.llm.mock import MockLLMClient

                        app.state.llm = MockLLMClient()

                    ui.notify("LLM settings saved", type="positive")
                    llm_status.style("color: #4caf50")
                    llm_status.set_text(f"Saved: {provider} / {model}")

                ui.button(
                    "Save",
                    on_click=_save_llm_settings,
                ).props('flat dense color="grey-5"').classes("text-xs")

        # ── Embedding Provider Section ──────────────────────────
        ui.label("Embedding Provider").classes(
            "text-xs tracking-wider uppercase mb-3"
        ).style("color: #7eb8da; letter-spacing: 0.1em")

        with ui.card().classes("w-full mb-6").style("background: #111"):
            emb_provider = masked_settings.get(
                "embedding_provider",
                settings.embedding_provider if settings else "local",
            )
            emb_model = masked_settings.get(
                "embedding_model",
                settings.embedding_model if settings else "all-MiniLM-L6-v2",
            )
            emb_dim = masked_settings.get(
                "embedding_dim",
                str(settings.embedding_dim) if settings else "384",
            )

            with ui.row().classes("items-center gap-4 mb-2"):
                ui.label("Provider:").classes("text-xs").style("color: #6b6b6b")
                ui.label(emb_provider).classes("text-xs font-medium")
            with ui.row().classes("items-center gap-4 mb-2"):
                ui.label("Model:").classes("text-xs").style("color: #6b6b6b")
                ui.label(emb_model).classes("text-xs font-medium")
            with ui.row().classes("items-center gap-4 mb-2"):
                ui.label("Dimension:").classes("text-xs").style("color: #6b6b6b")
                ui.label(str(emb_dim)).classes("text-xs font-medium")

            # Embedding change status with auto-refresh
            emb_status_container = ui.element("div").classes("mt-2")

            def _update_emb_status() -> None:
                emb_status_container.clear()
                status = getattr(app.state, "embedding_change_status", None)
                if status and status.status == "in_progress":
                    with emb_status_container, ui.row().classes("items-center gap-2"):
                        ui.spinner(size="sm").props('color="grey-5"')
                        ui.label(
                            f"Rebuilding... {status.processed}/{status.total}"
                        ).classes("text-xs").style("color: #ff9800")
                elif status and status.status == "failed":
                    with emb_status_container:
                        ui.label(
                            f"Rebuild failed: {status.error or 'unknown'}"
                        ).classes("text-xs").style("color: #ef5350")
                    emb_poll_timer.deactivate()
                elif status and status.status == "complete" and status.total > 0:
                    with emb_status_container:
                        ui.label(
                            f"Rebuild complete ({status.processed} documents)"
                        ).classes("text-xs").style("color: #4caf50")
                    emb_poll_timer.deactivate()
                else:
                    emb_poll_timer.deactivate()

            emb_poll_timer = ui.timer(3.0, _update_emb_status, active=False)

            # Start polling if currently in progress
            emb_change_status = getattr(app.state, "embedding_change_status", None)
            if emb_change_status and emb_change_status.status == "in_progress":
                emb_poll_timer.activate()
                _update_emb_status()

            async def _change_embedding() -> None:
                """Show warning dialog for embedding provider change."""
                with ui.dialog() as dialog, ui.card().style("background: #111; min-width: 350px"):
                    ui.label("Change Embedding Provider").classes("text-sm font-medium mb-2")
                    ui.label(
                        "This will delete all engrams, edges, and projections, "
                        "then reprocess every document through the ontology pipeline. "
                        "This can take a long time."
                    ).classes("text-xs mb-4").style("color: #ff9800")

                    from hypomnema.embeddings.factory import EMBEDDING_DEFAULTS

                    emb_options = {
                        "local": "Local (sentence-transformers)",
                        "openai": "OpenAI Embeddings",
                        "google": "Google Embeddings",
                    }
                    new_emb_provider = ui.select(
                        options=emb_options,
                        value=emb_provider,
                        label="New Embedding Provider",
                    ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")

                    new_emb_api_key = ui.input(
                        label="API Key (for cloud providers)",
                        password=True,
                        password_toggle_button=True,
                    ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")
                    new_emb_api_key.set_visibility(emb_provider != "local")

                    def _on_emb_change(e: object) -> None:
                        new_emb_api_key.set_visibility(new_emb_provider.value != "local")

                    new_emb_provider.on("update:model-value", _on_emb_change)

                    with ui.row().classes("gap-2 justify-end"):
                        ui.button("Cancel", on_click=dialog.close).props(
                            'flat dense color="grey-5"'
                        ).classes("text-xs")

                        async def _confirm_change() -> None:
                            """Execute embedding provider change via API."""
                            dialog.close()
                            provider = new_emb_provider.value
                            api_key = new_emb_api_key.value or None

                            try:
                                # Call the change-embedding logic directly
                                from hypomnema.db.schema import (
                                    create_vec_tables,
                                    drop_vec_tables,
                                    reset_knowledge_graph,
                                )
                                from hypomnema.db.settings_store import get_all_settings, set_setting
                                from hypomnema.embeddings.factory import build_embeddings

                                assert fernet_key is not None
                                dim, model = EMBEDDING_DEFAULTS[provider]

                                # Store new API key if provided
                                if api_key and provider == "openai":
                                    await set_setting(
                                        db, "openai_api_key", api_key,
                                        fernet_key=fernet_key, encrypt_value=True,
                                    )
                                if api_key and provider == "google":
                                    await set_setting(
                                        db, "google_api_key", api_key,
                                        fernet_key=fernet_key, encrypt_value=True,
                                    )

                                # Reset and rebuild
                                await reset_knowledge_graph(db)
                                await drop_vec_tables(db)
                                await create_vec_tables(db, dim)

                                for key, value in [
                                    ("embedding_provider", provider),
                                    ("embedding_dim", str(dim)),
                                    ("embedding_model", model),
                                ]:
                                    await set_setting(
                                        db, key, value,
                                        fernet_key=fernet_key, encrypt_value=False,
                                    )

                                # Reload settings
                                from hypomnema.config import Settings

                                db_settings = await get_all_settings(db, fernet_key=fernet_key)
                                new_settings = Settings.with_db_overrides(app.state.settings, db_settings)
                                app.state.settings = new_settings
                                app.state.embeddings = build_embeddings(new_settings)

                                # Count docs and kick off reprocessing
                                cursor = await db.execute("SELECT count(*) FROM documents")
                                row = await cursor.fetchone()
                                await cursor.close()
                                total = row[0] if row else 0

                                from hypomnema.api.schemas import EmbeddingChangeStatus

                                if total == 0:
                                    app.state.embedding_change_status = EmbeddingChangeStatus(
                                        status="complete", total=0, processed=0
                                    )
                                else:
                                    app.state.embedding_change_status = EmbeddingChangeStatus(
                                        status="in_progress", total=total, processed=0
                                    )
                                    from hypomnema.api.settings import _reprocess_all_documents

                                    app.state.embedding_change_task = asyncio.create_task(
                                        _reprocess_all_documents(app, total)
                                    )

                                ui.notify(
                                    f"Embedding changed to {provider}. Rebuild started.",
                                    type="positive",
                                )
                                ui.navigate.to("/settings")

                            except Exception as exc:
                                ui.notify(f"Failed: {exc}", type="negative")

                        ui.button("Confirm Change", on_click=_confirm_change).props(
                            'flat dense color="orange"'
                        ).classes("text-xs")

                dialog.open()

            ui.button(
                "Change Embedding Provider",
                on_click=_change_embedding,
            ).props('flat dense color="orange"').classes("text-xs mt-2")

        # ── Feeds Section ───────────────────────────────────────
        ui.label("Feeds").classes(
            "text-xs tracking-wider uppercase mb-3"
        ).style("color: #7eb8da; letter-spacing: 0.1em")

        feeds_container = ui.column().classes("w-full gap-0 mb-4")

        async def _load_feeds() -> list[dict[str, object]]:
            """Load all feed sources from DB."""
            if db is None:
                return []
            cursor = await db.execute(
                "SELECT id, name, feed_type, url, schedule, active, last_fetched, created_at "
                "FROM feed_sources ORDER BY created_at DESC LIMIT 100"
            )
            rows = [dict(r) for r in await cursor.fetchall()]
            await cursor.close()
            return rows

        async def _render_feeds() -> None:
            """Render the feed list."""
            feeds_container.clear()
            feeds = await _load_feeds()

            with feeds_container:
                if not feeds:
                    ui.label("No feeds configured.").classes(
                        "text-muted text-xs py-4"
                    )
                else:
                    for feed in feeds:
                        _render_feed_card(feed)

        def _render_feed_card(feed: dict[str, object]) -> None:
            """Render a single feed source card."""
            feed_id = str(feed["id"])
            is_active = bool(feed.get("active", 1))

            with ui.card().classes("w-full mb-2").style(
                f"background: #111; border-left: 2px solid {'#4caf50' if is_active else '#ef5350'}"
            ), ui.row().classes("items-center justify-between w-full"):
                with ui.column().classes("gap-0"):
                    ui.label(str(feed["name"])).classes("text-xs font-medium")
                    with ui.row().classes("items-center gap-2"):
                        ui.label(str(feed["feed_type"])).classes("source-badge").style(
                            "color: #8fb87e; background: rgba(143,184,126,0.08)"
                        )
                        ui.label(str(feed["url"])).classes("text-xs").style(
                            "color: #6b6b6b; max-width: 300px; overflow: hidden; "
                            "text-overflow: ellipsis; white-space: nowrap"
                        )
                    ui.label(f"schedule: {feed['schedule']}").classes("text-xs").style(
                        "color: #4a4a4a"
                    )

                with ui.row().classes("items-center gap-2"):
                    async def _toggle_active(fid: str = feed_id, active: bool = is_active) -> None:
                        new_val = 0 if active else 1
                        await db.execute(
                            "UPDATE feed_sources SET active = ? WHERE id = ?",
                            (new_val, fid),
                        )
                        await db.commit()
                        await _render_feeds()

                    ui.switch(
                        value=is_active,
                        on_change=lambda _, fid=feed_id, act=is_active: asyncio.ensure_future(
                            _toggle_active(fid, act)
                        ),
                    ).props('dense color="green"')

                    async def _delete_feed(fid: str = feed_id) -> None:
                        await db.execute("DELETE FROM feed_sources WHERE id = ?", (fid,))
                        await db.commit()
                        ui.notify("Feed deleted", type="info")
                        await _render_feeds()

                    ui.button(
                        icon="delete",
                        on_click=lambda _, fid=feed_id: asyncio.ensure_future(
                            _delete_feed(fid)
                        ),
                    ).props('flat dense round size="sm" color="red-4"')

        await _render_feeds()

        # Add Feed form
        ui.label("Add Feed").classes(
            "text-xs tracking-wider uppercase mb-3 mt-4"
        ).style("color: #7eb8da; letter-spacing: 0.1em")

        with ui.card().classes("w-full mb-6").style("background: #111"):
            feed_name_input = ui.input(
                label="Name",
                placeholder="My RSS Feed",
            ).props('outlined dense dark color="grey-7"').classes("w-full mb-2")

            feed_type_select = ui.select(
                options=_FEED_TYPES,
                value="rss",
                label="Type",
            ).props('outlined dense dark color="grey-7"').classes("w-full mb-2")

            feed_url_input = ui.input(
                label="URL",
                placeholder="https://example.com/feed.xml",
            ).props('outlined dense dark color="grey-7"').classes("w-full mb-2")

            feed_schedule_input = ui.input(
                label="Schedule (cron)",
                value="0 */6 * * *",
                placeholder="0 */6 * * *",
            ).props('outlined dense dark color="grey-7"').classes("w-full mb-3")

            async def _add_feed() -> None:
                """Add a new feed source."""
                name = (feed_name_input.value or "").strip()
                url = (feed_url_input.value or "").strip()
                feed_type = feed_type_select.value
                schedule = (feed_schedule_input.value or "0 */6 * * *").strip()

                if not name:
                    ui.notify("Feed name is required", type="warning")
                    return
                if not url:
                    ui.notify("Feed URL is required", type="warning")
                    return
                if db is None:
                    ui.notify("Database not ready", type="negative")
                    return

                await db.execute(
                    "INSERT INTO feed_sources (name, feed_type, url, schedule, active) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (name, feed_type, url, schedule),
                )
                await db.commit()

                # Register with scheduler if available
                scheduler = getattr(app.state, "scheduler", None)
                if scheduler:
                    await scheduler.load_jobs()

                # Clear form
                feed_name_input.value = ""
                feed_url_input.value = ""
                feed_schedule_input.value = "0 */6 * * *"

                ui.notify(f"Feed '{name}' added", type="positive")
                await _render_feeds()

            ui.button(
                "Add Feed",
                on_click=_add_feed,
            ).props('flat dense color="grey-5"').classes("text-xs")
