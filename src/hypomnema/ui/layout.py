"""Navigation sidebar and page layout shell."""

from __future__ import annotations

import asyncio

from nicegui import app, ui

_NAV_ITEMS = [
    {"label": "Stream", "icon": "rss_feed", "path": "/"},
    {"label": "Search", "icon": "search", "path": "/search"},
    {"label": "Settings", "icon": "settings", "path": "/settings"},
]


def sidebar() -> None:
    """Render the collapsible navigation sidebar."""
    with ui.left_drawer(value=True, bordered=True).classes("px-2 py-4") as drawer:
        drawer.props("width=200 mini-width=56 mini-to-overlay")

        # Logo
        ui.label("hypomnema").classes(
            "text-sm font-bold tracking-wider uppercase text-center w-full mb-1"
        ).style("color: #d4d4d4; letter-spacing: 0.15em")
        ui.label("ontological synthesizer").classes(
            "text-[9px] text-center w-full mb-6"
        ).style("color: #4a4a4a; letter-spacing: 0.1em")

        ui.separator().classes("mb-4").style("background: #1e1e1e")

        # Nav items — use div + on_click to avoid nested <a> tag issues
        for item in _NAV_ITEMS:
            path = item["path"]  # capture for closure
            with ui.element("div").classes(
                "relative flex items-center gap-3 px-3 py-2 rounded cursor-pointer"
            ).style(
                "color: #6b6b6b; transition: color 0.15s, background 0.15s"
            ).on(
                "mouseenter", lambda e: e.sender.style("color: #d4d4d4; background: rgba(255,255,255,0.03)")
            ).on(
                "mouseleave", lambda e: e.sender.style("color: #6b6b6b; background: transparent")
            ).on("click", lambda _, p=path: ui.navigate.to(p)):
                ui.icon(item["icon"]).classes("text-lg")
                ui.label(item["label"]).classes("text-xs tracking-wider uppercase")

        # Spacer + minimap + viz link at bottom
        ui.space()
        ui.separator().classes("my-4").style("background: #1e1e1e")

        # Minimap container — populated asynchronously after page load.
        # TODO: cache minimap SVG across pages to avoid re-querying on every navigation.
        minimap_container = ui.element("div").classes("px-1 mb-2")

        async def _load_minimap() -> None:
            if getattr(app.state, "db", None) is None:
                return
            try:
                from hypomnema.ui.viz.minimap import render_minimap

                with minimap_container:
                    await render_minimap(width=176, height=110)
            except Exception:
                pass  # Silently skip minimap if data unavailable

        asyncio.ensure_future(_load_minimap())

        # Viz link
        with ui.element("div").classes(
            "relative flex items-center gap-3 px-3 py-2 rounded cursor-pointer"
        ).style("color: #6b6b6b").on("click", lambda: ui.navigate.to("/viz")):
            ui.icon("hub").classes("text-lg")
            ui.label("Visualization").classes("text-xs tracking-wider uppercase")

        ui.separator().classes("my-2").style("background: #1e1e1e")

        # Collapse button
        def _toggle_drawer() -> None:
            drawer.toggle()

        with ui.element("div").classes(
            "flex items-center gap-3 px-3 py-2 rounded cursor-pointer"
        ).style("color: #4a4a4a").on("click", _toggle_drawer):
            ui.icon("chevron_left").classes("text-lg")
            ui.label("Collapse").classes("text-xs tracking-wider uppercase")


def page_layout(title: str | None = None) -> ui.element:
    """Create the standard page layout with sidebar.

    Returns the main content container to use as a context manager.
    """
    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600'
        '&display=swap" rel="stylesheet">'
    )
    from hypomnema.ui.theme import CUSTOM_CSS

    ui.add_head_html(CUSTOM_CSS)

    sidebar()

    container = ui.element("main").classes("mx-auto max-w-2xl px-4 py-8 w-full")
    return container
