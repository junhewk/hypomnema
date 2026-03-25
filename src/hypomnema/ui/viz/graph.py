"""3D graph rendering using Three.js + three-forcegraph.

Uses raw Three.js for full control over node sizing and labels.
Embeds via ui.html() for the container div, ui.run_javascript() for
the Three.js scene initialization (runs after DOM is ready).
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
) -> dict[str, Any]:
    """Build graph data with UMAP positions, cluster colors, PageRank sizing."""
    page_ranks = compute_page_rank(edges)
    max_rank = max(page_ranks.values()) if page_ranks else 1.0
    node_ids = {p["engram_id"] for p in projections}

    nodes = []
    for p in projections:
        eid = p["engram_id"]
        rank = page_ranks.get(eid, 0.0)
        norm_rank = rank / max_rank if max_rank > 0 else 0.0
        nodes.append({
            "id": eid,
            "name": p["canonical_name"],
            "fx": float(p["x"]),
            "fy": float(p["y"]),
            "fz": float(p["z"]),
            "color": cluster_color(p["cluster_id"]),
            "cluster_id": p["cluster_id"],
            "rank": norm_rank,
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


# Raw Three.js + three-forcegraph initialization.
# Executed via ui.run_javascript() after DOM is ready.
_GRAPH_INIT_JS = """
(async () => {
  const THREE = await import('https://esm.sh/three@0.175');
  const {default: ThreeForceGraph} = await import('https://esm.sh/three-forcegraph@1?external=three');
  const {default: SpriteText} = await import('https://esm.sh/three-spritetext@1?external=three');
  const {OrbitControls} = await import('https://esm.sh/three@0.175/addons/controls/OrbitControls.js');

  const el = document.getElementById('hypo-graph-container');
  if (!el) return;

  const data = %%GRAPH_DATA%%;
  const W = el.clientWidth;
  const H = el.clientHeight;

  // Scene
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('%%BG_COLOR%%');

  // Camera
  const camera = new THREE.PerspectiveCamera(50, W / H, 0.1, 1000);
  camera.position.set(0, 0, 12);

  // Renderer
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setSize(W, H);
  renderer.setPixelRatio(window.devicePixelRatio);
  el.appendChild(renderer.domElement);

  // Orbit controls
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.1;

  // Lights
  scene.add(new THREE.AmbientLight(0x666666));
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
  dirLight.position.set(5, 10, 7);
  scene.add(dirLight);

  // Force graph
  const graph = new ThreeForceGraph()
    .graphData(data)
    .nodeThreeObject(node => {
      const group = new THREE.Group();
      // Sphere — radius 0.04 base, up to 0.1 for top-ranked
      const r = 0.04 + (node.rank || 0) * 0.06;
      const geo = new THREE.SphereGeometry(r, 16, 12);
      const mat = new THREE.MeshPhongMaterial({
        color: new THREE.Color(node.color || '#787068'),
        transparent: true, opacity: 0.9,
        shininess: 40
      });
      group.add(new THREE.Mesh(geo, mat));

      // Label for high-rank nodes
      if (node.show_label) {
        const sprite = new SpriteText(node.name);
        sprite.color = 'rgba(200,200,200,0.75)';
        sprite.textHeight = 0.08;
        sprite.backgroundColor = 'rgba(10,10,10,0.5)';
        sprite.padding = 0.5;
        sprite.borderRadius = 0.5;
        sprite.position.y = r + 0.06;
        group.add(sprite);
      }
      return group;
    })
    .linkColor(link => {
      var c = Math.round((0.1 + (link.confidence || 0.3) * 0.15) * 255);
      return 'rgb(' + c + ',' + c + ',' + c + ')';
    })
    .linkWidth(0.004)
    .linkOpacity(0.4);

  // Disable forces — use UMAP fixed positions
  graph.d3Force('charge', null);
  graph.d3Force('link', null);
  graph.d3Force('center', null);
  graph.tickFrame();
  graph.tickFrame();
  scene.add(graph);

  // Right detail panel
  var panel = document.getElementById('hypo-detail-panel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'hypo-detail-panel';
    Object.assign(panel.style, {
      position: 'fixed', top: '0', right: '0', width: '0', height: '100vh',
      background: '#0d0d0d', borderLeft: '1px solid #1e1e1e',
      fontFamily: "'JetBrains Mono',monospace", color: '#d4d4d4',
      transition: 'width 0.2s ease', overflow: 'hidden auto',
      zIndex: '9999', boxSizing: 'border-box'
    });
    document.body.appendChild(panel);
  }

  function showPanel(node) {
    var edges = data.links.filter(function(l) {
      var s = (typeof l.source === 'object') ? l.source.id : l.source;
      var t = (typeof l.target === 'object') ? l.target.id : l.target;
      return s === node.id || t === node.id;
    });
    var html = '<div style="padding:16px">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">';
    html += '<div style="font-size:13px;font-weight:500">' + (node.name || node.id) + '</div>';
    html += '<div id="hypo-panel-close" style="cursor:pointer;color:#4a4a4a;font-size:18px">&times;</div></div>';
    html += '<div style="font-size:10px;color:#6b6b6b;margin-bottom:12px">';
    html += 'cluster ' + (node.cluster_id != null ? node.cluster_id : '-');
    html += ' &middot; rank ' + Math.round((node.rank || 0) * 100) + '%</div>';
    html += '<a href="/engrams/' + node.id + '" style="display:inline-block;color:#7eb8da;';
    html += 'font-size:11px;text-decoration:none;margin-bottom:16px;padding:4px 8px;';
    html += 'border:1px solid #1e1e1e;border-radius:3px">View engram</a>';
    html += '<div style="font-size:10px;color:#4a4a4a;text-transform:uppercase;';
    html += 'letter-spacing:0.1em;margin-bottom:8px">Connections (' + edges.length + ')</div>';
    edges.slice(0, 20).forEach(function(l) {
      var s = (typeof l.source === 'object') ? l.source : data.nodes.find(function(n){return n.id===l.source});
      var t = (typeof l.target === 'object') ? l.target : data.nodes.find(function(n){return n.id===l.target});
      var other = (s && s.id === node.id) ? t : s;
      if (!other) return;
      html += '<div style="padding:4px 0;border-bottom:1px solid #1a1a1a;font-size:11px">';
      html += '<a href="/engrams/' + other.id + '" style="color:#7eb8da;text-decoration:none">';
      html += (other.name || other.id) + '</a>';
      html += '<span style="color:#4a4a4a;margin-left:6px">' + Math.round((l.confidence||0)*100) + '%</span></div>';
    });
    if (edges.length > 20) html += '<div style="color:#4a4a4a;font-size:10px;padding-top:4px">'
      + '+' + (edges.length-20) + ' more</div>';
    html += '</div>';
    panel.innerHTML = html;
    panel.style.width = '260px';
    var cb = document.getElementById('hypo-panel-close');
    if (cb) cb.onclick = function() { panel.style.width = '0'; };
  }

  // Raycaster for node click
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  var mouseDown = new THREE.Vector2();

  renderer.domElement.addEventListener('pointerdown', function(e) {
    mouseDown.set(e.clientX, e.clientY);
  });
  renderer.domElement.addEventListener('pointerup', function(e) {
    // Only click if mouse didn't move (not a drag)
    if (Math.abs(e.clientX - mouseDown.x) + Math.abs(e.clientY - mouseDown.y) > 5) return;
    var rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    var hits = raycaster.intersectObjects(scene.children, true);
    for (var i = 0; i < hits.length; i++) {
      var obj = hits[i].object;
      while (obj && !obj.__data) { obj = obj.parent; }
      if (obj && obj.__data) {
        showPanel(obj.__data);
        return;
      }
    }
  });

  // Hover label
  var hoverSprite = null;
  renderer.domElement.addEventListener('pointermove', function(e) {
    var rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    var hits = raycaster.intersectObjects(scene.children, true);
    if (hoverSprite) { scene.remove(hoverSprite); hoverSprite = null; }
    for (var i = 0; i < hits.length; i++) {
      var obj = hits[i].object;
      while (obj && !obj.__data) { obj = obj.parent; }
      if (obj && obj.__data && !obj.__data.show_label) {
        hoverSprite = new SpriteText(obj.__data.name);
        hoverSprite.color = 'rgba(220,220,220,0.9)';
        hoverSprite.textHeight = 0.07;
        hoverSprite.backgroundColor = 'rgba(10,10,10,0.7)';
        hoverSprite.padding = 0.4;
        hoverSprite.borderRadius = 0.5;
        hoverSprite.position.copy(obj.position);
        hoverSprite.position.y += 0.12;
        scene.add(hoverSprite);
        renderer.domElement.style.cursor = 'pointer';
        return;
      }
    }
    renderer.domElement.style.cursor = 'grab';
  });

  // Resize
  window.addEventListener('resize', function() {
    var w = el.clientWidth, h = el.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  });

  // Fit camera to data bounds
  var xs = data.nodes.map(function(n){return n.fx});
  var ys = data.nodes.map(function(n){return n.fy});
  var zs = data.nodes.map(function(n){return n.fz});
  var cx = (Math.min.apply(null,xs)+Math.max.apply(null,xs))/2;
  var cy = (Math.min.apply(null,ys)+Math.max.apply(null,ys))/2;
  var cz = (Math.min.apply(null,zs)+Math.max.apply(null,zs))/2;
  var maxR = Math.max.apply(null, data.nodes.map(function(n){
    return Math.sqrt(Math.pow(n.fx-cx,2)+Math.pow(n.fy-cy,2)+Math.pow(n.fz-cz,2));
  }));
  controls.target.set(cx, cy, cz);
  camera.position.set(cx, cy, cz + Math.max(maxR * 2.5, 3));

  // Animate
  function animate() {
    requestAnimationFrame(animate);
    graph.tickFrame();
    controls.update();
    renderer.render(scene, camera);
  }
  animate();
})();
"""


async def render_graph(
    container: ui.element,
    *,
    height: str = "100vh",
) -> dict[str, int]:
    """Render the 3D graph into the given container.

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

    graph_data = _build_graph_data(projections, edges)

    div_html = '<div id="hypo-graph-container" style="width:100%;height:100%;background:%%BG_COLOR%%"></div>'
    div_html = div_html.replace("%%BG_COLOR%%", _BG_COLOR)

    init_js = _GRAPH_INIT_JS.replace("%%GRAPH_DATA%%", json.dumps(graph_data))
    init_js = init_js.replace("%%BG_COLOR%%", _BG_COLOR)

    with container:
        ui.html(div_html).style(f"width: 100%; height: {height}")

    # Run after DOM is ready
    ui.timer(0.5, lambda: ui.run_javascript(init_js), once=True)

    return {
        "node_count": len(graph_data["nodes"]),
        "edge_count": len(graph_data["links"]),
    }
