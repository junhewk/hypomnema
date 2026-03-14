import type { ProjectionPoint } from "./types";

type RGB = [number, number, number];

const COLOR_NEUTRAL: RGB = [0.82, 0.84, 0.88];
const COLOR_EDGE_DEFAULT: RGB = [0.68, 0.72, 0.80];
const COLOR_VIZ_BG: RGB = [0.031, 0.031, 0.039];

/** Convert HSL (h: 0–360, s: 0–1, l: 0–1) to RGB (each 0–1). */
function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let r = 0,
    g = 0,
    b = 0;
  if (h < 60) {
    r = c;
    g = x;
  } else if (h < 120) {
    r = x;
    g = c;
  } else if (h < 180) {
    g = c;
    b = x;
  } else if (h < 240) {
    g = x;
    b = c;
  } else if (h < 300) {
    r = x;
    b = c;
  } else {
    r = c;
    b = x;
  }
  return [r + m, g + m, b + m];
}

/** Deterministic cluster color — golden angle HSL. */
export function clusterColor(
  clusterId: number | null,
): [number, number, number] {
  if (clusterId == null || clusterId < 0) return [0.47, 0.44, 0.42];
  const hue = (clusterId * 137.508) % 360;
  return hslToRgb(hue, 0.7, 0.6);
}

export interface NetworkMetrics {
  degree: number;
  betweenness: number;
}

/** Compute degree centrality and betweenness centrality for each node. */
export function computeNetworkMetrics(
  points: ProjectionPoint[],
  edges: Array<{ source_engram_id: string; target_engram_id: string }>,
): Map<string, NetworkMetrics> {
  const n = points.length;
  const result = new Map<string, NetworkMetrics>();
  if (n === 0) return result;

  const idToIdx = new Map<string, number>();
  for (let i = 0; i < n; i++) idToIdx.set(points[i].engram_id, i);

  // Build adjacency list (undirected)
  const adj: Array<number[]> = Array.from({ length: n }, () => []);
  const degree = new Float64Array(n);

  for (const e of edges) {
    const si = idToIdx.get(e.source_engram_id);
    const ti = idToIdx.get(e.target_engram_id);
    if (si == null || ti == null) continue;
    adj[si].push(ti);
    adj[ti].push(si);
    degree[si]++;
    degree[ti]++;
  }

  // Betweenness centrality via BFS from each node (Brandes' algorithm)
  const betweenness = new Float64Array(n);

  for (let s = 0; s < n; s++) {
    const stack: number[] = [];
    const pred: Array<number[]> = Array.from({ length: n }, () => []);
    const sigma = new Float64Array(n);
    sigma[s] = 1;
    const dist = new Int32Array(n).fill(-1);
    dist[s] = 0;

    const queue: number[] = [s];
    let head = 0;
    while (head < queue.length) {
      const v = queue[head++];
      stack.push(v);
      for (const w of adj[v]) {
        if (dist[w] < 0) {
          dist[w] = dist[v] + 1;
          queue.push(w);
        }
        if (dist[w] === dist[v] + 1) {
          sigma[w] += sigma[v];
          pred[w].push(v);
        }
      }
    }

    const delta = new Float64Array(n);
    while (stack.length > 0) {
      const w = stack.pop()!;
      for (const v of pred[w]) {
        delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w]);
      }
      if (w !== s) betweenness[w] += delta[w];
    }
  }

  // Normalize betweenness (undirected: divide by 2)
  for (let i = 0; i < n; i++) betweenness[i] /= 2;

  for (let i = 0; i < n; i++) {
    result.set(points[i].engram_id, { degree: degree[i], betweenness: betweenness[i] });
  }
  return result;
}

