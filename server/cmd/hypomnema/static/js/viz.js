// Hypomnema 3D Knowledge Graph Visualization
// Raw Three.js + three-forcegraph — matching the Python NiceGUI version exactly.
// Features: PageRank node sizing, cluster colors, node drag, alt+scroll spread,
// hover labels, click detail panel, camera fitting.

const BG_COLOR = '#0a0a0a';
const LABEL_RANK_THRESHOLD = 0.3;

// Golden-angle HSL cluster color (matching Python transforms.py)
function clusterColor(clusterId) {
    if (clusterId == null || clusterId < 0) return '#787068';
    const hue = (clusterId * 137.508) % 360;
    const s = 0.7, l = 0.6;
    // HSL to hex
    const c = (1 - Math.abs(2 * l - 1)) * s;
    const x = c * (1 - Math.abs(((hue / 60) % 2) - 1));
    const m = l - c / 2;
    let r, g, b;
    if (hue < 60) { r = c; g = x; b = 0; }
    else if (hue < 120) { r = x; g = c; b = 0; }
    else if (hue < 180) { r = 0; g = c; b = x; }
    else if (hue < 240) { r = 0; g = x; b = c; }
    else if (hue < 300) { r = x; g = 0; b = c; }
    else { r = c; g = 0; b = x; }
    const toHex = v => Math.round((v + m) * 255).toString(16).padStart(2, '0');
    return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

// PageRank via power iteration (matching Python transforms.py)
function computePageRank(edges, damping = 0.85, iterations = 20) {
    const nodeSet = new Set();
    for (const e of edges) {
        nodeSet.add(e.source_engram_id);
        nodeSet.add(e.target_engram_id);
    }
    if (nodeSet.size === 0) return {};

    const nodeList = [...nodeSet].sort();
    const nodeIdx = {};
    nodeList.forEach((id, i) => nodeIdx[id] = i);
    const n = nodeList.length;

    const outEdges = Array.from({length: n}, () => []);
    const outWeight = new Float64Array(n);

    for (const e of edges) {
        const si = nodeIdx[e.source_engram_id];
        const ti = nodeIdx[e.target_engram_id];
        const w = e.confidence || 1.0;
        outEdges[si].push([ti, w]);
        outWeight[si] += w;
        outEdges[ti].push([si, w]);
        outWeight[ti] += w;
    }

    let rank = new Float64Array(n).fill(1.0 / n);
    for (let iter = 0; iter < iterations; iter++) {
        const newRank = new Float64Array(n).fill((1.0 - damping) / n);
        for (let src = 0; src < n; src++) {
            if (outWeight[src] === 0) {
                const share = damping * rank[src] / n;
                for (let j = 0; j < n; j++) newRank[j] += share;
            } else {
                for (const [tgt, w] of outEdges[src]) {
                    newRank[tgt] += damping * rank[src] * w / outWeight[src];
                }
            }
        }
        rank = newRank;
    }

    const maxRank = Math.max(...rank) || 1;
    const result = {};
    nodeList.forEach((id, i) => result[id] = rank[i] / maxRank);
    return result;
}

function buildGraphData(projections, edges) {
    const pageRanks = computePageRank(edges);
    const nodeIds = new Set(projections.map(p => p.engram_id));

    const nodes = projections.map(p => ({
        id: p.engram_id,
        name: p.canonical_name,
        fx: p.x, fy: p.y, fz: p.z,
        color: clusterColor(p.cluster_id),
        cluster_id: p.cluster_id,
        rank: pageRanks[p.engram_id] || 0,
        show_label: (pageRanks[p.engram_id] || 0) >= LABEL_RANK_THRESHOLD,
    }));

    const links = edges
        .filter(e => nodeIds.has(e.source_engram_id) && nodeIds.has(e.target_engram_id))
        .map(e => ({
            source: e.source_engram_id,
            target: e.target_engram_id,
            confidence: e.confidence || 0.5,
        }));

    return { nodes, links };
}

export async function initGraph(containerSelector, projections, edges) {
    const el = document.querySelector(containerSelector);
    if (!el) return;
    el.style.position = 'relative';

    const data = buildGraphData(projections, edges);

    const THREE = await import('three');
    const { default: ThreeForceGraph } = await import('https://esm.sh/three-forcegraph@1?external=three&deps=three@0.175');
    const { default: SpriteText } = await import('https://esm.sh/three-spritetext@1?external=three&deps=three@0.175');
    const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');

    const W = el.clientWidth;
    const H = el.clientHeight;

    // Scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(BG_COLOR);

    // Camera
    const camera = new THREE.PerspectiveCamera(50, W / H, 0.1, 1000);
    camera.position.set(0, 0, 12);

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(W, H);
    renderer.setPixelRatio(window.devicePixelRatio);
    el.appendChild(renderer.domElement);

    // Orbit controls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.1;
    controls.minDistance = 0.5;

    // Lights
    scene.add(new THREE.AmbientLight(0xffffff, 1.5));

    // Circle texture for flat dot sprites
    const canvas = document.createElement('canvas');
    canvas.width = 64; canvas.height = 64;
    const ctx = canvas.getContext('2d');
    ctx.beginPath();
    ctx.arc(32, 32, 30, 0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    const circleTexture = new THREE.CanvasTexture(canvas);

    // Force graph
    const graph = new ThreeForceGraph()
        .graphData(data)
        .nodeThreeObject(node => {
            const group = new THREE.Group();
            group.__graphData = node;
            const size = 0.03 + (node.rank || 0) * 0.06;
            const spriteMat = new THREE.SpriteMaterial({
                color: new THREE.Color(node.color || '#787068'),
                transparent: true, opacity: 0.92,
                map: circleTexture
            });
            const dot = new THREE.Sprite(spriteMat);
            dot.scale.set(size, size, 1);
            group.add(dot);

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
        .linkVisibility(false);

    // Disable forces — use UMAP fixed positions
    graph.d3Force('charge', null);
    graph.d3Force('link', null);
    graph.d3Force('center', null);
    graph.tickFrame();
    graph.tickFrame();
    scene.add(graph);

    // Render edges manually
    const nodeById = {};
    data.nodes.forEach(n => nodeById[n.id] = n);

    const edgeLines = [];
    const edgeGroup = new THREE.Group();
    edgeGroup.name = 'edges';
    data.links.forEach(link => {
        const sid = (typeof link.source === 'object') ? link.source.id : link.source;
        const tid = (typeof link.target === 'object') ? link.target.id : link.target;
        if (!nodeById[sid] || !nodeById[tid]) return;
        const c = 0.08 + (link.confidence || 0.3) * 0.15;
        const geo = new THREE.BufferGeometry();
        const positions = new Float32Array(6);
        geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        const mat = new THREE.LineBasicMaterial({
            color: new THREE.Color(c, c, c), transparent: true, opacity: 0.35
        });
        const line = new THREE.Line(geo, mat);
        line.frustumCulled = false;
        edgeLines.push({ line, sid, tid });
        edgeGroup.add(line);
    });
    scene.add(edgeGroup);

    function updateEdges() {
        // Read positions from data (updated by tickFrame and applySpread)
        edgeLines.forEach(e => {
            const n1 = nodeById[e.sid], n2 = nodeById[e.tid];
            if (!n1 || !n2) return;
            const pos = e.line.geometry.attributes.position.array;
            pos[0] = n1.x; pos[1] = n1.y; pos[2] = n1.z;
            pos[3] = n2.x; pos[4] = n2.y; pos[5] = n2.z;
            e.line.geometry.attributes.position.needsUpdate = true;
        });
    }
    // Initial edge positions set after first ticks


    // Detail panel
    let panel = document.getElementById('hypo-detail-panel');
    if (!panel) {
        panel = document.createElement('div');
        panel.id = 'hypo-detail-panel';
        Object.assign(panel.style, {
            position: 'fixed', top: '16px', right: '16px',
            width: '260px', maxHeight: 'calc(100vh - 32px)',
            background: 'rgba(13,13,13,0.88)', border: '1px solid #1e1e1e',
            backdropFilter: 'blur(12px)', borderRadius: '6px',
            fontFamily: "'DM Sans', sans-serif", color: '#d4d4d4',
            transition: 'opacity 0.2s ease, transform 0.2s ease',
            overflow: 'hidden auto', zIndex: '9999', boxSizing: 'border-box',
            opacity: '0', transform: 'translateX(10px)', pointerEvents: 'none'
        });
        document.body.appendChild(panel);
    }

    // HUD
    const hud = document.createElement('div');
    Object.assign(hud.style, {
        position: 'absolute', bottom: '16px', left: '16px',
        background: 'rgba(13,13,13,0.7)', border: '1px solid #1e1e1e',
        backdropFilter: 'blur(8px)', borderRadius: '4px',
        fontFamily: "'DM Sans', sans-serif", color: '#4a4a4a',
        fontSize: '9px', padding: '8px 12px', zIndex: '9998',
        letterSpacing: '0.05em', lineHeight: '1.6'
    });
    const isTouchDevice = 'ontouchstart' in window;
    if (isTouchDevice) {
        hud.innerHTML = '<span style="color:#6b6b6b">orbit</span> drag'
            + ' &nbsp; <span style="color:#6b6b6b">zoom</span> pinch'
            + ' &nbsp; <span style="color:#6b6b6b">pan</span> 2-finger drag'
            + ' &nbsp; <span style="color:#6b6b6b">spread</span> double-tap drag ↕'
            + '<br><span style="color:#6b6b6b">inspect</span> tap'
            + ' &nbsp; <span style="color:#6b6b6b">'
            + data.nodes.length + '</span> nodes'
            + ' &nbsp; <span style="color:#6b6b6b">'
            + data.links.length + '</span> edges';
    } else {
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
    }
    el.appendChild(hud);

    // Cluster label lookup — populated after cluster fetch
    const clusterLabelMap = {};

    function showPanel(node) {
        const nodeEdges = data.links.filter(l => {
            const s = (typeof l.source === 'object') ? l.source.id : l.source;
            const t = (typeof l.target === 'object') ? l.target.id : l.target;
            return s === node.id || t === node.id;
        });
        let html = '<div style="padding:16px">';
        html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">';
        html += '<div style="font-size:13px;font-weight:500">' + (node.name || node.id) + '</div>';
        html += '<div id="hypo-panel-close" style="cursor:pointer;color:#4a4a4a;font-size:18px">&times;</div></div>';
        html += '<div style="font-size:10px;color:#6b6b6b;margin-bottom:12px">';
        var clusterDisplay = clusterLabelMap[node.cluster_id] || ('cluster ' + (node.cluster_id != null ? node.cluster_id : '-'));
        html += clusterDisplay;
        html += ' &middot; rank ' + Math.round((node.rank || 0) * 100) + '%</div>';
        html += '<a href="/engrams/' + node.id + '" style="display:inline-block;color:#3ecfcf;';
        html += 'font-size:11px;text-decoration:none;margin-bottom:16px;padding:4px 8px;';
        html += 'border:1px solid #1e1e1e;border-radius:3px">View engram</a>';
        html += '<div style="font-size:10px;color:#4a4a4a;text-transform:uppercase;';
        html += 'letter-spacing:0.1em;margin-bottom:8px">Connections (' + nodeEdges.length + ')</div>';
        nodeEdges.slice(0, 20).forEach(l => {
            const s = (typeof l.source === 'object') ? l.source : data.nodes.find(n => n.id === l.source);
            const t = (typeof l.target === 'object') ? l.target : data.nodes.find(n => n.id === l.target);
            const other = (s && s.id === node.id) ? t : s;
            if (!other) return;
            html += '<div style="padding:4px 0;border-bottom:1px solid #1a1a1a;font-size:11px">';
            html += '<a href="/engrams/' + other.id + '" style="color:#3ecfcf;text-decoration:none">';
            html += (other.name || other.id) + '</a>';
            html += '<span style="color:#4a4a4a;margin-left:6px">' + Math.round((l.confidence || 0) * 100) + '%</span></div>';
        });
        if (nodeEdges.length > 20) html += '<div style="color:#4a4a4a;font-size:10px;padding-top:4px">+' + (nodeEdges.length - 20) + ' more</div>';
        html += '</div>';
        panel.innerHTML = html;
        panel.style.opacity = '1';
        panel.style.transform = 'translateX(0)';
        panel.style.pointerEvents = 'auto';
        const cb = document.getElementById('hypo-panel-close');
        if (cb) cb.onclick = () => {
            panel.style.opacity = '0';
            panel.style.transform = 'translateX(10px)';
            panel.style.pointerEvents = 'none';
        };
    }

    // Raycaster for click + drag
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    const mouseDown = new THREE.Vector2();

    let dragNode = null;
    let dragActive = false;
    const dragPlane = new THREE.Plane();
    const dragOffset = new THREE.Vector3();
    const intersection = new THREE.Vector3();
    let pendingHit = null;

    renderer.domElement.addEventListener('pointerdown', e => {
        mouseDown.set(e.clientX, e.clientY);
        if (e.button !== 0) return;
        const rect = renderer.domElement.getBoundingClientRect();
        mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(mouse, camera);
        const hits = raycaster.intersectObjects(scene.children, true);
        for (const hit of hits) {
            let obj = hit.object;
            while (obj && !obj.__data && !obj.__graphData) obj = obj.parent;
            if (obj && (obj.__graphData || obj.__data)) {
                pendingHit = obj;
                dragActive = false;
                return;
            }
        }
        pendingHit = null;
    });

    renderer.domElement.addEventListener('pointermove', e => {
        if (!pendingHit) return;
        const dist = Math.abs(e.clientX - mouseDown.x) + Math.abs(e.clientY - mouseDown.y);
        if (!dragActive && dist > 4) {
            dragActive = true;
            dragNode = pendingHit;
            controls.enabled = false;
            dragPlane.setFromNormalAndCoplanarPoint(
                camera.getWorldDirection(new THREE.Vector3()).negate(),
                dragNode.position
            );
            const rect = renderer.domElement.getBoundingClientRect();
            mouse.x = ((mouseDown.x - rect.left) / rect.width) * 2 - 1;
            mouse.y = -((mouseDown.y - rect.top) / rect.height) * 2 + 1;
            raycaster.setFromCamera(mouse, camera);
            raycaster.ray.intersectPlane(dragPlane, intersection);
            dragOffset.copy(dragNode.position).sub(intersection);
            renderer.domElement.style.cursor = 'grabbing';
        }
        if (dragActive && dragNode) {
            const rect = renderer.domElement.getBoundingClientRect();
            mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
            mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
            raycaster.setFromCamera(mouse, camera);
            if (e.altKey) {
                const dy = e.clientY - mouseDown.y;
                const camDir = camera.getWorldDirection(new THREE.Vector3());
                dragNode.position.addScaledVector(camDir, dy * 0.005);
                mouseDown.set(e.clientX, e.clientY);
            } else {
                raycaster.ray.intersectPlane(dragPlane, intersection);
                dragNode.position.copy(intersection.add(dragOffset));
            }
            const dd = dragNode.__graphData || dragNode.__data;
            if (dd) {
                dd.fx = dragNode.position.x;
                dd.fy = dragNode.position.y;
                dd.fz = dragNode.position.z;
                updateEdges();
            }
        }
    });

    renderer.domElement.addEventListener('pointerup', e => {
        const wasDrag = dragActive;
        if (dragNode) {
            controls.enabled = true;
            dragNode = null;
            dragActive = false;
            renderer.domElement.style.cursor = 'grab';
        }
        pendingHit = null;
        if (!wasDrag && Math.abs(e.clientX - mouseDown.x) + Math.abs(e.clientY - mouseDown.y) < 4) {
            const rect = renderer.domElement.getBoundingClientRect();
            mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
            mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
            raycaster.setFromCamera(mouse, camera);
            const hits = raycaster.intersectObjects(scene.children, true);
            let foundNode = false;
            for (const hit of hits) {
                let obj = hit.object;
                // Check for cluster label
                if (obj.__clusterData) {
                    const cl = obj.__clusterData;
                    panel.innerHTML = `<div style="padding:16px">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
                            <div style="font-size:13px;font-weight:500">${cl.label || 'Cluster ' + cl.cluster_id}</div>
                            <div id="hypo-panel-close" style="cursor:pointer;color:#4a4a4a;font-size:18px">&times;</div>
                        </div>
                        <div style="font-size:10px;color:#6b6b6b;margin-bottom:12px">${cl.engram_count || '?'} engrams</div>
                        ${cl.summary ? `<div style="font-size:12px;color:#d4d4d4;line-height:1.6">${cl.summary}</div>` : ''}
                    </div>`;
                    panel.style.opacity = '1';
                    panel.style.transform = 'translateX(0)';
                    panel.style.pointerEvents = 'auto';
                    const cb = document.getElementById('hypo-panel-close');
                    if (cb) cb.onclick = () => { panel.style.opacity = '0'; panel.style.transform = 'translateX(10px)'; panel.style.pointerEvents = 'none'; };
                    foundNode = true;
                    break;
                }
                while (obj && !obj.__data && !obj.__graphData) obj = obj.parent;
                const nd = obj && (obj.__graphData || obj.__data);
                if (nd) { showPanel(nd); foundNode = true; break; }
            }
            if (!foundNode && panel) {
                panel.style.opacity = '0';
                panel.style.transform = 'translateX(10px)';
                panel.style.pointerEvents = 'none';
            }
        }
    });

    // Hover label
    let hoverSprite = null;
    renderer.domElement.addEventListener('pointermove', e => {
        const rect = renderer.domElement.getBoundingClientRect();
        mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(mouse, camera);
        const hits = raycaster.intersectObjects(scene.children, true);
        if (hoverSprite) { scene.remove(hoverSprite); hoverSprite = null; }
        for (const hit of hits) {
            let obj = hit.object;
            while (obj && !obj.__data && !obj.__graphData) obj = obj.parent;
            const nd = obj && (obj.__graphData || obj.__data);
            if (nd && !nd.show_label) {
                hoverSprite = new SpriteText(nd.name);
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
    window.addEventListener('resize', () => {
        const w = el.clientWidth, h = el.clientHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
    });

    // Alt+scroll spread: scale node positions from per-cluster centroids
    let spreadFactor = 1.0;
    const clusterCentroids = {};
    const clusterCounts = {};
    data.nodes.forEach(n => {
        const cid = n.cluster_id != null ? n.cluster_id : '__noise__';
        if (!clusterCentroids[cid]) {
            clusterCentroids[cid] = { x: 0, y: 0, z: 0 };
            clusterCounts[cid] = 0;
        }
        clusterCentroids[cid].x += n.fx;
        clusterCentroids[cid].y += n.fy;
        clusterCentroids[cid].z += n.fz;
        clusterCounts[cid]++;
    });
    Object.keys(clusterCentroids).forEach(cid => {
        clusterCentroids[cid].x /= clusterCounts[cid];
        clusterCentroids[cid].y /= clusterCounts[cid];
        clusterCentroids[cid].z /= clusterCounts[cid];
    });
    data.nodes.forEach(n => {
        const cid = n.cluster_id != null ? n.cluster_id : '__noise__';
        const cc = clusterCentroids[cid];
        n._dx = n.fx - cc.x; n._dy = n.fy - cc.y; n._dz = n.fz - cc.z;
        n._clusterCentroid = cc;
    });

    function applySpread() {
        data.nodes.forEach(n => {
            const cc = n._clusterCentroid;
            n.fx = cc.x + n._dx * spreadFactor;
            n.fy = cc.y + n._dy * spreadFactor;
            n.fz = cc.z + n._dz * spreadFactor;
            n.x = n.fx; n.y = n.fy; n.z = n.fz;
        });
        // Move Three.js objects directly — no graph rebuild
        graph.children.forEach(obj => {
            const nd = obj.__graphData || obj.__data;
            if (nd && nd.fx != null) {
                obj.position.set(nd.fx, nd.fy, nd.fz);
            }
        });
        updateEdges();
    }

    // Desktop: alt+scroll for spread
    renderer.domElement.addEventListener('wheel', e => {
        if (!e.altKey) return;
        e.preventDefault();
        e.stopPropagation();
        spreadFactor += e.deltaY > 0 ? -0.08 : 0.08;
        spreadFactor = Math.max(0.3, Math.min(5.0, spreadFactor));
        applySpread();
    }, { passive: false, capture: true });

    renderer.domElement.addEventListener('wheel', e => {
        controls.enableZoom = !e.altKey;
    }, { capture: true });

    // Mobile: double-tap + drag for spread (Google Maps style)
    // One finger orbit, two-finger pan, pinch zoom — all default OrbitControls.
    // Double-tap-hold-drag up = spread out, drag down = contract.
    if ('ontouchstart' in window) {
        let lastTapTime = 0;
        let spreadDragging = false;
        let spreadStartY = 0;

        renderer.domElement.addEventListener('touchstart', e => {
            if (e.touches.length !== 1) return;
            const now = Date.now();
            const dt = now - lastTapTime;
            if (dt < 300 && dt > 50) {
                // Second tap — enter spread mode
                spreadDragging = true;
                spreadStartY = e.touches[0].clientY;
                controls.enabled = false;
                e.preventDefault();
            }
            lastTapTime = now;
        }, { passive: false });

        renderer.domElement.addEventListener('touchmove', e => {
            if (!spreadDragging || e.touches.length !== 1) return;
            e.preventDefault();
            const y = e.touches[0].clientY;
            const delta = (spreadStartY - y) * 0.004;
            spreadStartY = y;
            spreadFactor += delta;
            spreadFactor = Math.max(0.3, Math.min(5.0, spreadFactor));
            applySpread();
        }, { passive: false });

        renderer.domElement.addEventListener('touchend', () => {
            if (spreadDragging) {
                spreadDragging = false;
                controls.enabled = true;
            }
        }, { passive: true });
    }

    // Fit camera to data bounds
    const xs = data.nodes.map(n => n.fx);
    const ys = data.nodes.map(n => n.fy);
    const zs = data.nodes.map(n => n.fz);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const cz = (Math.min(...zs) + Math.max(...zs)) / 2;
    const maxR = Math.max(...data.nodes.map(n =>
        Math.sqrt((n.fx - cx) ** 2 + (n.fy - cy) ** 2 + (n.fz - cz) ** 2)
    ));
    controls.target.set(cx, cy, cz);
    camera.position.set(cx, cy, cz + Math.max(maxR * 2.5, 3));

    // Cluster labels — fetch overviews, populate label map, render sprites + legend
    try {
        const clustersResp = await fetch('/api/viz/clusters');
        if (clustersResp.ok) {
            const clusters = await clustersResp.json();
            // Populate label map for node detail panel
            for (const cluster of (clusters || [])) {
                if (cluster.label && cluster.cluster_id != null) {
                    clusterLabelMap[cluster.cluster_id] = cluster.label;
                }
            }
            // Render 3D sprites at centroids
            for (const cluster of (clusters || [])) {
                if (!cluster.label) continue;
                const labelSprite = new SpriteText(cluster.label.toUpperCase());
                labelSprite.color = 'rgba(160,160,160,0.5)';
                labelSprite.textHeight = 0.06;
                labelSprite.fontFamily = "'DM Sans', sans-serif";
                labelSprite.fontWeight = '600';
                labelSprite.backgroundColor = false;
                labelSprite.padding = 0;
                labelSprite.position.set(
                    cluster.centroid_x || 0,
                    (cluster.centroid_y || 0) + 0.3,
                    cluster.centroid_z || 0,
                );
                labelSprite.__clusterData = cluster;
                scene.add(labelSprite);
            }
            // Clusters legend — collapsible panel, top left
            if (clusters && clusters.length > 0) {
                // Count nodes per cluster
                const clusterNodeCounts = {};
                data.nodes.forEach(n => {
                    const key = n.cluster_id != null ? n.cluster_id : '__noise__';
                    clusterNodeCounts[key] = (clusterNodeCounts[key] || 0) + 1;
                });
                const legend = document.createElement('div');
                Object.assign(legend.style, {
                    position: 'absolute', top: '16px', left: '16px',
                    background: 'rgba(13,13,13,0.8)', border: '1px solid #1e1e1e',
                    backdropFilter: 'blur(8px)', borderRadius: '4px',
                    fontFamily: "'JetBrains Mono', monospace", color: '#6b6b6b',
                    fontSize: '10px', zIndex: '9997',
                    maxHeight: 'calc(100vh - 80px)', overflowY: 'auto',
                    minWidth: '180px', maxWidth: '240px',
                });
                const header = document.createElement('div');
                Object.assign(header.style, {
                    padding: '8px 12px', cursor: 'pointer', userSelect: 'none',
                    textTransform: 'uppercase', letterSpacing: '0.1em',
                    fontSize: '10px', color: '#6b6b6b',
                });
                header.textContent = 'Clusters';
                const body = document.createElement('div');
                body.style.display = 'none';
                body.style.padding = '0 12px 8px';
                header.addEventListener('click', () => {
                    body.style.display = body.style.display === 'none' ? 'block' : 'none';
                    header.textContent = body.style.display === 'none' ? 'Clusters' : 'Clusters \u25B4';
                });
                // Build sorted cluster entries
                const sortedIds = Object.keys(clusterNodeCounts)
                    .sort((a, b) => a === '__noise__' ? 1 : b === '__noise__' ? -1 : Number(a) - Number(b));
                for (const key of sortedIds) {
                    const cid = key === '__noise__' ? null : Number(key);
                    const label = clusterLabelMap[cid] || (cid != null ? 'cluster ' + cid : 'noise');
                    const color = clusterColor(cid);
                    const count = clusterNodeCounts[key];
                    const row = document.createElement('div');
                    Object.assign(row.style, {
                        display: 'flex', alignItems: 'center', gap: '8px',
                        padding: '3px 0',
                    });
                    row.innerHTML = `<span style="width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0"></span>`
                        + `<span style="color:#a0a0a0;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${label}</span>`
                        + `<span style="color:#4a4a4a;flex-shrink:0">${count}</span>`;
                    body.appendChild(row);
                }
                legend.id = 'hypo-cluster-legend';
                legend.appendChild(header);
                legend.appendChild(body);
                el.appendChild(legend);
            }
        }
    } catch (e) {
        // Cluster labels are optional
    }

    // Animate — updateEdges after tickFrame so nodes and edges are in sync
    function animate() {
        requestAnimationFrame(animate);
        graph.tickFrame();
        updateEdges();
        controls.update();
        renderer.render(scene, camera);
    }
    animate();

    // Cleanup on navigation
    return { destroy: () => {
        hud.remove();
        panel.remove();
        document.getElementById('hypo-mobile-controls')?.remove();
        document.getElementById('hypo-cluster-legend')?.remove();
    }};
}
