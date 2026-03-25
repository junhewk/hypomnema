"""Visualization page — full 3D knowledge graph with interactive controls."""

from __future__ import annotations

import logging

from nicegui import ui

from hypomnema.ui.viz.graph import render_graph

logger = logging.getLogger(__name__)


@ui.page("/viz")
async def viz_page() -> None:
    """Full visualization page with 3D force-directed graph."""
    from hypomnema.ui.theme import CUSTOM_CSS

    ui.add_head_html(CUSTOM_CSS)
    ui.add_head_html(
        '<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600'
        '&display=swap" rel="stylesheet">'
    )
    # Force full viewport, no scroll
    ui.add_head_html("""
    <style>
    body, html { margin: 0; padding: 0; overflow: hidden; height: 100vh; }
    .nicegui-content { padding: 0 !important; height: 100vh; overflow: hidden; }
    .q-page { padding: 0 !important; min-height: 100vh !important; }
    </style>
    """)

    from hypomnema.ui.layout import sidebar

    sidebar(mini=True)

    # Full viewport container
    with ui.element("main").classes("w-full relative").style(
        "height: 100vh; background: #0a0a0a; overflow: hidden"
    ):
        # Graph fills entire viewport (tooltip handled in JS)
        graph_container = ui.element("div").style(
            "width: 100%; height: 100vh; position: absolute; top: 0; left: 0"
        )

        result = await render_graph(
            graph_container,
            height="100vh",
        )

        # HUD overlay — bottom
        node_count = result.get("node_count", 0)
        edge_count = result.get("edge_count", 0)
        # Stats overlay — bottom right
        ui.label(
            f"{node_count} nodes / {edge_count} edges"
        ).classes("absolute bottom-3 right-3 text-xs pointer-events-none").style(
            "z-index: 20; color: #333; font-family: 'JetBrains Mono', monospace; font-size: 10px"
        )