/** Compute centroid and bounding radius of projection points. */
export function computeDataBounds(points: ProjectionPoint[]): {
  centroid: [number, number, number];
  radius: number;
} {
  if (points.length === 0) return { centroid: [0, 0, 0], radius: 15 };
  let cx = 0, cy = 0, cz = 0;
  for (const p of points) { cx += p.x; cy += p.y; cz += p.z; }
  const n = points.length;
  cx /= n; cy /= n; cz /= n;
  let maxDistSq = 0;
  for (const p of points) {
    const dx = p.x - cx, dy = p.y - cy, dz = p.z - cz;
    maxDistSq = Math.max(maxDistSq, dx * dx + dy * dy + dz * dz);
  }
  return { centroid: [cx, cy, cz], radius: Math.sqrt(maxDistSq) || 15 };
}

/** Build Float32Array of positions from points (x, y, z triples). */
export function buildPositionBuffer(points: ProjectionPoint[]): Float32Array {
  const buf = new Float32Array(points.length * 3);
  for (let i = 0; i < points.length; i++) {
    buf[i * 3] = points[i].x;
    buf[i * 3 + 1] = points[i].y;
    buf[i * 3 + 2] = points[i].z;
  }
  return buf;
}

/**
 * Build Float32Array of colors from points.
 * - activeClusterId = null/undefined → all nodes warm neutral white
 * - activeClusterId = number → that cluster gets full color, others stay white
 * - activeClusterId = "all" → every node gets its cluster color
 */
export function buildColorBuffer(
  points: ProjectionPoint[],
  activeClusterId?: number | null | "all",
): Float32Array {
  const buf = new Float32Array(points.length * 3);
  const neutral = COLOR_NEUTRAL;

  for (let i = 0; i < points.length; i++) {
    let color: [number, number, number];

    if (activeClusterId === "all") {
      color = clusterColor(points[i].cluster_id);
    } else if (activeClusterId != null && points[i].cluster_id === activeClusterId) {
      color = clusterColor(points[i].cluster_id);
    } else {
      color = neutral;
    }

    buf[i * 3] = color[0];
    buf[i * 3 + 1] = color[1];
    buf[i * 3 + 2] = color[2];
  }
  return buf;
}

/** Build engram_id → ProjectionPoint lookup. */
export function buildPointIndex(
  points: ProjectionPoint[],
): Map<string, ProjectionPoint> {
  const map = new Map<string, ProjectionPoint>();
  for (const p of points) {
    map.set(p.engram_id, p);
  }
  return map;
}

function countValidEdges(
  edges: Array<{ source_engram_id: string; target_engram_id: string }>,
  pointIndex: Map<string, ProjectionPoint>,
): number {
  let count = 0;
  for (const e of edges) {
    if (pointIndex.has(e.source_engram_id) && pointIndex.has(e.target_engram_id)) count++;
  }
  return count;
}

/** Build edge line positions buffer — two vertices per edge. */
export function buildEdgeBuffer(
  edges: Array<{ source_engram_id: string; target_engram_id: string }>,
  pointIndex: Map<string, ProjectionPoint>,
): Float32Array {
  const buf = new Float32Array(countValidEdges(edges, pointIndex) * 6);
  let idx = 0;
  for (const e of edges) {
    const src = pointIndex.get(e.source_engram_id);
    const tgt = pointIndex.get(e.target_engram_id);
    if (!src || !tgt) continue;
    buf[idx++] = src.x; buf[idx++] = src.y; buf[idx++] = src.z;
    buf[idx++] = tgt.x; buf[idx++] = tgt.y; buf[idx++] = tgt.z;
  }
  return buf;
}

