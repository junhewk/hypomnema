"""Stream page — main document feed."""

from __future__ import annotations

from nicegui import app, ui

from hypomnema.ontology.heat import ALL_HEAT_TIERS
from hypomnema.ui.components.document_card import render_document_card
from hypomnema.ui.layout import page_layout
from hypomnema.ui.theme import HEAT_TIER_STYLES
from hypomnema.ui.utils import get_db


async def _load_documents(heat_filter: str | None = None) -> list[dict[str, object]]:
    """Fetch recent documents from the database, optionally filtered by heat tier."""
    db = get_db()
    if db is None:
        return []
    base = (
        "SELECT id, source_type, title, tidy_title, text, tidy_text, "
        "mime_type, created_at, processed, metadata, heat_score, heat_tier "
        "FROM documents"
    )
    if heat_filter and heat_filter in ALL_HEAT_TIERS:
        query = f"{base} WHERE heat_tier = ? ORDER BY created_at DESC LIMIT 100"
        cursor = await db.execute(query, (heat_filter,))
    else:
        query = f"{base} ORDER BY created_at DESC LIMIT 100"
        cursor = await db.execute(query)
    rows = await cursor.fetchall()
    await cursor.close()
    return [dict(row) for row in rows]


@ui.page("/")
async def stream_page() -> None:
    """Main document stream."""
    # Redirect to setup wizard if not configured
    if getattr(app.state, "embeddings", None) is None:
        ui.navigate.to("/setup")
        return

    with page_layout("Stream"):
        # Scribble input — entire card is a drop zone
        with (
            ui.card()
            .classes("w-full mb-6")
            .style("background: #111; transition: border-color 0.2s; border: 1px dashed transparent") as input_card
        ):
            text_input = (
                ui.textarea(placeholder="Drop a thought, paste a URL, or drag a file...")
                .classes("w-full")
                .props('autogrow outlined dense dark color="grey-7"')
            )

            # Hidden upload element for file handling
            upload = (
                ui.upload(
                    auto_upload=True,
                    on_upload=lambda e: _handle_file_upload(e),
                )
                .props('accept=".pdf,.docx,.md"')
                .classes("hidden")
            )

            with ui.row().classes("justify-end mt-2 gap-2 items-center"):
                ui.button(
                    "Upload",
                    icon="attach_file",
                    on_click=lambda: upload.run_method("pickFiles"),
                ).props('flat dense size="sm" color="grey-6" no-caps').classes("text-xs")
                ui.button(
                    "Submit",
                    icon="send",
                    on_click=lambda: _submit_scribble(text_input),
                ).props('flat dense size="sm" color="grey-6" no-caps').classes("text-xs")

        # Wire dropzone on the card via JS (targets this specific card by NiceGUI element id)
        card_id = f"c{input_card.id}"
        upload_id = f"c{upload.id}"
        ui.timer(
            0.3,
            lambda: ui.run_javascript(f"""
            var card = document.getElementById('{card_id}');
            var upEl = document.getElementById('{upload_id}');
            if (!card || !upEl) return;
            var inp = upEl.querySelector('input[type=file]');
            card.addEventListener('dragover', function(e) {{
                e.preventDefault();
                card.style.borderColor = '#7eb8da';
            }});
            card.addEventListener('dragleave', function(e) {{
                card.style.borderColor = 'transparent';
            }});
            card.addEventListener('drop', function(e) {{
                e.preventDefault();
                card.style.borderColor = 'transparent';
                if (!e.dataTransfer || !e.dataTransfer.files.length || !inp) return;
                var dt = new DataTransfer();
                for (var i = 0; i < e.dataTransfer.files.length; i++) dt.items.add(e.dataTransfer.files[i]);
                inp.files = dt.files;
                inp.dispatchEvent(new Event('change', {{bubbles: true}}));
            }});
        """),
            once=True,
        )

        # Heat filter tabs
        active_filter: dict[str, str | None] = {"value": None}

        _heat_tab_colors: dict[str | None, str] = {
            None: "#a0a0a0",
            **{tier: s["color"] for tier, s in HEAT_TIER_STYLES.items()},
        }

        with ui.row().classes("w-full mb-4 gap-1"):
            tab_buttons: dict[str | None, ui.button] = {}
            for label, tier in [("All", None)] + [(s["label"], t) for t, s in HEAT_TIER_STYLES.items()]:
                color = _heat_tab_colors[tier]
                btn = (
                    ui.button(
                        label,
                        on_click=lambda _e=None, t=tier: _set_filter(t),
                    )
                    .props('flat dense size="sm" no-caps')
                    .classes("text-xs")
                    .style(f"color: {color}; opacity: 1.0")
                )
                tab_buttons[tier] = btn

        def _update_tab_styles() -> None:
            for tier, btn in tab_buttons.items():
                is_active = tier == active_filter["value"]
                color = _heat_tab_colors[tier]
                btn.style(
                    f"color: {color}; opacity: {'1.0' if is_active else '0.5'}; "
                    f"{'border-bottom: 1px solid ' + color if is_active else 'border-bottom: none'}"
                )

        _update_tab_styles()

        # Document list with auto-refresh when items are processing
        doc_container = ui.column().classes("w-full gap-0")
        last_snapshot: dict[str, int] = {}  # {doc_id: processed} for change detection

        def _build_snapshot(docs: list[dict[str, object]]) -> dict[str, int]:
            return {str(d["id"]): int(d.get("processed") or 0) for d in docs}  # type: ignore[call-overload]

        def _render_doc_list(docs: list[dict[str, object]]) -> None:
            doc_container.clear()
            with doc_container:
                if not docs:
                    tier_label = active_filter["value"] or "any"
                    ui.label(f"No {tier_label} documents yet.").classes("text-muted text-xs text-center py-8")
                else:
                    for doc in docs:
                        render_document_card(doc)
                    ui.label(f"{len(docs)} documents").classes("text-muted text-xs text-center mt-4")

        async def _set_filter(tier: str | None) -> None:
            active_filter["value"] = tier
            _update_tab_styles()
            docs = await _load_documents(heat_filter=tier)
            nonlocal last_snapshot
            last_snapshot = _build_snapshot(docs)
            _render_doc_list(docs)

        async def _poll_docs() -> None:
            """Re-render only if document state changed."""
            nonlocal last_snapshot
            docs = await _load_documents(heat_filter=active_filter["value"])
            snapshot = _build_snapshot(docs)
            if snapshot != last_snapshot:
                last_snapshot = snapshot
                _render_doc_list(docs)

            has_unprocessed = any(not d.get("processed") for d in docs)
            if not has_unprocessed:
                poll_timer.deactivate()

        poll_timer = ui.timer(5.0, _poll_docs, active=False)

        # Initial load
        docs = await _load_documents()
        last_snapshot = _build_snapshot(docs)
        _render_doc_list(docs)

        if any(not d.get("processed") for d in docs):
            poll_timer.activate()


