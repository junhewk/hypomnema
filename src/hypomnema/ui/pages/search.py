"""Search page — hybrid document search and knowledge graph exploration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from nicegui import app, ui

from hypomnema.ui.components.document_card import render_document_card
from hypomnema.ui.layout import page_layout
from hypomnema.ui.utils import get_db

if TYPE_CHECKING:
    from hypomnema.search.doc_search import ScoredDocument

logger = logging.getLogger(__name__)


def _render_doc_result(scored: ScoredDocument) -> None:
    """Render a single document search result card using the shared component."""
    doc = scored.document
    created = doc.created_at.isoformat() if doc.created_at else ""
    doc_dict = {
        "id": doc.id,
        "source_type": doc.source_type or "scribble",
        "tidy_title": doc.tidy_title,
        "title": doc.title,
        "tidy_text": doc.tidy_text,
        "text": doc.text,
        "created_at": created,
    }
    render_document_card(
        doc_dict,
        show_score=True,
        score=scored.score,
        match_type=scored.match_type,
    )


def _render_engram_card(row: dict[str, Any]) -> None:
    """Render a single engram result card."""
    with ui.card().classes("w-full mb-3 animate-fade-up").style(
        "border-left: 2px solid #7eb8da"
    ):
        ui.label(str(row["canonical_name"])).classes("text-sm font-medium mb-1")
        if row.get("description"):
            ui.label(str(row["description"])[:200]).classes("text-xs leading-relaxed").style(
                "color: #6b6b6b"
            )


def _render_edge_card(row: dict[str, Any]) -> None:
    """Render a single edge result card."""
    confidence = row.get("confidence", 0.0)
    conf_color = "#4caf50" if confidence >= 0.7 else "#ff9800" if confidence >= 0.4 else "#ef5350"

    with ui.card().classes("w-full mb-2 animate-fade-up").style(
        "border-left: 2px solid #4a4a4a"
    ):
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.label(str(row.get("source_name", "?"))).classes("text-xs font-medium").style(
                "color: #d4d4d4"
            )
            ui.label(str(row.get("predicate", ""))).classes("source-badge").style(
                "color: #7eb8da; background: rgba(126,184,218,0.1)"
            )
            ui.label(str(row.get("target_name", "?"))).classes("text-xs font-medium").style(
                "color: #d4d4d4"
            )
        with ui.row().classes("items-center gap-2 mt-1"):
            ui.label(f"confidence: {confidence:.2f}").classes("text-xs").style(
                f"color: {conf_color}"
            )


@ui.page("/search")
async def search_page() -> None:
    """Search page with document and knowledge graph modes."""
    db = get_db()
    embeddings = getattr(app.state, "embeddings", None)

    # Debounce state
    debounce_timer: dict[str, object | None] = {"timer": None}
    current_query: dict[str, str] = {"value": ""}
    current_mode: dict[str, str] = {"value": "Documents"}

    with page_layout("Search"):
        ui.label("Search").classes("text-lg font-medium mb-4")

        # Search input
        search_input = ui.input(
            placeholder="Search documents and knowledge..."
        ).props(
            'outlined dense dark color="grey-7"'
        ).classes("w-full mb-3").style("font-size: 13px")
        search_input.props('prepend-inner-icon="search"')

        # Mode toggle
        mode_toggle = ui.toggle(
            ["Documents", "Knowledge"],
            value="Documents",
        ).props('dense flat color="grey-7" text-color="grey-5"').classes("mb-4")

        # Results container
        results_container = ui.column().classes("w-full gap-0")
        status_label = ui.label("").classes("text-muted text-xs mb-2")

        async def _do_search() -> None:
            """Execute the search and render results."""
            query = current_query["value"].strip()
            mode = current_mode["value"]

            results_container.clear()
            status_label.set_text("")

            if not query:
                return

            if db is None:
                with results_container:
                    ui.label("Database not ready.").classes("text-muted text-xs py-4")
                return

            if mode == "Documents":
                await _search_documents(query, results_container, status_label)
            else:
                await _search_knowledge(query, results_container, status_label)

        async def _search_documents(
            query: str,
            container: ui.column,
            status: ui.label,
        ) -> None:
            """Run hybrid document search."""
            from hypomnema.search.doc_search import (
                _reciprocal_rank_fusion,
                keyword_search,
                semantic_search,
            )

            keyword_results = await keyword_search(db, query, limit=20)

            # Try semantic search if embeddings are available
            semantic_results: list[ScoredDocument] = []
            if embeddings is not None:
                try:
                    semantic_results = await semantic_search(
                        db, query, embeddings, limit=20
                    )
                except Exception:
                    logger.debug("Semantic search unavailable, falling back to keyword-only")

            if keyword_results and semantic_results:
                merged = _reciprocal_rank_fusion(keyword_results, semantic_results)
                results = merged[:20]
                search_type = "hybrid"
            elif keyword_results:
                results = keyword_results
                search_type = "keyword"
            elif semantic_results:
                results = semantic_results
                search_type = "semantic"
            else:
                results = []
                search_type = "none"

            with container:
                if not results:
                    ui.label("No documents found.").classes(
                        "text-muted text-xs text-center py-8"
                    )
                else:
                    for scored in results:
                        _render_doc_result(scored)

            count = len(results)
            mode_note = f" ({search_type})" if search_type != "none" else ""
            status.set_text(
                f"{count} result{'s' if count != 1 else ''}{mode_note}"
                if count > 0
                else ""
            )

        async def _search_knowledge(
            query: str,
            container: ui.column,
            status: ui.label,
        ) -> None:
            """Search engrams and edges by name."""
            like_pattern = f"%{query}%"

            # Search engrams
            cursor = await db.execute(
                "SELECT id, canonical_name, concept_hash, description, created_at "
                "FROM engrams WHERE canonical_name LIKE ? "
                "ORDER BY canonical_name LIMIT 30",
                (like_pattern,),
            )
            engram_rows = [dict(r) for r in await cursor.fetchall()]
            await cursor.close()

            # Search edges involving matching engrams
            cursor = await db.execute(
                "SELECT e.id, e.source_engram_id, e.target_engram_id, e.predicate, "
                "e.confidence, e.source_document_id, e.created_at, "
                "se.canonical_name AS source_name, te.canonical_name AS target_name "
                "FROM edges e "
                "JOIN engrams se ON e.source_engram_id = se.id "
                "JOIN engrams te ON e.target_engram_id = te.id "
                "WHERE se.canonical_name LIKE ? OR te.canonical_name LIKE ? "
                "ORDER BY e.confidence DESC LIMIT 50",
                (like_pattern, like_pattern),
            )
            edge_rows = [dict(r) for r in await cursor.fetchall()]
            await cursor.close()

            with container:
                if not engram_rows and not edge_rows:
                    ui.label("No knowledge graph results found.").classes(
                        "text-muted text-xs text-center py-8"
                    )
                else:
                    if engram_rows:
                        ui.label("Engrams").classes(
                            "text-xs tracking-wider uppercase mb-2"
                        ).style("color: #7eb8da; letter-spacing: 0.1em")
                        for row in engram_rows:
                            _render_engram_card(row)

                    if edge_rows:
                        ui.label("Edges").classes(
                            "text-xs tracking-wider uppercase mb-2 mt-4"
                        ).style("color: #7eb8da; letter-spacing: 0.1em")
                        for row in edge_rows:
                            _render_edge_card(row)

            engram_count = len(engram_rows)
            edge_count = len(edge_rows)
            parts = []
            if engram_count:
                parts.append(f"{engram_count} engram{'s' if engram_count != 1 else ''}")
            if edge_count:
                parts.append(f"{edge_count} edge{'s' if edge_count != 1 else ''}")
            status.set_text(", ".join(parts) if parts else "")

        async def _on_search_trigger() -> None:
            """Called after debounce interval elapses."""
            await _do_search()

        def _schedule_search() -> None:
            """Debounce: cancel any pending timer and schedule a new one."""
            current_query["value"] = search_input.value or ""

            # Cancel existing timer
            if debounce_timer["timer"] is not None:
                timer = debounce_timer["timer"]
                timer.cancel()  # type: ignore[attr-defined]
                debounce_timer["timer"] = None

            if not current_query["value"].strip():
                results_container.clear()
                status_label.set_text("")
                return

            # Schedule new search after 300ms debounce
            loop = asyncio.get_event_loop()
            handle = loop.call_later(
                0.3,
                lambda: asyncio.ensure_future(_on_search_trigger()),
            )
            debounce_timer["timer"] = handle

        def _on_mode_change(e: object) -> None:
            """Handle mode toggle change."""
            current_mode["value"] = mode_toggle.value
            if current_query["value"].strip():
                asyncio.ensure_future(_on_search_trigger())

        search_input.on("update:model-value", lambda _: _schedule_search())
        mode_toggle.on("update:model-value", lambda _: _on_mode_change(None))
