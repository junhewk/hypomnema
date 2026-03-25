"""Sidebar minimap — small 2D SVG projection of the knowledge graph.

Renders a compact overview of the graph using inline SVG via ui.html().
Clicking the minimap navigates to the full /viz page.
"""

from __future__ import annotations

import html
import logging
from typing import Any

from nicegui import app, ui

from hypomnema.ui.viz.transforms import cluster_color

logger = logging.getLogger(__name__)


async def _fetch_minimap_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch projections and edges for the minimap."""
    db = app.state.db
    if db is None:
        return [], []

    cursor = await db.execute(
        "SELECT p.engram_id, p.x, p.y, p.z, p.cluster_id "
        "FROM projections p"
    )
    proj_rows = await cursor.fetchall()
    await cursor.close()

    cursor = await db.execute(
        "SELECT source_engram_id, target_engram_id FROM edges LIMIT 2000"
    )
    edge_rows = await cursor.fetchall()
    await cursor.close()

    projections = [
        {
            "engram_id": r[0],
            "x": r[1],
            "y": r[2],
            "z": r[3],
            "cluster_id": r[4],
        }
        for r in proj_rows
    ]

    edges = [
        {
            "source_engram_id": r[0],
            "target_engram_id": r[1],
        }
        for r in edge_rows
    ]

    return projections, edges


def _project_2d(x: float, y: float, z: float) -> tuple[float, float]:
    """Simple isometric projection: drop z with slight offset."""
    return (x + z * 0.3, y + z * 0.3)


def _build_svg(
    projections: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    width: int,
    height: int,
) -> str:
    """Generate an SVG string for the minimap."""
    if not projections:
        return (
            f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg"'
            f' style="background: #0a0a0a; border-radius: 4px; cursor: pointer">'
            f'<text x="{width // 2}" y="{height // 2}" text-anchor="middle"'
            f' fill="#4a4a4a" font-size="9" font-family="monospace">no data</text>'
            f"</svg>"
        )

    # Project all points to 2D
    projected: list[tuple[float, float]] = []
    for p in projections:
        px, py = _project_2d(p["x"], p["y"], p["z"])
        projected.append((px, py))

    # Compute bounds
    min_x = min(pt[0] for pt in projected)
    max_x = max(pt[0] for pt in projected)
    min_y = min(pt[1] for pt in projected)
    max_y = max(pt[1] for pt in projected)

    range_x = max_x - min_x if max_x != min_x else 1.0
    range_y = max_y - min_y if max_y != min_y else 1.0

    # Normalize to fit within SVG with padding
    pad = 8
    usable_w = width - 2 * pad
    usable_h = height - 2 * pad

    # Maintain aspect ratio
    scale = min(usable_w / range_x, usable_h / range_y)
    offset_x = pad + (usable_w - range_x * scale) / 2
    offset_y = pad + (usable_h - range_y * scale) / 2

    def norm(pt: tuple[float, float]) -> tuple[float, float]:
        nx = (pt[0] - min_x) * scale + offset_x
        ny = (pt[1] - min_y) * scale + offset_y
        return (nx, ny)

    normalized = [norm(pt) for pt in projected]

    # Build position lookup by engram_id
    pos_idx: dict[str, int] = {}
    for i, p in enumerate(projections):
        pos_idx[p["engram_id"]] = i

    # Start SVG
    parts: list[str] = [
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg"'
        f' style="background: #0a0a0a; border-radius: 4px; cursor: pointer">'
    ]

    # Draw edges first (behind nodes)
    for edge in edges:
        si = pos_idx.get(edge["source_engram_id"])
        ti = pos_idx.get(edge["target_engram_id"])
        if si is None or ti is None:
            continue
        sx, sy = normalized[si]
        tx, ty = normalized[ti]
        parts.append(
            f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{tx:.1f}" y2="{ty:.1f}"'
            f' stroke="#1a1a1e" stroke-width="0.5"/>'
        )

    # Draw nodes
    for i, p in enumerate(projections):
        nx, ny = normalized[i]
        color = html.escape(cluster_color(p["cluster_id"] if p["cluster_id"] is not None else -1))
        parts.append(
            f'<circle cx="{nx:.1f}" cy="{ny:.1f}" r="1.8" fill="{color}" opacity="0.85"/>'
        )

    parts.append("</svg>")
    return "".join(parts)


async def render_minimap(width: int = 180, height: int = 120) -> None:
    """Render a small 2D minimap of the knowledge graph in the sidebar.

    :param width: SVG width in pixels
    :param height: SVG height in pixels
    """
    projections, edges = await _fetch_minimap_data()
    svg = _build_svg(projections, edges, width, height)

    with ui.element("div").classes("cursor-pointer").on(
        "click", lambda _: ui.navigate.to("/viz")
    ):
        ui.html(svg)
