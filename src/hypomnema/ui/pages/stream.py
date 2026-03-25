"""Stream page — main document feed."""

from __future__ import annotations

from nicegui import app, ui

from hypomnema.ui.components.document_card import render_document_card
from hypomnema.ui.layout import page_layout


async def _load_documents() -> list[dict[str, object]]:
    """Fetch recent documents from the database."""
    db = app.state.db
    if db is None:
        return []
    cursor = await db.execute(
        "SELECT id, source_type, title, tidy_title, text, tidy_text, "
        "mime_type, created_at, processed, metadata "
        "FROM documents ORDER BY created_at DESC LIMIT 100"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [dict(row) for row in rows]


@ui.page("/")
async def stream_page() -> None:
    """Main document stream."""
    with page_layout("Stream"):
        # Scribble input
        with ui.card().classes("w-full mb-6").style("background: #111"):
            text_input = ui.textarea(
                placeholder="Drop a thought, paste a URL, or drag a file..."
            ).classes("w-full").props('autogrow outlined dense dark color="grey-7"')

            with ui.row().classes("justify-end mt-2 gap-2 items-center"):
                upload = ui.upload(
                    auto_upload=True,
                    on_upload=lambda e: _handle_file_upload(e),
                ).props('flat dense accept=".pdf,.docx,.md" color="grey-7"').classes("hidden")
                ui.button(
                    "Upload", icon="attach_file",
                    on_click=lambda: upload.run_method("pickFiles"),
                ).props('flat dense size="sm" color="grey-6" no-caps').classes("text-xs")
                ui.button(
                    "Submit", icon="send",
                    on_click=lambda: _submit_scribble(text_input),
                ).props('flat dense size="sm" color="grey-6" no-caps').classes("text-xs")

        # Document list with auto-refresh when items are processing
        doc_container = ui.column().classes("w-full gap-0")
        last_snapshot: dict[str, int] = {}  # {doc_id: processed} for change detection

        def _build_snapshot(docs: list[dict[str, object]]) -> dict[str, int]:
            return {str(d["id"]): int(d.get("processed") or 0) for d in docs}

        def _render_doc_list(docs: list[dict[str, object]]) -> None:
            doc_container.clear()
            with doc_container:
                if not docs:
                    ui.label("No documents yet. Write something above to get started.").classes(
                        "text-muted text-xs text-center py-8"
                    )
                else:
                    for doc in docs:
                        render_document_card(doc)
                    ui.label(f"{len(docs)} documents").classes("text-muted text-xs text-center mt-4")

        async def _poll_docs() -> None:
            """Re-render only if document state changed."""
            nonlocal last_snapshot
            docs = await _load_documents()
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

    db = app.state.db
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

    db = app.state.db
    doc = await create_scribble(db, text)

    # Enqueue for ontology processing
    if app.state.ontology_queue:
        await app.state.ontology_queue.enqueue(doc.id)

    ui.notify("Scribble saved", type="positive")


async def _submit_url(url: str) -> None:
    """Fetch a URL and create a document."""
    from hypomnema.ingestion.url_fetch import fetch_url

    try:
        doc = await fetch_url(app.state.db, url)
        if app.state.ontology_queue:
            await app.state.ontology_queue.enqueue(doc.id)
        ui.notify(f"Fetched: {doc.title or url}", type="positive")
    except Exception as e:
        ui.notify(f"Fetch failed: {e}", type="negative")


async def _handle_file_upload(e: object) -> None:
    """Handle file upload."""
    import tempfile
    from pathlib import Path

    from hypomnema.ingestion.file_parser import parse_file

    upload_event = e
    content = upload_event.content.read()  # type: ignore[attr-defined]
    name = upload_event.name  # type: ignore[attr-defined]

    with tempfile.NamedTemporaryFile(suffix=Path(name).suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        parsed = parse_file(tmp_path)
        db = app.state.db
        cursor = await db.execute(
            "INSERT INTO documents (source_type, title, text, mime_type, source_uri) "
            "VALUES ('file', ?, ?, ?, ?) RETURNING id",
            (parsed.title, parsed.text, parsed.mime_type, str(tmp_path)),
        )
        row = await cursor.fetchone()
        await db.commit()
        assert row is not None
        doc_id = str(row[0])

        if app.state.ontology_queue:
            await app.state.ontology_queue.enqueue(doc_id)

        ui.notify(f"Uploaded: {name}", type="positive")
        ui.navigate.to("/")
    except Exception as ex:
        ui.notify(f"Upload failed: {ex}", type="negative")
    finally:
        tmp_path.unlink(missing_ok=True)
