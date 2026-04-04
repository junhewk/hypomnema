"""Engram detail page."""

from __future__ import annotations

from typing import Any

from nicegui import app, ui

from hypomnema.ui.layout import page_layout
from hypomnema.ui.theme import SOURCE_STYLES
from hypomnema.ui.utils import get_db


def _render_edge_row(edge: dict[str, Any], engram_id: str, direction: str) -> None:
    """Render a single edge row."""
    if direction == "outgoing":
        linked_id = str(edge["target_engram_id"])
        linked_name = str(edge["target_name"])
    else:
        linked_id = str(edge["source_engram_id"])
        linked_name = str(edge["source_name"])

    predicate = str(edge.get("predicate", ""))
    confidence = float(edge.get("confidence") or 0)
    confidence_pct = f"{confidence * 100:.0f}%" if confidence else "0%"

    with ui.row().classes("items-center gap-2 py-1"):
        ui.link(linked_name, f"/engrams/{linked_id}").classes(
            "source-badge engram-link no-underline cursor-pointer"
        ).style(
            "color: var(--accent); background: var(--accent-soft); "
            "text-decoration: none; font-size: 11px"
        )
        ui.label(predicate).classes("text-xs").style(
            "color: var(--fg-muted); font-style: italic"
        )
        ui.label(confidence_pct).classes("text-xs").style(
            "color: rgba(99,105,120,0.5); font-size: 10px"
        )


def _render_edges(edges: list[dict[str, Any]], engram_id: str) -> None:
    """Render edges grouped by direction."""
    outgoing = [e for e in edges if str(e["source_engram_id"]) == engram_id]
    incoming = [e for e in edges if str(e["target_engram_id"]) == engram_id]

    if not outgoing and not incoming:
        ui.label("No edges.").classes("text-muted text-xs")
        return

    if outgoing:
        ui.label("Outgoing").classes("text-xs tracking-wider uppercase mt-2 mb-1").style(
            "color: rgba(99,105,120,0.5); font-size: 10px"
        )
        for edge in outgoing:
            _render_edge_row(edge, engram_id, "outgoing")

    if incoming:
        ui.label("Incoming").classes("text-xs tracking-wider uppercase mt-4 mb-1").style(
            "color: rgba(99,105,120,0.5); font-size: 10px"
        )
        for edge in incoming:
            _render_edge_row(edge, engram_id, "incoming")


def _render_source_docs(docs: list[dict[str, Any]]) -> None:
    """Render source documents as cards."""
    if not docs:
        ui.label("No source documents.").classes("text-muted text-xs")
        return

    for doc in docs:
        doc_id = str(doc["id"])
        source_type = str(doc.get("source_type", "scribble"))
        style = SOURCE_STYLES.get(source_type, SOURCE_STYLES["scribble"])
        title = str(doc.get("tidy_title") or doc.get("title") or "Untitled")
        preview = str(doc.get("tidy_text") or doc.get("text") or "")[:200]

        with ui.card().classes("w-full mb-2 doc-card cursor-pointer").style(
            f"border-left: 2px solid {style['color']}"
        ).on("click", lambda _d=doc_id: ui.navigate.to(f"/documents/{_d}")):
            with ui.row().classes("items-center gap-2 mb-1"):
                ui.label(style["label"]).classes("source-badge").style(
                    f"color: {style['color']}; background: {style['bg']}"
                )
            ui.label(title).classes("text-display-sm mb-1")
            if preview:
                ui.label(preview).classes("text-xs leading-relaxed text-muted").style(
                    "display: -webkit-box; -webkit-line-clamp: 2; "
                    "-webkit-box-orient: vertical; overflow: hidden"
                )


@ui.page("/engrams/{engram_id}")
async def engram_detail_page(engram_id: str) -> None:
    """Engram detail view."""
    db = get_db()

    with page_layout("Engram"):
        # Back button
        ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props(
            "flat dense round color=grey-7"
        ).classes("mb-4")

        if db is None:
            ui.label("Database not ready.").classes("text-muted text-xs")
            return

        # Fetch engram
        cursor = await db.execute(
            "SELECT * FROM engrams WHERE id = ?", (engram_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            ui.label("Engram not found.").classes("text-sm").style(
                "color: #e06c75"
            )
            return

        engram = dict(row)

        # Fetch edges
        cursor = await db.execute(
            "SELECT e.*, "
            "se.canonical_name AS source_name, te.canonical_name AS target_name "
            "FROM edges e "
            "JOIN engrams se ON e.source_engram_id = se.id "
            "JOIN engrams te ON e.target_engram_id = te.id "
            "WHERE e.source_engram_id = ? OR e.target_engram_id = ? "
            "ORDER BY e.confidence DESC LIMIT 100",
            (engram_id, engram_id),
        )
        edges = [dict(r) for r in await cursor.fetchall()]
        await cursor.close()

        # Fetch source documents
        cursor = await db.execute(
            "SELECT d.* FROM documents d "
            "JOIN document_engrams de ON d.id = de.document_id "
            "WHERE de.engram_id = ? LIMIT 100",
            (engram_id,),
        )
        docs = [dict(r) for r in await cursor.fetchall()]
        await cursor.close()

        # Heading
        canonical_name = str(engram.get("canonical_name", ""))
        ui.label(canonical_name).classes("text-display-lg mb-1")

        # Description (if present)
        description = engram.get("description")
        if description:
            ui.label(str(description)).classes(
                "text-xs leading-relaxed mb-4 text-muted"
            )

        # Synthesized article
        article = engram.get("article")
        if article:
            with ui.element("div").classes("pt-4 mb-6").style(
                "border-top: 1px solid var(--border)"
            ):
                ui.label("Article").classes("section-label mb-3")
                ui.markdown(str(article)).classes("text-sm leading-relaxed")

                async def _regenerate_article() -> None:
                    if db is None:
                        ui.notify("Database not ready", type="negative")
                        return
                    llm = getattr(app.state, "llm", None)
                    if llm is None:
                        ui.notify("LLM not configured", type="negative")
                        return
                    from hypomnema.ontology.synthesizer import synthesize_engram_article

                    ui.notify("Regenerating article...", type="info")
                    result = await synthesize_engram_article(db, llm, engram_id)
                    if result:
                        ui.notify("Article regenerated", type="positive")
                        ui.navigate.to(f"/engrams/{engram_id}")
                    else:
                        ui.notify("Not enough sources for article", type="warning")

                ui.button(
                    "Regenerate",
                    icon="refresh",
                    on_click=_regenerate_article,
                ).props('flat dense color="grey-7"').classes("text-xs mt-2")

        # Edges section
        with ui.element("div").classes("pt-4 mb-6").style(
            "border-top: 1px solid var(--border)"
        ):
            ui.label("Edges").classes("section-label mb-3")
            _render_edges(edges, engram_id)

        # Source documents section
        with ui.element("div").classes("pt-6").style(
            "border-top: 1px solid var(--border)"
        ):
            ui.label("Source Documents").classes("section-label mb-3")
            _render_source_docs(docs)
