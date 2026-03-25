"""3D graph rendering using 3d-force-graph (Three.js-based).

Embeds the graph via ui.html() + CDN, communicates data via run_javascript.
Provides orbit, zoom, node drag, force-directed spread, and always-on labels
for high-PageRank nodes.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from nicegui import app, ui

from hypomnema.ui.viz.transforms import (
    cluster_color,
    compute_page_rank,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_BG_COLOR = "#0a0a0a"

# PageRank threshold for always-visible labels (top ~15% of nodes)
_LABEL_RANK_THRESHOLD = 0.3


async def _fetch_projections() -> list[dict[str, Any]]:
    db = app.state.db
    if db is None:
        return []
    cursor = await db.execute(
        "SELECT p.engram_id, e.canonical_name, p.x, p.y, p.z, p.cluster_id "
        "FROM projections p JOIN engrams e ON p.engram_id = e.id"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [dict(r) for r in rows]


async def _fetch_edges() -> list[dict[str, Any]]:
    db = app.state.db
    if db is None:
        return []
    cursor = await db.execute(
        "SELECT source_engram_id, target_engram_id, confidence "
        "FROM edges ORDER BY confidence DESC LIMIT 5000"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [dict(r) for r in rows]


def _build_graph_data(
    projections: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    spread: float = 1.0,
) -> dict[str, Any]:
    """Build 3d-force-graph compatible data structure."""
    page_ranks = compute_page_rank(edges)
    max_rank = max(page_ranks.values()) if page_ranks else 1.0

    # Node IDs present in projections
    node_ids = {p["engram_id"] for p in projections}

    nodes = []
    for p in projections:
        eid = p["engram_id"]
        rank = page_ranks.get(eid, 0.0)
        norm_rank = rank / max_rank if max_rank > 0 else 0.0
        nodes.append({
            "id": eid,
            "name": p["canonical_name"],
            "x": float(p["x"]) * spread,
            "y": float(p["y"]) * spread,
            "z": float(p["z"]) * spread,
            # Fix positions (use UMAP layout, not force simulation)
            "fx": float(p["x"]) * spread,
            "fy": float(p["y"]) * spread,
            "fz": float(p["z"]) * spread,
            "cluster_id": p["cluster_id"],
            "color": cluster_color(p["cluster_id"]),
            "rank": norm_rank,
            # Size: base 2, top nodes up to 6
            "size": 2.0 + norm_rank * 4.0,
            # Show label for high-rank nodes
            "show_label": norm_rank >= _LABEL_RANK_THRESHOLD,
        })

    links = []
    for e in edges:
        src = e["source_engram_id"]
        tgt = e["target_engram_id"]
        if src in node_ids and tgt in node_ids:
            links.append({
                "source": src,
                "target": tgt,
                "confidence": float(e.get("confidence", 0.5)),
            })

    return {"nodes": nodes, "links": links}


_GRAPH_JS = """
<div id="force-graph-container" style="width:100%; height:100%; background:{{BG_COLOR}};"></div>
<script type="module">
import ForceGraph3D from 'https://esm.sh/3d-force-graph@1?deps=three@0.175';
import SpriteText from 'https://esm.sh/three-spritetext@1';

const container = document.getElementById('force-graph-container');
const graphData = {{GRAPH_DATA}};

const graph = new ForceGraph3D(container)
  .backgroundColor('{{BG_COLOR}}')
  .graphData(graphData)
  .nodeVal(d => d.size)
  .nodeColor(d => d.color)
  .nodeOpacity(0.9)
  .nodeResolution(16)
  .nodeLabel(d => d.name)
  .nodeThreeObjectExtend(true)
  .nodeThreeObject(node => {
    if (!node.show_label) return null;
    const sprite = new SpriteText(node.name);
    sprite.color = 'rgba(200,200,200,0.85)';
    sprite.textHeight = Math.max(1.2, node.size * 0.4);
    sprite.backgroundColor = 'rgba(10,10,10,0.6)';
    sprite.padding = 1;
    sprite.borderRadius = 2;
    sprite.position.y = node.size * 0.15 + 2;
    return sprite;
  })
  .linkColor(link => {
    const opacity = 0.08 + link.confidence * 0.15;
    const v = Math.round(opacity * 255);
    return `rgba(${v},${v},${v},${opacity})`;
  })
  .linkWidth(0.3)
  .linkOpacity(1.0)
  .onNodeClick(node => {
    if (node && node.id) {
      window.__hypomnema_node_click(node.id, node.name);
    }
  })
  .onNodeDragEnd(node => {
    // When user drags a node, fix it at the new position
    node.fx = node.x;
    node.fy = node.y;
    node.fz = node.z;
  });

// Disable force simulation (using UMAP fixed positions)
graph.d3Force('charge', null);
graph.d3Force('link', null);
graph.d3Force('center', null);

// Fit camera to data after initial render
setTimeout(() => {
  graph.zoomToFit(400, 50);
}, 500);

// Expose graph for Python control
window.__hypomnema_graph = graph;

// Spread update function
window.__hypomnema_update_spread = (factor) => {
  const nodes = graph.graphData().nodes;
  nodes.forEach(n => {
    if (n._ox === undefined) { n._ox = n.fx; n._oy = n.fy; n._oz = n.fz; }
    n.fx = n._ox * factor;
    n.fy = n._oy * factor;
    n.fz = n._oz * factor;
    n.x = n.fx;
    n.y = n.fy;
    n.z = n.fz;
  });
  graph.graphData(graph.graphData());
  setTimeout(() => graph.zoomToFit(300, 50), 100);
};
</script>
"""


async def render_graph(
    container: ui.element,
    *,
    on_node_click: Callable[[str, str], None] | None = None,
    height: str = "600px",
    spread: float = 1.0,
) -> dict[str, int]:
    """Render the 3D force graph into the given container.

    Returns dict with node_count and edge_count.
    """
    projections = await _fetch_projections()
    edges = await _fetch_edges()

    if not projections:
        with container:
            ui.label("No visualization data. Process some documents first.").classes(
                "text-muted text-xs text-center py-16"
            )
        return {"node_count": 0, "edge_count": 0}

    graph_data = _build_graph_data(projections, edges, spread)

    # Build the HTML with injected data
    html = _GRAPH_JS.replace("{{GRAPH_DATA}}", json.dumps(graph_data))
    html = html.replace("{{BG_COLOR}}", _BG_COLOR)

    with container:
        graph_div = ui.html(html).style(f"width: 100%; height: {height}")

    # Wire up node click callback via JavaScript bridge
    if on_node_click:
        def _handle_click(eid: str, name: str) -> None:
            on_node_click(eid, name)

        ui.run_javascript("""
            window.__hypomnema_node_click = (id, name) => {
                emitEvent('node_click', {id: id, name: name});
            };
        """)
        # NiceGUI event listener
        graph_div.on("node_click", lambda e: _handle_click(
            e.args.get("id", ""), e.args.get("name", ""),
        ))

    return {
        "node_count": len(graph_data["nodes"]),
        "edge_count": len(graph_data["links"]),
    }
