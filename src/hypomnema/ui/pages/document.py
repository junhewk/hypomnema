"""Document detail page with inline editing."""

from __future__ import annotations

from nicegui import app, ui

from hypomnema.ui.layout import page_layout
from hypomnema.ui.theme import SOURCE_STYLES
from hypomnema.ui.utils import get_db, time_ago

SUMMARY_MAX_LENGTH = 600


def _render_text_content(doc: dict[str, object]) -> None:
    """Render the document text with TL;DR / tidy logic."""
    tidy_text = doc.get("tidy_text")
    raw_text = str(doc.get("text") or "")
    mime_type = str(doc.get("mime_type") or "")

    if tidy_text and len(str(tidy_text)) < SUMMARY_MAX_LENGTH:
        # Short tidy_text: show as TL;DR block above original
        with ui.element("div").classes("mb-4 pl-3").style(
            "border-left: 2px solid color-mix(in srgb, var(--accent) 30%, transparent)"
        ):
            ui.label("TL;DR").classes("text-xs tracking-wider uppercase").style(
                "color: rgba(99,105,120,0.6); font-size: 10px"
            )
            ui.label(str(tidy_text)).classes("mt-1 text-xs leading-relaxed").style(
                "color: rgba(200,204,214,0.8)"
            )
        # Show original text below
        if mime_type == "text/markdown":
            ui.markdown(raw_text).classes("text-sm")
        else:
            ui.label(raw_text).classes("text-sm leading-relaxed").style(
                "white-space: pre-wrap; color: var(--fg)"
            )

    elif tidy_text:
        # Long tidy_text: show as main content, collapsible original
        ui.markdown(str(tidy_text)).classes("text-sm leading-relaxed")

        with ui.expansion("Original text").classes("mt-6 pt-4").style(
            "border-top: 1px solid var(--border)"
        ).props('dense header-class="text-xs uppercase tracking-wider"').style(
            "color: rgba(99,105,120,0.6)"
        ):
            if mime_type == "text/markdown":
                ui.markdown(raw_text).classes("text-xs mt-3").style(
                    "color: rgba(99,105,120,0.6)"
                )
            else:
                ui.label(raw_text).classes("text-xs leading-relaxed mt-3").style(
                    "white-space: pre-wrap; color: rgba(99,105,120,0.6)"
                )

    else:
        # No tidy_text: show raw
        if mime_type == "text/markdown":
            ui.markdown(raw_text).classes("text-sm")
        else:
            ui.label(raw_text).classes("text-sm leading-relaxed").style(
                "white-space: pre-wrap; color: var(--fg)"
            )


def _render_annotation(doc: dict[str, object]) -> None:
    """Render the user annotation block if present."""
    annotation = doc.get("annotation")
    if not annotation:
        return
    with ui.element("div").classes("mt-4 pl-3").style(
        "border-left: 2px solid color-mix(in srgb, var(--accent) 30%, transparent)"
    ):
        ui.label("Your notes").classes("text-xs tracking-wider uppercase").style(
            "color: rgba(99,105,120,0.6); font-size: 10px"
        )
        ui.label(str(annotation)).classes("mt-1 text-sm leading-relaxed").style(
            "white-space: pre-wrap; color: rgba(200,204,214,0.8)"
        )


def _render_engrams(engrams: list[dict[str, object]], doc_id: str) -> None:
    """Render the engrams section."""
    if not engrams:
        ui.label("No engrams linked yet.").classes("text-muted text-xs")
        return

    with ui.element("div").classes("flex flex-wrap gap-2"):
        for engram in engrams:
            engram_id = str(engram["id"])
            name = str(engram["canonical_name"])
            ui.link(name, f"/engrams/{engram_id}").classes(
                "source-badge engram-link no-underline cursor-pointer"
            ).style(
                "color: var(--accent); background: var(--accent-soft); "
                "text-decoration: none; font-size: 11px"
            )


def _render_related_docs(related: list[dict[str, object]]) -> None:
    """Render the related documents section."""
    if not related:
        ui.label("No related documents.").classes("text-muted text-xs")
        return

    for rdoc in related:
        rdoc_id = str(rdoc["id"])
        rdoc_title = str(rdoc.get("tidy_title") or rdoc.get("title") or "Untitled")
        with ui.element("a").classes(
            "block relative px-3 py-2 rounded no-underline cursor-pointer mb-1"
        ).style(
            "color: var(--fg); transition: background 0.15s"
        ).on(
            "mouseenter",
            lambda e: e.sender.style("background: var(--accent-soft)"),
        ).on(
            "mouseleave", lambda e: e.sender.style("background: transparent")
        ):
            ui.label(rdoc_title).classes("text-xs truncate font-display")
            ui.element("a").props(f'href="/documents/{rdoc_id}"').classes(
                "absolute inset-0"
            )


