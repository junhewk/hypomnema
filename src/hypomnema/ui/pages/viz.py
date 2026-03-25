"""Visualization page — full 3D knowledge graph with HUD controls."""

from __future__ import annotations

import asyncio
import logging

from nicegui import app, ui

from hypomnema.ui.viz.graph import render_graph

logger = logging.getLogger(__name__)


def _viz_layout(title: str | None = None) -> ui.element:
    """Create a wide page layout for the visualization (no max-w-2xl constraint)."""
    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600'
        '&display=swap" rel="stylesheet">'
    )
    from hypomnema.ui.theme import CUSTOM_CSS

    ui.add_head_html(CUSTOM_CSS)

    from hypomnema.ui.layout import sidebar

    sidebar(collapsed=True, overlay=False)

    container = ui.element("main").classes("px-4 py-4 w-full")
    return container


@ui.page("/viz")
async def viz_page() -> None:
    """Full visualization page with 3D graph and HUD overlay."""
    with _viz_layout("Visualization"):
        # State
        spread_value: dict[str, float] = {"value": 1.0}
        stats: dict[str, int] = {"node_count": 0, "edge_count": 0}

        # Header row
        with ui.row().classes("items-center justify-between w-full mb-2"):
            ui.label("Visualization").classes("text-lg font-medium")
            ui.button(
                icon="arrow_back",
                on_click=lambda: ui.navigate.to("/"),
            ).props("flat dense round color=grey-7")

        # Tooltip card (created before graph so it can be referenced by click handler)
        tooltip_card = ui.card().classes("absolute").style(
            "display: none; top: 16px; right: 16px; z-index: 20; "
            "background: rgba(13,13,13,0.92); border: 1px solid #1e1e1e; "
            "backdrop-filter: blur(8px); min-width: 200px"
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

        # Graph container
        graph_container = ui.element("div").classes("w-full relative")

        # Render graph
        result = await render_graph(
            graph_container,
            on_node_click=lambda eid: _on_node_click(eid, tooltip_card, tooltip_name, tooltip_link),
            height="calc(100vh - 200px)",
            spread=spread_value["value"],
        )
        stats["node_count"] = result.get("node_count", 0)
        stats["edge_count"] = result.get("edge_count", 0)

        # HUD overlay
        with ui.element("div").classes(
            "absolute bottom-4 left-4 right-4 flex items-end justify-between pointer-events-none"
        ).style("z-index: 10"):
            # Left: controls panel
            with ui.card().classes("pointer-events-auto").style(
                "background: rgba(13,13,13,0.85); border: 1px solid #1e1e1e; "
                "backdrop-filter: blur(8px)"
            ):
                # Spread slider
                ui.label("spread").classes("text-xs tracking-wider uppercase mb-1").style(
                    "color: #6b6b6b; font-size: 9px; letter-spacing: 0.1em"
                )
                spread_slider = ui.slider(
                    min=0.3, max=3.0, step=0.1, value=1.0
                ).props('dense dark color="grey-6"').classes("w-40")

                ui.separator().classes("my-2").style("background: #1e1e1e")

                # Recompute button
                ui.button(
                    "Recompute UMAP",
                    on_click=lambda: asyncio.ensure_future(
                        _recompute(
                            graph_container, spread_value, stats, stats_label,
                            tooltip_card, tooltip_name, tooltip_link,
                        )
                    ),
                ).props('flat dense color="grey-6"').classes("text-xs w-full")

            # Right: stats
            stats_label: ui.label = ui.label(
                f"{stats['node_count']} nodes / {stats['edge_count']} edges"
            ).classes("pointer-events-auto text-xs").style(
                "color: #4a4a4a; font-family: 'JetBrains Mono', monospace; font-size: 10px"
            )

        # Wire up spread slider to re-render
        async def _on_spread_change() -> None:
            new_spread = spread_slider.value
            if new_spread == spread_value["value"]:
                return
            spread_value["value"] = new_spread
            graph_container.clear()
            result = await render_graph(
                graph_container,
                on_node_click=lambda eid: _on_node_click(eid, tooltip_card, tooltip_name, tooltip_link),
                height="calc(100vh - 200px)",
                spread=new_spread,
            )
            stats["node_count"] = result.get("node_count", 0)
            stats["edge_count"] = result.get("edge_count", 0)
            stats_label.set_text(f"{stats['node_count']} nodes / {stats['edge_count']} edges")

        # Debounce the slider (avoid re-render on every tick)
        debounce_handle: dict[str, object | None] = {"timer": None}

        def _schedule_spread_update() -> None:
            if debounce_handle["timer"] is not None:
                debounce_handle["timer"].cancel()  # type: ignore[attr-defined]
            loop = asyncio.get_event_loop()
            debounce_handle["timer"] = loop.call_later(
                0.5,
                lambda: asyncio.ensure_future(_on_spread_change()),
            )

        spread_slider.on("update:model-value", lambda _: _schedule_spread_update())


def _on_node_click(
    engram_id: str,
    tooltip_card: ui.card,
    tooltip_name: ui.label,
    tooltip_link: ui.link,
) -> None:
    """Handle node click: show tooltip card with engram info."""
    asyncio.ensure_future(_show_tooltip(engram_id, tooltip_card, tooltip_name, tooltip_link))


async def _show_tooltip(
    engram_id: str,
    tooltip_card: ui.card,
    tooltip_name: ui.label,
    tooltip_link: ui.link,
) -> None:
    """Fetch engram name and show tooltip."""
    db = app.state.db
    if db is None:
        return

    cursor = await db.execute(
        "SELECT canonical_name FROM engrams WHERE id = ?", (engram_id,)
    )
    row = await cursor.fetchone()
    await cursor.close()

    name = str(row[0]) if row else engram_id
    tooltip_name.set_text(name)
    tooltip_link._props["href"] = f"/engrams/{engram_id}"  # noqa: SLF001
    tooltip_link.update()
    tooltip_card.style("display: block")


async def _recompute(
    graph_container: ui.element,
    spread_value: dict[str, float],
    stats: dict[str, int],
    stats_label: ui.label,
    tooltip_card: ui.card,
    tooltip_name: ui.label,
    tooltip_link: ui.link,
) -> None:
    """Trigger UMAP recompute and re-render the graph."""
    db = app.state.db
    if db is None:
        ui.notify("Database not ready", type="negative")
        return

    ui.notify("Recomputing projections...", type="info")

    try:
        from hypomnema.visualization.projection import compute_projections

        await compute_projections(db)
        ui.notify("Projections recomputed", type="positive")

        # Re-render
        graph_container.clear()
        result = await render_graph(
            graph_container,
            on_node_click=lambda eid: _on_node_click(eid, tooltip_card, tooltip_name, tooltip_link),
            height="calc(100vh - 200px)",
            spread=spread_value["value"],
        )
        stats["node_count"] = result.get("node_count", 0)
        stats["edge_count"] = result.get("edge_count", 0)
        stats_label.set_text(f"{stats['node_count']} nodes / {stats['edge_count']} edges")
    except ImportError:
        ui.notify(
            "Projection dependencies not installed (umap-learn, scikit-learn)",
            type="warning",
        )
    except Exception as e:
        logger.exception("Failed to recompute projections")
        ui.notify(f"Recompute failed: {e}", type="negative")
