"""Lint page — knowledge graph health issues."""

from __future__ import annotations

import asyncio
from typing import Any

from nicegui import ui

from hypomnema.ui.layout import page_layout
from hypomnema.ui.utils import get_db

_SEVERITY_STYLES = {
    "error": {"color": "#e06c75", "icon": "error"},
    "warning": {"color": "#d4b06a", "icon": "warning"},
    "info": {"color": "#5e9eff", "icon": "info"},
}

_TYPE_LABELS = {
    "orphan": "Orphan Engram",
    "contradiction": "Contradiction",
    "missing_link": "Missing Link",
    "duplicate_candidate": "Duplicate Candidate",
}


@ui.page("/lint")
async def lint_page() -> None:
    """Knowledge graph health check page."""
    db = get_db()

    with page_layout("Lint"):
        ui.label("Knowledge Health").classes("text-display-lg mb-2")
        ui.label("Automated quality checks on the knowledge graph").classes(
            "text-xs mb-6"
        ).style("color: var(--fg-dim)")

        issues_container = ui.column().classes("w-full gap-0")

        async def _load_and_render() -> None:
            issues_container.clear()
            if db is None:
                with issues_container:
                    ui.label("Database not ready.").classes("text-muted text-xs")
                return

            from hypomnema.ontology.lint import get_lint_issues

            issues = await get_lint_issues(db, resolved=False, limit=100)

            with issues_container:
                if not issues:
                    ui.label("No issues found. Knowledge graph is healthy.").classes(
                        "text-xs text-center py-8"
                    ).style("color: #56c9a0")
                else:
                    # Group by type
                    grouped: dict[str, list[dict[str, Any]]] = {}
                    for issue in issues:
                        t = str(issue.get("issue_type", "unknown"))
                        grouped.setdefault(t, []).append(issue)

                    for issue_type, group in grouped.items():
                        label = _TYPE_LABELS.get(issue_type, issue_type)
                        ui.label(f"{label} ({len(group)})").classes("section-label mb-2 mt-4")

                        for issue in group:
                            _render_issue(issue)

                    ui.label(f"{len(issues)} unresolved issues").classes(
                        "text-muted text-xs text-center mt-4"
                    ).style("font-size: 10px")

        def _render_issue(issue: dict[str, Any]) -> None:
            issue_id = str(issue.get("id", ""))
            severity = str(issue.get("severity", "warning"))
            style = _SEVERITY_STYLES.get(severity, _SEVERITY_STYLES["warning"])
            engram_ids = issue.get("engram_ids", [])
            if isinstance(engram_ids, str):
                import json
                engram_ids = json.loads(engram_ids)

            with ui.card().classes("w-full mb-2").style(
                f"border-left: 2px solid {style['color']}"
            ):
                with ui.row().classes("items-center gap-2 mb-1"):
                    ui.icon(style["icon"]).classes("text-xs").style(
                        f"color: {style['color']}; font-size: 14px"
                    )
                    ui.label(str(issue.get("description", ""))).classes(
                        "text-xs"
                    ).style("color: var(--fg)")

                with ui.row().classes("items-center gap-2"):
                    for eid in engram_ids[:5]:
                        ui.link(eid[:8] + "...", f"/engrams/{eid}").classes(
                            "source-badge engram-link no-underline"
                        ).style(
                            "color: var(--accent); background: var(--accent-soft); "
                            "text-decoration: none; font-size: 9px"
                        )

                    async def _resolve(iid: str = issue_id) -> None:
                        from hypomnema.ontology.lint import resolve_lint_issue

                        if db is not None:
                            await resolve_lint_issue(db, iid)
                            ui.notify("Issue resolved", type="positive")
                            await _load_and_render()

                    ui.button(
                        "Resolve",
                        on_click=lambda _, iid=issue_id: asyncio.ensure_future(
                            _resolve(iid)
                        ),
                    ).props('flat dense color="grey-7" size="sm"').classes(
                        "text-xs ml-auto"
                    )

        # Run lint button
        async def _run_lint() -> None:
            if db is None:
                ui.notify("Database not ready", type="negative")
                return
            from hypomnema.ontology.lint import run_lint

            ui.notify("Running lint checks...", type="info")
            new_issues = await run_lint(db)
            ui.notify(
                f"Found {len(new_issues)} new issues" if new_issues else "No new issues",
                type="positive" if not new_issues else "warning",
            )
            await _load_and_render()

        ui.button(
            "Run Checks",
            icon="health_and_safety",
            on_click=_run_lint,
        ).props('flat dense color="grey-5"').classes("text-xs mb-4")

        await _load_and_render()