async def _save_document_edit(
    doc_id: str,
    doc: dict[str, object],
    *,
    text: str | None = None,
    title: str | None = None,
    annotation: str | None = None,
) -> None:
    """Save an edit via shared update logic, then enqueue reprocessing."""
    from hypomnema.api.documents import snapshot_and_update_document
    from hypomnema.db.models import Document

    db = get_db()
    if db is None:
        ui.notify("Database not ready", type="negative")
        return

    # Fetch fresh document for snapshot_and_update_document
    cursor = await db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        ui.notify("Document not found", type="negative")
        return

    updated = await snapshot_and_update_document(
        db,
        Document.from_row(row),
        text=text,
        title=title,
        annotation=annotation,
    )
    queue = getattr(app.state, "ontology_queue", None)
    if queue:
        await queue.enqueue(doc_id, updated.revision, incremental=True)

    ui.notify("Saved", type="positive")
    ui.navigate.to(f"/documents/{doc_id}")


@ui.page("/documents/{doc_id}")
async def document_detail_page(doc_id: str) -> None:
    """Document detail view with inline edit mode."""
    db = get_db()

    with page_layout("Document"):
        # Back button
        ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props(
            "flat dense round color=grey-7"
        ).classes("mb-4")

        if db is None:
            ui.label("Database not ready.").classes("text-muted text-xs")
            return

        # Fetch document
        cursor = await db.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            ui.label("Document not found.").classes("text-sm").style(
                "color: #e06c75"
            )
            return

        doc = dict(row)

        # Fetch engrams
        cursor = await db.execute(
            "SELECT e.id, e.canonical_name FROM engrams e "
            "JOIN document_engrams de ON e.id = de.engram_id "
            "WHERE de.document_id = ? LIMIT 200",
            (doc_id,),
        )
        engrams = [dict(r) for r in await cursor.fetchall()]
        await cursor.close()

        # Fetch related documents
        cursor = await db.execute(
            "SELECT DISTINCT d.id, d.tidy_title, d.title FROM document_engrams de1 "
            "JOIN document_engrams de2 ON de1.engram_id = de2.engram_id "
            "JOIN documents d ON de2.document_id = d.id "
            "WHERE de1.document_id = ? AND de2.document_id != ? LIMIT 10",
            (doc_id, doc_id),
        )
        related = [dict(r) for r in await cursor.fetchall()]
        await cursor.close()

        # Source type + metadata header
        source_type = str(doc.get("source_type", "scribble"))
        style = SOURCE_STYLES.get(source_type, SOURCE_STYLES["scribble"])
        title = doc.get("tidy_title") or doc.get("title") or "Untitled"
        created_at = str(doc.get("created_at", ""))
        is_scribble = source_type == "scribble"

        with ui.element("article").classes("animate-fade-up pl-4").style(
            f"border-left: 2px solid {style['color']}"
        ):
            # Badge row: source type, status, mime
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.label(style["label"]).classes("source-badge").style(
                    f"color: {style['color']}; background: {style['bg']}"
                )

                if doc.get("processed"):
                    ui.icon("check_circle").classes("text-xs").style(
                        "color: #56c9a0; font-size: 12px"
                    )
                else:
                    ui.icon("pending").classes(
                        "text-xs animate-pulse-dot"
                    ).style("color: #d4b06a; font-size: 12px")

                if doc.get("mime_type"):
                    ui.label(str(doc["mime_type"])).classes("text-muted text-xs")

            # Title
            ui.label(str(title)).classes("text-display-lg mb-1")

            # Timestamp
            ui.label(time_ago(created_at)).classes("text-xs mb-4").style(
                "color: rgba(99,105,120,0.6); font-size: 10px"
            )

            # Content area — swapped between read/edit mode
            content_container = ui.element("div").classes("mb-8")

            def _render_read_mode() -> None:
                content_container.clear()
                with content_container:
                    _render_text_content(doc)
                    if not is_scribble:
                        _render_annotation(doc)

            def _render_edit_mode() -> None:
                content_container.clear()
                with content_container:
                    if is_scribble:
                        title_input = ui.input(
                            label="Title",
                            value=str(
                                doc.get("title") or doc.get("tidy_title") or ""
                            ),
                        ).classes("w-full mb-3").props(
                            'outlined dense dark color="grey-7"'
                        )

                        text_input = (
                            ui.textarea(
                                label="Text",
                                value=str(doc.get("text") or ""),
                            )
                            .classes("w-full")
                            .props('autogrow outlined dense dark color="grey-7"')
                        )

                        with ui.row().classes("mt-3 gap-2"):
                            ui.button(
                                "Save",
                                icon="save",
                                on_click=lambda: _save_document_edit(
                                    doc_id,
                                    doc,
                                    text=text_input.value,
                                    title=title_input.value,
                                ),
                            ).props(
                                'flat dense color="green-7" no-caps'
                            ).classes("text-xs")
                            ui.button(
                                "Cancel",
                                icon="close",
                                on_click=_exit_edit,
                            ).props(
                                'flat dense color="grey-7" no-caps'
                            ).classes("text-xs")
                    else:
                        _render_text_content(doc)
                        ui.separator().classes("my-4")
                        ui.label("Your notes").classes(
                            "section-label mb-2"
                        )

                        annotation_input = (
                            ui.textarea(
                                value=str(doc.get("annotation") or ""),
                                placeholder="Add your notes about this document...",
                            )
                            .classes("w-full")
                            .props('autogrow outlined dense dark color="grey-7"')
                        )

                        with ui.row().classes("mt-3 gap-2"):
                            ui.button(
                                "Save",
                                icon="save",
                                on_click=lambda: _save_document_edit(
                                    doc_id,
                                    doc,
                                    annotation=annotation_input.value,
                                ),
                            ).props(
                                'flat dense color="green-7" no-caps'
                            ).classes("text-xs")
                            ui.button(
                                "Cancel",
                                icon="close",
                                on_click=_exit_edit,
                            ).props(
                                'flat dense color="grey-7" no-caps'
                            ).classes("text-xs")

            def _enter_edit() -> None:
                _render_edit_mode()
                edit_btn.set_visibility(False)

            def _exit_edit() -> None:
                _render_read_mode()
                edit_btn.set_visibility(True)

            # Initial render
            _render_read_mode()

            # Engrams section
            with ui.element("div").classes("pt-6").style(
                "border-top: 1px solid var(--border)"
            ):
                ui.label("Engrams").classes("section-label mb-3")
                _render_engrams(engrams, doc_id)

            # Related documents section
            if related:
                with ui.element("div").classes("pt-6 mt-6").style(
                    "border-top: 1px solid var(--border)"
                ):
                    ui.label("Related Documents").classes("section-label mb-3")
                    _render_related_docs(related)

            # Edit button — dynamic label by source type
            if is_scribble:
                edit_label, edit_icon = "Edit", "edit"
            elif doc.get("annotation"):
                edit_label, edit_icon = "Edit notes", "edit_note"
            else:
                edit_label, edit_icon = "Annotate", "note_add"

            with ui.row().classes("mt-6 gap-2"):
                edit_btn = ui.button(
                    edit_label,
                    icon=edit_icon,
                    on_click=_enter_edit,
                ).props('flat dense color="grey-7"').classes("text-xs")

                async def _delete_document() -> None:
                    """Delete document after confirmation."""
                    with ui.dialog() as confirm_dialog, ui.card().style(
                        "background: var(--bg-raised); min-width: 300px"
                    ):
                        ui.label("Delete this document and its engram links?").classes(
                            "text-xs mb-4"
                        ).style("color: var(--fg-muted)")
                        with ui.row().classes("gap-2 justify-end"):
                            ui.button(
                                "Cancel", on_click=confirm_dialog.close
                            ).props('flat dense color="grey-7"').classes("text-xs")

                            async def _confirm_delete() -> None:
                                confirm_dialog.close()
                                if db is None:
                                    ui.notify("Database not ready", type="negative")
                                    return
                                from hypomnema.db.transactions import immediate_transaction
                                from hypomnema.ontology.pipeline import remove_document_associations

                                async with immediate_transaction(db):
                                    await remove_document_associations(db, doc_id)
                                    await db.execute(
                                        "DELETE FROM documents WHERE id = ?", (doc_id,)
                                    )
                                ui.notify("Document deleted", type="info")
                                ui.navigate.to("/")

                            ui.button(
                                "Delete", on_click=_confirm_delete
                            ).props('flat dense color="red-4"').classes("text-xs")

                    confirm_dialog.open()

                ui.button(
                    "Delete",
                    icon="delete",
                    on_click=_delete_document,
                ).props('flat dense color="red-4"').classes("text-xs")
