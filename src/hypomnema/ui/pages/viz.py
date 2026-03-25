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
        # Tooltip card
        tooltip_card = ui.card().classes("absolute").style(
            "display: none; top: 16px; right: 16px; z-index: 30; "
            "background: rgba(13,13,13,0.92); border: 1px solid #1e1e1e; "
            "backdrop-filter: blur(8px); min-width: 220px; max-width: 320px"
        )
        with tooltip_card:
            with ui.row().classes("items-center justify-between w-full mb-1"):
                tooltip_name = ui.label("").classes("text-sm font-medium")
                ui.button(
                    icon="close",
                    on_click=lambda: tooltip_card.style("display: none"),
                ).props("flat dense round size=xs color=grey-7")
            tooltip_link = ui.link("View engram", "/engrams/").classes(
                "text-xs no-underline"
            ).style("color: #7eb8da; font-size: 10px")

        # Graph fills entire viewport
        graph_container = ui.element("div").style(
            "width: 100%; height: 100vh; position: absolute; top: 0; left: 0"
        )

        def _on_node_click(eid: str, name: str) -> None:
            tooltip_name.set_text(name)
            tooltip_link._props["href"] = f"/engrams/{eid}"  # noqa: SLF001
            tooltip_link.update()
            tooltip_card.style(
                "display: block; top: 16px; right: 16px; z-index: 30; "
                "background: rgba(13,13,13,0.92); border: 1px solid #1e1e1e; "
                "backdrop-filter: blur(8px); min-width: 220px; max-width: 320px"
            )

        result = await render_graph(
            graph_container,
            on_node_click=_on_node_click,
            height="100vh",
        )

        # HUD overlay — bottom
        node_count = result.get("node_count", 0)
        edge_count = result.get("edge_count", 0)
        with ui.element("div").classes(
            "absolute bottom-3 left-3 right-3 flex items-end justify-between pointer-events-none"
        ).style("z-index: 20"):
            with ui.card().classes("pointer-events-auto").style(
                "background: rgba(13,13,13,0.75); border: 1px solid #1e1e1e; "
                "backdrop-filter: blur(8px); padding: 8px 12px"
            ):
                ui.label("spread").classes("text-xs tracking-wider uppercase mb-1").style(
                    "color: #4a4a4a; font-size: 9px; letter-spacing: 0.1em"
                )
                spread_slider = ui.slider(
                    min=0.3, max=3.0, step=0.05, value=1.0,
                ).props('dense dark color="grey-6"').classes("w-36")

                def _on_spread(e: object) -> None:
                    val = spread_slider.value
                    ui.run_javascript(f"if(window.__hypomnema_update_spread) window.__hypomnema_update_spread({val})")

                spread_slider.on("update:model-value", _on_spread)

            ui.label(
                f"{node_count} nodes / {edge_count} edges"
            ).classes("pointer-events-auto text-xs").style(
                "color: #333; font-family: 'JetBrains Mono', monospace; font-size: 10px"
            )
