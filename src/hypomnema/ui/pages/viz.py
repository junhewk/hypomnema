"""Visualization page — full 3D knowledge graph with interactive controls."""

from __future__ import annotations

import logging

from nicegui import ui

from hypomnema.ui.viz.graph import render_graph

logger = logging.getLogger(__name__)


@ui.page("/viz")
async def viz_page() -> None:
    """Full visualization page with 3D force-directed graph."""
    from hypomnema.ui.layout import apply_theme, sidebar

    apply_theme()

    # Force full viewport, no scroll
    ui.add_head_html("""
    <style>
    body, html { margin: 0; padding: 0; overflow: hidden; height: 100vh; }
    .nicegui-content { padding: 0 !important; height: 100vh; overflow: hidden; }
    .q-page { padding: 0 !important; min-height: 100vh !important; }
    </style>
    """)

    sidebar(mini=True)

    # Full viewport container
    with ui.element("main").classes("w-full relative").style(
        "height: 100vh; background: var(--bg); overflow: hidden"
    ):
        # Graph fills entire viewport (tooltip handled in JS)
        graph_container = ui.element("div").style(
            "width: 100%; height: 100vh; position: absolute; top: 0; left: 0"
        )

        result = await render_graph(
            graph_container,
            height="100vh",
        )

        # Clusters legend — top left, collapsible
        clusters = result.get("clusters", [])
        if clusters:
            with ui.element("div").classes("absolute").style(
                "top: 16px; left: 72px; z-index: 20; "
                "max-height: calc(100vh - 80px); overflow-y: auto"
            ):
                with ui.expansion("Clusters").classes("").props(
                    'dense header-class="text-xs uppercase tracking-wider"'
                ).style(
                    "background: rgba(13,13,13,0.8); backdrop-filter: blur(8px); "
                    "border: 1px solid #1e1e1e; border-radius: 4px; "
                    "min-width: 180px; max-width: 240px; "
                    "font-family: 'JetBrains Mono', monospace; color: #6b6b6b"
                ):
                    for c in clusters:
                        cid = c["cluster_id"]
                        label = c.get("label") or (f"cluster {cid}" if cid is not None else "noise")
                        color = c["color"]
                        count = c["count"]
                        with ui.row().classes("items-center gap-2 py-1").style(
                            "min-height: 0"
                        ):
                            ui.element("span").style(
                                f"width: 8px; height: 8px; border-radius: 50%; "
                                f"background: {color}; flex-shrink: 0"
                            )
                            ui.label(label).classes("text-xs truncate").style(
                                "color: #a0a0a0; flex: 1; min-width: 0"
                            )
                            ui.label(str(count)).classes("text-xs").style(
                                "color: #4a4a4a; flex-shrink: 0"
                            )

        # Stats overlay — bottom right
        node_count = result.get("node_count", 0)
        edge_count = result.get("edge_count", 0)
        ui.label(
            f"{node_count} nodes / {edge_count} edges"
        ).classes("absolute bottom-3 right-3 text-xs pointer-events-none").style(
            "z-index: 20; color: var(--fg-dim); "
            "font-family: var(--font-body); font-size: 10px"
        )
