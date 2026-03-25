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

  // Lights — bright ambient so nodes are clearly visible
  scene.add(new THREE.AmbientLight(0xffffff, 1.5));

  // Circle texture for flat dot sprites
  var canvas = document.createElement('canvas');
  canvas.width = 64; canvas.height = 64;
  var ctx = canvas.getContext('2d');
  ctx.beginPath();
  ctx.arc(32, 32, 30, 0, Math.PI * 2);
  ctx.fillStyle = '#ffffff';
  ctx.fill();
  var circleTexture = new THREE.CanvasTexture(canvas);

  // Force graph
  const graph = new ThreeForceGraph()
    .graphData(data)
    .nodeThreeObject(node => {
      const group = new THREE.Group();
      group.__graphData = node;
      // Flat circle sprite — size 0.03 base, up to 0.09 for top-ranked
      const size = 0.03 + (node.rank || 0) * 0.06;
      const spriteMat = new THREE.SpriteMaterial({
        color: new THREE.Color(node.color || '#787068'),
        transparent: true, opacity: 0.92,
        map: circleTexture
      });
      const dot = new THREE.Sprite(spriteMat);
      dot.scale.set(size, size, 1);
      group.add(dot);

      // Label for high-rank nodes
      if (node.show_label) {
        const sprite = new SpriteText(node.name);
        sprite.color = 'rgba(210,210,210,0.8)';
        sprite.textHeight = 0.03;
        sprite.backgroundColor = false;
        sprite.padding = 0;
        sprite.position.y = size * 0.5 + 0.025;
        group.add(sprite);
      }
      return group;
    })
    .linkVisibility(false); // disable built-in links — positions not set when forces are off

  // Disable forces — use UMAP fixed positions
  graph.d3Force('charge', null);
  graph.d3Force('link', null);
  graph.d3Force('center', null);
  graph.tickFrame();
  graph.tickFrame();
  scene.add(graph);

  // Render edges manually (forces are off, built-in links have no coords)
  // Store node position lookup that updates when nodes are dragged
  var nodeById = {};
  data.nodes.forEach(function(n) { nodeById[n.id] = n; });

  var edgeLines = []; // [{line, sid, tid}]
  var edgeGroup = new THREE.Group();
  edgeGroup.name = 'edges';
  data.links.forEach(function(link) {
    var sid = (typeof link.source === 'object') ? link.source.id : link.source;
    var tid = (typeof link.target === 'object') ? link.target.id : link.target;
    if (!nodeById[sid] || !nodeById[tid]) return;
    var c = 0.08 + (link.confidence || 0.3) * 0.15;
    var geo = new THREE.BufferGeometry();
    var positions = new Float32Array(6);
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    var mat = new THREE.LineBasicMaterial({
      color: new THREE.Color(c, c, c), transparent: true, opacity: 0.35
    });
    var line = new THREE.Line(geo, mat);
    edgeLines.push({line: line, sid: sid, tid: tid});
    edgeGroup.add(line);
  });
  scene.add(edgeGroup);

  // Update edge positions from current node fx/fy/fz
  function updateEdges() {
    edgeLines.forEach(function(e) {
      var n1 = nodeById[e.sid], n2 = nodeById[e.tid];
      if (!n1 || !n2) return;
      var pos = e.line.geometry.attributes.position.array;
      pos[0] = n1.fx; pos[1] = n1.fy; pos[2] = n1.fz;
      pos[3] = n2.fx; pos[4] = n2.fy; pos[5] = n2.fz;
      e.line.geometry.attributes.position.needsUpdate = true;
    });
  }
  updateEdges();

  // Floating detail card
  var panel = document.getElementById('hypo-detail-panel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'hypo-detail-panel';
    Object.assign(panel.style, {
      position: 'fixed', top: '16px', right: '16px',
      width: '260px', maxHeight: 'calc(100vh - 32px)',
      background: 'rgba(13,13,13,0.88)', border: '1px solid #1e1e1e',
      backdropFilter: 'blur(12px)', borderRadius: '6px',
      fontFamily: "'JetBrains Mono',monospace", color: '#d4d4d4',
      transition: 'opacity 0.2s ease, transform 0.2s ease',
      overflow: 'hidden auto', zIndex: '9999', boxSizing: 'border-box',
      opacity: '0', transform: 'translateX(10px)', pointerEvents: 'none'
    });
    document.body.appendChild(panel);
  }

  // Controls HUD (bottom-left)
  var hud = document.createElement('div');
  Object.assign(hud.style, {
    position: 'fixed', bottom: '16px', left: '72px',
    background: 'rgba(13,13,13,0.7)', border: '1px solid #1e1e1e',
    backdropFilter: 'blur(8px)', borderRadius: '4px',
    fontFamily: "'JetBrains Mono',monospace", color: '#4a4a4a',
    fontSize: '9px', padding: '8px 12px', zIndex: '9998',
    letterSpacing: '0.05em', lineHeight: '1.6'
  });
  hud.innerHTML = '<span style="color:#6b6b6b">orbit</span> drag'
    + ' &nbsp; <span style="color:#6b6b6b">zoom</span> scroll'
    + ' &nbsp; <span style="color:#6b6b6b">pan</span> right-drag'
    + ' &nbsp; <span style="color:#6b6b6b">spread</span> alt+scroll'
    + '<br><span style="color:#6b6b6b">move</span> drag node'
    + ' &nbsp; <span style="color:#6b6b6b">push/pull</span> alt+drag node'
    + ' &nbsp; <span style="color:#6b6b6b">inspect</span> click node'
    + ' &nbsp; <span style="color:#6b6b6b">'
    + data.nodes.length + '</span> nodes'
    + ' &nbsp; <span style="color:#6b6b6b">'
    + data.links.length + '</span> edges';
  document.body.appendChild(hud);

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
    panel.style.opacity = '1';
    panel.style.transform = 'translateX(0)';
    panel.style.pointerEvents = 'auto';
    var cb = document.getElementById('hypo-panel-close');
    if (cb) cb.onclick = function() {
      panel.style.opacity = '0';
      panel.style.transform = 'translateX(10px)';
      panel.style.pointerEvents = 'none';
    };
  }

  // Raycaster for click + drag
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  var mouseDown = new THREE.Vector2();

  // Node drag + click + push/pull
  var dragNode = null;
  var dragActive = false; // true only after movement threshold
  var dragPlane = new THREE.Plane();
  var dragOffset = new THREE.Vector3();
  var intersection = new THREE.Vector3();
  var pendingHit = null; // node hit on pointerdown, confirmed as drag after threshold

  renderer.domElement.addEventListener('pointerdown', function(e) {
    mouseDown.set(e.clientX, e.clientY);
    if (e.button !== 0) return;
    var rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    var hits = raycaster.intersectObjects(scene.children, true);
    for (var i = 0; i < hits.length; i++) {
      var obj = hits[i].object;
      while (obj && !obj.__data && !obj.__graphData) { obj = obj.parent; }
      var nd = obj && (obj.__graphData || obj.__data);
      if (nd) {
        pendingHit = obj;
        dragActive = false;
        return;
      }
    }
    pendingHit = null;
  });

  renderer.domElement.addEventListener('pointermove', function(e) {
    if (!pendingHit) return;
    var dist = Math.abs(e.clientX - mouseDown.x) + Math.abs(e.clientY - mouseDown.y);
    // Activate drag after 4px movement
    if (!dragActive && dist > 4) {
      dragActive = true;
      dragNode = pendingHit;
      controls.enabled = false;
      dragPlane.setFromNormalAndCoplanarPoint(
        camera.getWorldDirection(new THREE.Vector3()).negate(),
        dragNode.position
      );
      var rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((mouseDown.x - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((mouseDown.y - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      raycaster.ray.intersectPlane(dragPlane, intersection);
      dragOffset.copy(dragNode.position).sub(intersection);
      renderer.domElement.style.cursor = 'grabbing';
    }
    if (dragActive && dragNode) {
      var rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      if (e.altKey) {
        // Alt+drag: push/pull along camera direction
        var dy = e.clientY - mouseDown.y;
        var camDir = camera.getWorldDirection(new THREE.Vector3());
        var pushDist = dy * 0.005;
        dragNode.position.addScaledVector(camDir, pushDist);
        mouseDown.set(e.clientX, e.clientY);
      } else {
        // Normal drag: move on camera plane
        raycaster.ray.intersectPlane(dragPlane, intersection);
        var newPos = intersection.add(dragOffset);
        dragNode.position.copy(newPos);
      }
      var dd = dragNode.__graphData || dragNode.__data;
      if (dd) {
        dd.fx = dragNode.position.x;
        dd.fy = dragNode.position.y;
        dd.fz = dragNode.position.z;
        updateEdges();
      }
    }
  });

  renderer.domElement.addEventListener('pointerup', function(e) {
    var wasDrag = dragActive;
    if (dragNode) {
      controls.enabled = true;
      dragNode = null;
      dragActive = false;
      renderer.domElement.style.cursor = 'grab';
    }
    pendingHit = null;
    // Click (no drag) — show panel or close it
    if (!wasDrag && Math.abs(e.clientX-mouseDown.x)+Math.abs(e.clientY-mouseDown.y) < 4) {
      var rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      var hits = raycaster.intersectObjects(scene.children, true);
      var foundNode = false;
      for (var i = 0; i < hits.length; i++) {
        var obj = hits[i].object;
        while (obj && !obj.__data && !obj.__graphData) { obj = obj.parent; }
        var nd2 = obj && (obj.__graphData || obj.__data);
        if (nd2) { showPanel(nd2); foundNode = true; break; }
      }
      // Click on empty space — close panel
      if (!foundNode && panel) {
        panel.style.opacity = '0';
        panel.style.transform = 'translateX(10px)';
        panel.style.pointerEvents = 'none';
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
      while (obj && !obj.__data && !obj.__graphData) { obj = obj.parent; }
      var nd3 = obj && (obj.__graphData || obj.__data);
      if (nd3 && !nd3.show_label) {
        hoverSprite = new SpriteText(nd3.name);
        hoverSprite.color = 'rgba(220,220,220,0.9)';
        hoverSprite.textHeight = 0.035;
        hoverSprite.backgroundColor = false;
        hoverSprite.padding = 0;
        hoverSprite.position.copy(obj.position);
        hoverSprite.position.y += 0.08;
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

  // Spread: Alt+scroll scales node positions from centroid
  var spreadFactor = 1.0;
  // Compute centroid
  var _cx = 0, _cy = 0, _cz = 0;
  data.nodes.forEach(function(n) { _cx += n.fx; _cy += n.fy; _cz += n.fz; });
  _cx /= data.nodes.length; _cy /= data.nodes.length; _cz /= data.nodes.length;
  // Store offsets from centroid
  data.nodes.forEach(function(n) {
    n._dx = n.fx - _cx; n._dy = n.fy - _cy; n._dz = n.fz - _cz;
  });

  function applySpread() {
    data.nodes.forEach(function(n) {
      n.fx = _cx + n._dx * spreadFactor;
      n.fy = _cy + n._dy * spreadFactor;
      n.fz = _cz + n._dz * spreadFactor;
      n.x = n.fx; n.y = n.fy; n.z = n.fz;
    });
    graph.graphData(graph.graphData());
    updateEdges();
  }

  renderer.domElement.addEventListener('wheel', function(e) {
    if (!e.altKey) return;
    e.preventDefault();
    e.stopPropagation();
    spreadFactor += e.deltaY > 0 ? -0.08 : 0.08;
    spreadFactor = Math.max(0.3, Math.min(5.0, spreadFactor));
    applySpread();
  }, {passive: false, capture: true});
  // Disable orbit zoom when alt is held
  renderer.domElement.addEventListener('wheel', function(e) {
    controls.enableZoom = !e.altKey;
  }, {capture: true});

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

    init_js = _GRAPH_INIT_JS.replace("%%GRAPH_DATA%%", json.dumps(graph_data, ensure_ascii=False))
    init_js = init_js.replace("%%BG_COLOR%%", _BG_COLOR)

    with container:
        ui.html(div_html).style(f"width: 100%; height: {height}")

    # Run after DOM is ready
    ui.timer(0.5, lambda: ui.run_javascript(init_js), once=True)

    return {
        "node_count": len(graph_data["nodes"]),
        "edge_count": len(graph_data["links"]),
    }
