"""Navigation sidebar and page layout shell."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import app, ui

_NAV_ITEMS = [
    {"label": "Stream", "icon": "rss_feed", "path": "/"},
    {"label": "Search", "icon": "search", "path": "/search"},
    {"label": "Health", "icon": "health_and_safety", "path": "/lint"},
    {"label": "Settings", "icon": "settings", "path": "/settings"},
]

_ICON_PATH = Path(__file__).resolve().parent.parent.parent.parent / "static" / "icon.png"


def _active_theme_name() -> str:
    """Return the active theme name from app settings, or the default."""
    from hypomnema.ui.theme import DEFAULT_THEME

    settings = getattr(app.state, "settings", None)
    return getattr(settings, "ui_theme", DEFAULT_THEME) if settings else DEFAULT_THEME


def sidebar(*, mini: bool = False) -> ui.element:
    """Render the collapsible navigation sidebar.

    Args:
        mini: Start in mini (icon-only) mode. Drawer stays visible but narrow.

    Returns:
        The drawer element (for toggling from a mobile hamburger button).
    """
    is_mini = {"value": mini}

    # value=None lets Quasar auto-show above 1024px and hide on mobile
    with ui.left_drawer(value=None, bordered=True).classes("px-2 py-4") as drawer:
        drawer.props(f"width=200 mini-width=56 breakpoint=1024 {'mini' if mini else ''}")

        # Icon + logo
        with ui.element("div").classes("flex items-center gap-2 mb-1 px-1"):
            ui.image("/static/icon.png").classes("w-8 h-8 rounded flex-shrink-0")
            logo_text = ui.label("hypomnema").classes(
                "font-display text-sm font-bold tracking-wider uppercase"
            ).style("color: var(--fg); letter-spacing: 0.15em")
        subtitle = ui.label("ontological synthesizer").classes(
            "text-center w-full mb-6"
        ).style("color: var(--fg-dim); letter-spacing: 0.1em; font-size: 9px")

        ui.separator().classes("mb-4")

        # Nav items — icon always visible, label hidden in mini
        nav_labels: list[ui.label] = []
        for item in _NAV_ITEMS:
            path = item["path"]
            with ui.element("div").classes(
                "flex items-center gap-3 px-3 py-2 rounded cursor-pointer"
            ).style(
                "color: var(--fg-muted); transition: color 0.15s, background 0.15s"
            ).on(
                "mouseenter",
                lambda e: e.sender.style(
                    "color: var(--fg); background: var(--accent-soft)"
                ),
            ).on(
                "mouseleave",
                lambda e: e.sender.style(
                    "color: var(--fg-muted); background: transparent"
                ),
            ).on("click", lambda _, p=path: ui.navigate.to(p)):
                ui.icon(item["icon"]).classes("text-lg flex-shrink-0")
                lbl = ui.label(item["label"]).classes(
                    "text-xs tracking-wider uppercase"
                )
                nav_labels.append(lbl)

        # Spacer
        ui.space()
        ui.separator().classes("my-4")

        # Minimap container — hidden in mini mode
        minimap_container = ui.element("div").classes("px-1 mb-2")

        async def _load_minimap() -> None:
            if getattr(app.state, "db", None) is None:
                return
            try:
                from hypomnema.ui.viz.minimap import render_minimap

                with minimap_container:
                    await render_minimap(width=176, height=110)
            except Exception:
                pass

        asyncio.ensure_future(_load_minimap())

        # Viz link
        with ui.element("div").classes(
            "flex items-center gap-3 px-3 py-2 rounded cursor-pointer"
        ).style("color: var(--fg-muted)").on(
            "click", lambda: ui.navigate.to("/viz")
        ):
            ui.icon("hub").classes("text-lg flex-shrink-0")
            viz_label = ui.label("Visualization").classes(
                "text-xs tracking-wider uppercase"
            )

        ui.separator().classes("my-2")

        # Collapse/expand toggle
        with ui.element("div").classes(
            "flex items-center gap-3 px-3 py-2 rounded cursor-pointer"
        ).style("color: var(--fg-dim)") as collapse_btn:
            collapse_icon = ui.icon("chevron_left").classes(
                "text-lg flex-shrink-0"
            )
            collapse_label = ui.label("Collapse").classes(
                "text-xs tracking-wider uppercase"
            )

        # All text elements to show/hide on mini toggle
        text_elements = [
            logo_text,
            subtitle,
            *nav_labels,
            viz_label,
            collapse_label,
            minimap_container,
        ]

        def _apply_mini(is_collapsed: bool) -> None:
            for el in text_elements:
                el.set_visibility(not is_collapsed)
            collapse_icon.props(
                f"name={'chevron_right' if is_collapsed else 'chevron_left'}"
            )

        def _toggle_mini() -> None:
            is_mini["value"] = not is_mini["value"]
            if is_mini["value"]:
                drawer.props(add="mini")
            else:
                drawer.props(remove="mini")
            _apply_mini(is_mini["value"])

        collapse_btn.on("click", _toggle_mini)

        # Apply initial state
        if mini:
            _apply_mini(True)

    return drawer


def apply_theme() -> None:
    """Inject CSS variables, font imports, and Quasar colour overrides for the active theme."""
    from hypomnema.ui.theme import FONT_IMPORTS, MOBILE_CSS, get_colors, get_theme_css

    theme_name = _active_theme_name()

    ui.add_head_html(FONT_IMPORTS)
    ui.add_head_html(get_theme_css(theme_name))
    ui.add_head_html(MOBILE_CSS)
    ui.colors(**get_colors(theme_name))


def page_layout(title: str | None = None) -> ui.element:
    """Create the standard page layout with sidebar.

    Returns the main content container to use as a context manager.
    """
    apply_theme()

    drawer = sidebar()

    # Mobile header with hamburger toggle — hidden on desktop via CSS
    with ui.header().classes("mobile-header").style(
        "background: var(--bg-sidebar); "
        "border-bottom: 1px solid var(--border); "
        "padding: 8px 16px"
    ):
        ui.button(
            icon="menu",
            on_click=lambda: drawer.toggle(),  # type: ignore[attr-defined]
        ).props('flat dense round color="grey-6"')
        ui.label("hypomnema").classes(
            "font-display text-sm font-bold tracking-wider uppercase ml-2"
        ).style("color: var(--fg); letter-spacing: 0.15em")

    container = ui.element("main").classes("mx-auto max-w-2xl px-4 py-8 w-full")
    return container
