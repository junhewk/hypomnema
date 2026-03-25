"""Reusable document card component for stream and search pages."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from hypomnema.ui.theme import SOURCE_STYLES
from hypomnema.ui.utils import time_ago


def render_document_card(
    doc: dict[str, Any],
    *,
    show_score: bool = False,
    show_edit: bool = False,
    score: float | None = None,
    match_type: str | None = None,
) -> None:
    """Render a single document card.

    :param doc: Document dict with standard column keys.
    :param show_score: If True, display a score/match-type badge.
    :param show_edit: If True, show an edit button (for scribbles).
    :param score: Numeric relevance score (used when show_score=True).
    :param match_type: Search match type string (used when show_score=True).
    """
    source_type = str(doc.get("source_type", "scribble"))
    style = SOURCE_STYLES.get(source_type, SOURCE_STYLES["scribble"])
    title = doc.get("tidy_title") or doc.get("title") or "Untitled"
    preview_text = str(doc.get("tidy_text") or doc.get("text") or "")[:280]
    created_at = str(doc.get("created_at", ""))
    doc_id = str(doc.get("id", ""))

    with ui.card().classes("w-full mb-3 animate-fade-up cursor-pointer").style(
        f"border-left: 2px solid {style['color']}"
    ).on("click", lambda _d=doc_id: ui.navigate.to(f"/documents/{_d}")):
        with ui.row().classes("items-center gap-2 mb-1"):
            ui.label(style["label"]).classes("source-badge").style(
                f"color: {style['color']}; background: {style['bg']}"
            )
            if show_score and score is not None and match_type is not None:
                match_color = {
                    "hybrid": "#7eb8da",
                    "semantic": "#b87eb8",
                    "keyword": "#b8a07e",
                }.get(match_type, "#6b6b6b")
                ui.label(f"{match_type} {score:.3f}").classes(
                    "source-badge"
                ).style(f"color: {match_color}; background: rgba(255,255,255,0.04)")
            else:
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

        ui.label(str(title)).classes("text-sm font-medium mb-1")

        if preview_text:
            ui.label(preview_text).classes("text-xs leading-relaxed").style(
                "color: #6b6b6b; display: -webkit-box; -webkit-line-clamp: 3; "
                "-webkit-box-orient: vertical; overflow: hidden"
            )

        ui.label(time_ago(created_at)).classes("text-muted text-xs mt-2")