async def _submit_scribble(text_input: ui.textarea) -> None:
    """Submit a scribble from the input."""
    text = text_input.value
    if not text or not text.strip():
        return

    db = get_db()
    if db is None:
        ui.notify("Database not ready", type="negative")
        return

    # Check if it looks like a URL
    stripped = text.strip()
    if stripped.startswith(("http://", "https://")) and " " not in stripped:
        await _submit_url(stripped)
    else:
        await _submit_text(stripped)

    text_input.value = ""
    ui.navigate.to("/")


async def _submit_text(text: str) -> None:
    """Create a scribble document."""
    from hypomnema.ingestion.scribble import create_scribble

    db = get_db()
    if db is None:
        ui.notify("Database not ready", type="negative")
        return
    doc = await create_scribble(db, text)

    # Enqueue for ontology processing
    if app.state.ontology_queue:
        await app.state.ontology_queue.enqueue(doc.id)

    ui.notify("Scribble saved", type="positive")


async def _submit_url(url: str) -> None:
    """Fetch a URL and create a document."""
    from hypomnema.ingestion.url_fetch import fetch_url

    try:
        doc = await fetch_url(get_db(), url)
        if app.state.ontology_queue:
            await app.state.ontology_queue.enqueue(doc.id)
        ui.notify(f"Fetched: {doc.title or url}", type="positive")
    except Exception as e:
        ui.notify(f"Fetch failed: {e}", type="negative")


async def _handle_file_upload(e: object) -> None:
    """Handle file upload."""
    import tempfile
    from pathlib import Path

    from hypomnema.ingestion.file_parser import ingest_file

    upload_event = e
    content = upload_event.content.read()  # type: ignore[attr-defined]
    name = upload_event.name  # type: ignore[attr-defined]

    with tempfile.NamedTemporaryFile(suffix=Path(name).suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        doc = await ingest_file(get_db(), tmp_path)

        if app.state.ontology_queue:
            await app.state.ontology_queue.enqueue(doc.id)

        ui.notify(f"Uploaded: {name}", type="positive")
        ui.navigate.to("/")
    except Exception as ex:
        ui.notify(f"Upload failed: {ex}", type="negative")
    finally:
        tmp_path.unlink(missing_ok=True)
