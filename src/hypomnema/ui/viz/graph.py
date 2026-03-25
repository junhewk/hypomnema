"""3D graph rendering using 3d-force-graph (Three.js-based).

Embeds the graph via ui.html() + CDN, communicates data via run_javascript.
Provides orbit, zoom, node drag, force-directed spread, and always-on labels
for high-PageRank nodes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from nicegui import app, ui

from hypomnema.ui.viz.transforms import (
    cluster_color,
    compute_page_rank,
)

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
            # Size: base 0.3, top nodes up to 1.0
            "size": 0.3 + norm_rank * 0.7,
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


_GRAPH_DIV = '<div id="force-graph-container" style="width:100%; height:100%; background:{{BG_COLOR}};"></div>'

# JavaScript executed via ui.run_javascript (no <script> tags)
_GRAPH_INIT_JS = """
(async () => {
  const {default: ForceGraph3D} = await import('https://esm.sh/3d-force-graph@1?deps=three@0.175');
  const {default: SpriteText} = await import('https://esm.sh/three-spritetext@1');

  const wrapper = document.getElementById('force-graph-container');
  if (!wrapper) { console.error('force-graph-container not found'); return; }

  // Create layout: graph (left) + detail panel (right)
  wrapper.style.display = 'flex';
  const container = document.createElement('div');
  container.style.cssText = 'flex:1;height:100%;position:relative';
  wrapper.appendChild(container);

  const panel = document.createElement('div');
  panel.id = 'hypo-detail-panel';
  Object.assign(panel.style, {
    width: '0', height: '100%', overflow: 'hidden auto',
    background: '#0d0d0d', borderLeft: '1px solid #1e1e1e',
    fontFamily: "'JetBrains Mono', monospace", color: '#d4d4d4',
    transition: 'width 0.25s ease', padding: '0', boxSizing: 'border-box'
  });
  wrapper.appendChild(panel);

  function showPanel(node) {
    const edges = graphData.links.filter(l => {
      const s = typeof l.source === 'object' ? l.source.id : l.source;
      const t = typeof l.target === 'object' ? l.target.id : l.target;
      return s === node.id || t === node.id;
    });
    let edgesHtml = '';
    edges.slice(0, 20).forEach(l => {
      const s = typeof l.source === 'object' ? l.source : graphData.nodes.find(n => n.id === l.source);
      const t = typeof l.target === 'object' ? l.target : graphData.nodes.find(n => n.id === l.target);
      const other = (s && s.id === node.id) ? t : s;
      if (!other) return;
      const conf = Math.round((l.confidence || 0) * 100);
      edgesHtml += '<div style="padding:4px 0;border-bottom:1px solid #1a1a1a;font-size:11px">'
        + '<a href="/engrams/' + other.id + '" style="color:#7eb8da;text-decoration:none">'
        + (other.name || other.id) + '</a>'
        + '<span style="color:#4a4a4a;margin-left:6px">' + conf + '%</span></div>';
    });
    if (edges.length > 20) edgesHtml += '<div style="color:#4a4a4a;font-size:10px;padding-top:4px">+'
      + (edges.length - 20) + ' more</div>';

    panel.innerHTML = '<div style="padding:16px">'
      + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">'
      + '<div style="font-size:14px;font-weight:500">' + (node.name || node.id) + '</div>'
      + '<div id="hypo-panel-close" '
      + 'style="cursor:pointer;color:#4a4a4a;font-size:16px">&times;</div></div>'
      + '<div style="font-size:10px;color:#6b6b6b;margin-bottom:12px">cluster '
      + (node.cluster_id != null ? node.cluster_id : 'none')
      + ' &middot; rank ' + Math.round((node.rank || 0) * 100) + '%</div>'
      + '<a href="/engrams/' + node.id + '" style="display:inline-block;color:#7eb8da;'
      + 'font-size:11px;text-decoration:none;margin-bottom:16px;padding:4px 8px;'
      + 'border:1px solid #1e1e1e;border-radius:3px">View engram &rarr;</a>'
      + '<div style="font-size:10px;color:#4a4a4a;text-transform:uppercase;letter-spacing:0.1em;'
      + 'margin-bottom:8px">Connections (' + edges.length + ')</div>'
      + edgesHtml + '</div>';
    panel.style.width = '280px';
    panel.style.padding = '0';
    var closeBtn = document.getElementById('hypo-panel-close');
    if (closeBtn) closeBtn.onclick = function() { panel.style.width = '0'; };
  }

  const graphData = {{GRAPH_DATA}};

  const graph = new ForceGraph3D(container)
    .backgroundColor('{{BG_COLOR}}')
    .graphData(graphData)
    .nodeVal(d => d.size)
    .nodeRelSize(1)
    .nodeColor(d => d.color)
    .nodeOpacity(0.9)
    .nodeResolution(16)
    .nodeLabel(d => d.name)
    .nodeThreeObjectExtend(true)
    .nodeThreeObject(node => {
      if (!node.show_label) return null;
      const sprite = new SpriteText(node.name);
      sprite.color = 'rgba(200,200,200,0.8)';
      sprite.textHeight = 0.4;
      sprite.backgroundColor = 'rgba(10,10,10,0.5)';
      sprite.padding = 0.3;
      sprite.borderRadius = 1;
      sprite.position.y = node.size * 0.3 + 0.5;
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
      if (!node || !node.id) return;
      showPanel(node);
    })
    .onNodeDragEnd(node => {
      node.fx = node.x;
      node.fy = node.y;
      node.fz = node.z;
    });

  graph.d3Force('charge', null);
  graph.d3Force('link', null);
  graph.d3Force('center', null);

  setTimeout(() => graph.zoomToFit(400, 50), 500);

  window.__hypomnema_graph = graph;
  window.__hypomnema_update_spread = (factor) => {
    const nodes = graph.graphData().nodes;
    nodes.forEach(n => {
      if (n._ox === undefined) { n._ox = n.fx; n._oy = n.fy; n._oz = n.fz; }
      n.fx = n._ox * factor;
      n.fy = n._oy * factor;
      n.fz = n._oz * factor;
      n.x = n.fx; n.y = n.fy; n.z = n.fz;
    });
    graph.graphData(graph.graphData());
    setTimeout(() => graph.zoomToFit(300, 50), 100);
  };
})();
"""


async def render_graph(
    container: ui.element,
    *,
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

    # Render div via ui.html, init graph via ui.run_javascript (runs after DOM is ready)
    div_html = _GRAPH_DIV.replace("{{BG_COLOR}}", _BG_COLOR)
    init_js = _GRAPH_INIT_JS.replace("{{GRAPH_DATA}}", json.dumps(graph_data))
    init_js = init_js.replace("{{BG_COLOR}}", _BG_COLOR)

    with container:
        ui.html(div_html).style(f"width: 100%; height: {height}")

    # Run after DOM is ready (ui.run_javascript waits for client connection)
    ui.timer(0.5, lambda: ui.run_javascript(init_js), once=True)

    return {
        "node_count": len(graph_data["nodes"]),
        "edge_count": len(graph_data["links"]),
    }