/** Build edge positions from a pre-computed position buffer (for exploded/offset views). */
export function buildEdgeBufferFromPositions(
  edges: Array<{ source_engram_id: string; target_engram_id: string }>,
  pointIndex: Map<string, ProjectionPoint>,
  points: ProjectionPoint[],
  positions: Float32Array,
): Float32Array {
  const idToIdx = new Map<string, number>();
  for (let i = 0; i < points.length; i++) idToIdx.set(points[i].engram_id, i);

  const buf = new Float32Array(countValidEdges(edges, pointIndex) * 6);
  let idx = 0;
  for (const e of edges) {
    const si = idToIdx.get(e.source_engram_id);
    const ti = idToIdx.get(e.target_engram_id);
    if (si == null || ti == null) continue;
    if (!pointIndex.has(e.source_engram_id) || !pointIndex.has(e.target_engram_id)) continue;
    buf[idx++] = positions[si * 3]; buf[idx++] = positions[si * 3 + 1]; buf[idx++] = positions[si * 3 + 2];
    buf[idx++] = positions[ti * 3]; buf[idx++] = positions[ti * 3 + 1]; buf[idx++] = positions[ti * 3 + 2];
  }
  return buf;
}

/** Find point at raycaster intersection index. */
export function pointAtIndex(
  points: ProjectionPoint[],
  index: number,
): ProjectionPoint | null {
  if (index < 0 || index >= points.length) return null;
  return points[index];
}

/** Build Float32Array of per-node sizes based on degree/betweenness centrality. */
export function buildSizeBuffer(
  points: ProjectionPoint[],
  metrics: Map<string, NetworkMetrics>,
): Float32Array {
  const BASE = 0.4;
  const n = points.length;
  if (n === 0) return new Float32Array(0);

  const degrees = points.map(p => metrics.get(p.engram_id)?.degree ?? 0);
  const betweennesses = points.map(p => metrics.get(p.engram_id)?.betweenness ?? 0);

  const sortedDeg = [...degrees].sort((a, b) => a - b);
  const sortedBet = [...betweennesses].sort((a, b) => a - b);

  const degThreshold = sortedDeg[Math.floor(n * 0.85)] ?? 0;
  const betThreshold = sortedBet[Math.floor(n * 0.90)] ?? 0;

  const buf = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const isCentral = degrees[i] > degThreshold && degThreshold > 0;
    const isBroker = betweennesses[i] > betThreshold && betThreshold > 0;
    const multiplier = isCentral ? 3 : isBroker ? 2 : 1;
    buf[i] = BASE * multiplier;
  }
  return buf;
}

/**
 * Build edge color buffer for vertex-colored line segments.
 * Since LineBasicMaterial can't do per-vertex alpha, we bake opacity
 * into the colors by mixing toward the background (#08080a).
 */
export function buildEdgeColorBuffer(
  edges: Array<{ source_engram_id: string; target_engram_id: string }>,
  pointIndex: Map<string, ProjectionPoint>,
  focusedEngramId?: string | null,
  focusedClusterId?: number | null,
): Float32Array {
  const colors = new Float32Array(countValidEdges(edges, pointIndex) * 6);
  const focusColor = focusedClusterId != null ? clusterColor(focusedClusterId) : COLOR_EDGE_DEFAULT;

  let idx = 0;
  for (const e of edges) {
    if (!pointIndex.has(e.source_engram_id) || !pointIndex.has(e.target_engram_id)) continue;

    const connected = focusedEngramId != null &&
      (e.source_engram_id === focusedEngramId || e.target_engram_id === focusedEngramId);

    const c = connected ? focusColor : COLOR_EDGE_DEFAULT;
    const opacity = connected ? 0.7 : (focusedEngramId != null ? 0.18 : 0.45);

    // Pre-multiply: mix color toward background at given opacity
    const r = COLOR_VIZ_BG[0] + (c[0] - COLOR_VIZ_BG[0]) * opacity;
    const g = COLOR_VIZ_BG[1] + (c[1] - COLOR_VIZ_BG[1]) * opacity;
    const b = COLOR_VIZ_BG[2] + (c[2] - COLOR_VIZ_BG[2]) * opacity;

    colors[idx++] = r; colors[idx++] = g; colors[idx++] = b;
    colors[idx++] = r; colors[idx++] = g; colors[idx++] = b;
  }

  return colors;
}
