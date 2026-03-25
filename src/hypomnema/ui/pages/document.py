"""Document detail page."""

from __future__ import annotations

from nicegui import app, ui

from hypomnema.ui.layout import page_layout
from hypomnema.ui.theme import SOURCE_STYLES
from hypomnema.ui.utils import time_ago

SUMMARY_MAX_LENGTH = 600


def _render_text_content(doc: dict[str, object]) -> None:
    """Render the document text with TL;DR / tidy logic."""
    tidy_text = doc.get("tidy_text")
    raw_text = str(doc.get("text") or "")
    mime_type = str(doc.get("mime_type") or "")

    if tidy_text and len(str(tidy_text)) < SUMMARY_MAX_LENGTH:
        # Short tidy_text: show as TL;DR block above original
        with ui.element("div").classes("mb-4 pl-3").style(
            "border-left: 2px solid rgba(126,184,218,0.3)"
        ):
            ui.label("TL;DR").classes("text-xs tracking-wider uppercase").style(
                "color: rgba(107,107,107,0.6); font-size: 10px"
            )
            ui.label(str(tidy_text)).classes("mt-1 text-xs leading-relaxed").style(
                "color: rgba(212,212,212,0.8)"
            )
        # Show original text below
        if mime_type == "text/markdown":
            ui.markdown(raw_text).classes("text-sm")
        else:
            ui.label(raw_text).classes("text-sm leading-relaxed").style(
                "white-space: pre-wrap; color: #d4d4d4"
            )

    elif tidy_text:
        # Long tidy_text: show as main content, collapsible original
        ui.markdown(str(tidy_text)).classes("text-sm leading-relaxed")

        with ui.expansion("Original text").classes("mt-6 pt-4").style(
            "border-top: 1px solid rgba(30,30,30,0.5)"
        ).props('dense header-class="text-xs uppercase tracking-wider"').style(
            "color: rgba(107,107,107,0.6)"
        ):
            if mime_type == "text/markdown":
                ui.markdown(raw_text).classes("text-xs mt-3").style(
                    "color: rgba(107,107,107,0.6)"
                )
            else:
                ui.label(raw_text).classes("text-xs leading-relaxed mt-3").style(
                    "white-space: pre-wrap; color: rgba(107,107,107,0.6)"
                )

    else:
        # No tidy_text: show raw
        if mime_type == "text/markdown":
            ui.markdown(raw_text).classes("text-sm")
        else:
            ui.label(raw_text).classes("text-sm leading-relaxed").style(
                "white-space: pre-wrap; color: #d4d4d4"
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
                "source-badge no-underline cursor-pointer"
            ).style(
                "color: #7eb8da; background: rgba(126,184,218,0.08); "
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
            "block px-3 py-2 rounded no-underline cursor-pointer mb-1"
        ).style(
            "color: #d4d4d4; transition: background 0.15s"
        ).on(
            "mouseenter", lambda e: e.sender.style("background: rgba(255,255,255,0.03)")
        ).on(
            "mouseleave", lambda e: e.sender.style("background: transparent")
        ):
            ui.label(rdoc_title).classes("text-xs truncate")
            ui.element("a").props(f'href="/documents/{rdoc_id}"').classes("absolute inset-0")


@ui.page("/documents/{doc_id}")
async def document_detail_page(doc_id: str) -> None:
    """Document detail view."""
    db = app.state.db

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
            ui.label("Document not found.").classes("text-sm").style("color: #ef5350")
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
                        "color: #4caf50; font-size: 12px"
                    )
                else:
                    ui.icon("pending").classes("text-xs animate-pulse-dot").style(
                        "color: #ff9800; font-size: 12px"
                    )

                if doc.get("mime_type"):
                    ui.label(str(doc["mime_type"])).classes("text-muted text-xs")

            # Title
            ui.label(str(title)).classes("text-lg font-medium mb-1")

            # Timestamp
            ui.label(time_ago(created_at)).classes("text-xs mb-4").style(
                "color: rgba(107,107,107,0.6); font-size: 10px"
            )

            # Content
            with ui.element("div").classes("mb-8"):
                _render_text_content(doc)

            # Engrams section
            with ui.element("div").classes("pt-6").style(
                "border-top: 1px solid #1e1e1e"
            ):
                ui.label("Engrams").classes(
                    "text-xs tracking-wider uppercase mb-3"
                ).style("color: #6b6b6b")
                _render_engrams(engrams, doc_id)

            # Related documents section
            if related:
                with ui.element("div").classes("pt-6 mt-6").style(
                    "border-top: 1px solid #1e1e1e"
                ):
                    ui.label("Related Documents").classes(
                        "text-xs tracking-wider uppercase mb-3"
                    ).style("color: #6b6b6b")
                    _render_related_docs(related)

            # Edit button for scribbles
            if source_type == "scribble":
                ui.button(
                    "Edit",
                    icon="edit",
                    on_click=lambda: ui.navigate.to("/"),
                ).props('flat dense color="grey-7"').classes("mt-6 text-xs")
