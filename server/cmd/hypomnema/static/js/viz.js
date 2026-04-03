// Hypomnema 3D Knowledge Graph Visualization
// Uses Three.js + 3d-force-graph via ESM CDN
// This is the client-side renderer — data comes from /api/viz/* endpoints.

import ForceGraph3D from 'https://esm.sh/3d-force-graph@1';
import SpriteText from 'https://esm.sh/three-spritetext';

// Golden-angle HSL palette for cluster coloring
function clusterColor(clusterId) {
    if (clusterId == null || clusterId < 0) return '#787068'; // noise = warm gray
    const hue = (clusterId * 137.508) % 360;
    return `hsl(${hue}, 55%, 60%)`;
}

export function initGraph(containerSelector, projections, edges) {
    const container = document.querySelector(containerSelector);
    if (!container) return;

    // Build graph data
    const nodeMap = new Map();
    const nodes = projections.map(p => {
        const node = {
            id: p.engram_id,
            name: p.canonical_name,
            fx: p.x, fy: p.y, fz: p.z,
            color: clusterColor(p.cluster_id),
            cluster_id: p.cluster_id,
        };
        nodeMap.set(p.engram_id, node);
        return node;
    });

    const links = edges
        .filter(e => nodeMap.has(e.source_engram_id) && nodeMap.has(e.target_engram_id))
        .map(e => ({
            source: e.source_engram_id,
            target: e.target_engram_id,
            confidence: e.confidence,
        }));

    // Create graph
    const graph = ForceGraph3D()(container)
        .graphData({ nodes, links })
        .nodeVal(2)
        .nodeColor(n => n.color)
        .nodeOpacity(0.9)
        .nodeLabel(n => n.name)
        .linkWidth(0.3)
        .linkOpacity(0.15)
        .linkColor(() => '#555')
        .backgroundColor('#0d0f14')
        .width(container.clientWidth)
        .height(container.clientHeight);

    // Disable force simulation (UMAP positions are fixed)
    graph.d3Force('charge', null);
    graph.d3Force('link', null);
    graph.d3Force('center', null);

    // Click handler — show node info
    graph.onNodeClick(node => {
        const info = document.createElement('div');
        info.innerHTML = `<strong>${node.name}</strong><br><a href="/engrams/${node.id}">View engram →</a>`;
        info.style.cssText = 'position:fixed;top:1rem;right:1rem;background:var(--bg-raised);border:1px solid var(--border);border-radius:8px;padding:1rem;font-size:0.82rem;color:var(--fg);z-index:999;max-width:300px';
        info.onclick = () => info.remove();

        // Remove existing info panel
        document.querySelectorAll('[data-graph-info]').forEach(el => el.remove());
        info.dataset.graphInfo = '1';
        document.body.appendChild(info);
    });

    // Handle resize
    const observer = new ResizeObserver(() => {
        graph.width(container.clientWidth).height(container.clientHeight);
    });
    observer.observe(container);

    return graph;
}
