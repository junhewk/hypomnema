"""3D graph rendering component using NiceGUI's ui.scene().

Fetches projection data from the database and renders an interactive 3D
knowledge graph with point cloud nodes, edge lines, orbit controls,
and click-to-inspect behavior.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from nicegui import app, ui

from hypomnema.ui.viz.transforms import (
    cluster_color_rgb,
    compute_data_bounds,
    compute_page_rank,
)

logger = logging.getLogger(__name__)

# Edge color: semi-transparent warm gray baked against dark background
_EDGE_COLOR = "#2a2a2e"
_BG_COLOR = "#08080a"


async def _fetch_projections() -> list[dict[str, Any]]:
    """Fetch projections joined with engram names."""
    db = app.state.db
    if db is None:
        return []
    cursor = await db.execute(
        "SELECT p.engram_id, e.canonical_name, p.x, p.y, p.z, p.cluster_id "
        "FROM projections p JOIN engrams e ON p.engram_id = e.id"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        {
            "engram_id": r[0],
            "canonical_name": r[1],
            "x": r[2],
            "y": r[3],
            "z": r[4],
            "cluster_id": r[5],
        }
        for r in rows
    ]


async def _fetch_edges() -> list[dict[str, Any]]:
    """Fetch edges for rendering."""
    db = app.state.db
    if db is None:
        return []
    cursor = await db.execute(
        "SELECT source_engram_id, target_engram_id, confidence "
        "FROM edges ORDER BY confidence DESC LIMIT 5000"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        {
            "source_engram_id": r[0],
            "target_engram_id": r[1],
            "confidence": r[2],
        }
        for r in rows
    ]


def _node_size(rank: float) -> float:
    """Map PageRank (0-1 normalized) to node point size.

    Base size 4px, top nodes (rank > 0.85 of max) scale up to 18px.
    """
    if rank > 0.85:
        return 4.0 + 14.0 * ((rank - 0.85) / 0.15)
    return 4.0


async def render_graph(
    container: ui.element,
    *,
    on_node_click: Callable[[str], None] | None = None,
    height: str = "600px",
    spread: float = 1.0,
) -> dict[str, Any]:
    """Render the 3D knowledge graph into the given container.

    :param container: parent NiceGUI element to render into
    :param on_node_click: callback receiving engram_id when a node is clicked
    :param height: CSS height for the scene
    :param spread: scale multiplier applied to all positions
    :returns: dict with node_count, edge_count for HUD display
    """
    projections = await _fetch_projections()
    edges = await _fetch_edges()

    if not projections:
        with container:
            ui.label("No visualization data. Upload some documents first.").classes(
                "text-muted text-xs text-center py-16"
            )
        return {"node_count": 0, "edge_count": 0}

    # Build position lookup
    pos_map: dict[str, tuple[float, float, float]] = {}
    for p in projections:
        pos_map[p["engram_id"]] = (
            p["x"] * spread,
            p["y"] * spread,
            p["z"] * spread,
        )

    # PageRank for node sizing
    page_ranks = compute_page_rank(edges)

    # Compute camera position from data bounds
    positions = list(pos_map.values())
    centroid, radius = compute_data_bounds(positions)
    cam_distance = max(radius * 2.5, 10.0)

    # Build point cloud data as lists-of-lists for NiceGUI
    points_data: list[list[float]] = []
    colors_data: list[list[float]] = []
    engram_ids_ordered: list[str] = []

    for p in projections:
        eid = p["engram_id"]
        x, y, z = pos_map[eid]
        points_data.append([x, y, z])

        r, g, b = cluster_color_rgb(p["cluster_id"])
        colors_data.append([r, g, b])

        engram_ids_ordered.append(eid)

    # Determine point size from PageRank (use average for the point cloud,
    # since NiceGUI point_cloud uses a single point_size for all points)
    ranks = [page_ranks.get(eid, 0.0) for eid in engram_ids_ordered]
    avg_size = sum(_node_size(r) for r in ranks) / len(ranks) if ranks else 4.0

    # Build scene
    # Parse numeric height for scene, fall back to 600 for CSS calc() values
    try:
        height_px = int(height.replace("px", ""))
    except ValueError:
        height_px = 600

    def _handle_click(e: Any) -> None:
        """Handle scene click events to identify clicked nodes."""
        if not e.hits:
            return
        hit = e.hits[0]
        # The point cloud object uses the name we set; map back to engram
        obj_name = hit.object_name
        if obj_name and obj_name.startswith("engram:"):
            eid = obj_name[7:]
            if on_node_click:
                on_node_click(eid)

    with container:
        scene = ui.scene(
            width=0,  # will be overridden by CSS
            height=height_px,
            grid=False,
            background_color=_BG_COLOR,
            on_click=_handle_click,
        ).classes("w-full").style(f"height: {height}")

        with scene:
            # Render nodes as individual spheres for click detection,
            # since point_cloud doesn't support per-point naming for click identification.
            # For large graphs, we also add a point cloud for visual appearance.

            # Point cloud for visual rendering (efficient for many points)
            pc = scene.point_cloud(
                points_data,
                colors=colors_data,
                point_size=avg_size,
            )
            pc.with_name("graph_points")

            # Render individual small transparent spheres for click targets
            # Only for reasonably-sized graphs to avoid performance issues
            if len(projections) <= 2000:
                for p in projections:
                    eid = p["engram_id"]
                    x, y, z = pos_map[eid]
                    rank = page_ranks.get(eid, 0.0)
                    size = _node_size(rank) * 0.05  # Scale sphere radius relative to scene
                    r, g, b = cluster_color_rgb(p["cluster_id"])
                    hex_color = f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

                    sphere = scene.sphere(radius=size).move(x, y, z)
                    sphere.material(color=hex_color, opacity=0.0)  # Invisible, just for click
                    sphere.with_name(f"engram:{eid}")

            # Render edges as lines
            edge_count = 0
            for edge in edges:
                src_pos = pos_map.get(edge["source_engram_id"])
                tgt_pos = pos_map.get(edge["target_engram_id"])
                if src_pos is None or tgt_pos is None:
                    continue

                line = scene.line(
                    list(src_pos),
                    list(tgt_pos),
                )
                # Bake opacity into color against dark background
                confidence = float(edge.get("confidence", 0.5))
                opacity = min(0.15 + confidence * 0.3, 0.45)
                bg = (0.031, 0.031, 0.039)
                base = (0.68, 0.72, 0.80)
                er = bg[0] + (base[0] - bg[0]) * opacity
                eg = bg[1] + (base[1] - bg[1]) * opacity
                eb = bg[2] + (base[2] - bg[2]) * opacity
                line_color = f"#{int(er * 255):02x}{int(eg * 255):02x}{int(eb * 255):02x}"
                line.material(color=line_color, opacity=0.6)
                edge_count += 1

        # Position camera
        scene.move_camera(
            x=centroid[0],
            y=centroid[1] - cam_distance * 0.8,
            z=centroid[2] + cam_distance * 0.6,
            look_at_x=centroid[0],
            look_at_y=centroid[1],
            look_at_z=centroid[2],
            duration=0,
        )

    return {
        "node_count": len(projections),
        "edge_count": edge_count,
    }
