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

/** PageRank via power iteration. Returns normalized [0,1] scores per engram_id. */
export function computePageRank(
  points: ProjectionPoint[],
  edges: Array<{ source_engram_id: string; target_engram_id: string; confidence?: number }>,
  opts: { damping?: number; iterations?: number } = {},
): Map<string, number> {
  const damping = opts.damping ?? 0.85;
  const iterations = opts.iterations ?? 20;
  const n = points.length;
  if (n === 0) return new Map();

  const idToIdx = new Map<string, number>();
  for (let i = 0; i < n; i++) idToIdx.set(points[i].engram_id, i);

  // Build adjacency: outLinks[i] = list of { target, weight }
  const outLinks: Array<Array<{ target: number; weight: number }>> = Array.from({ length: n }, () => []);
  const inLinks: Array<Array<{ source: number; weight: number }>> = Array.from({ length: n }, () => []);

  for (const e of edges) {
    const si = idToIdx.get(e.source_engram_id);
    const ti = idToIdx.get(e.target_engram_id);
    if (si == null || ti == null) continue;
    const w = e.confidence ?? 1;
    outLinks[si].push({ target: ti, weight: w });
    inLinks[ti].push({ source: si, weight: w });
  }

  // Compute total out-weight per node
  const outWeight = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    for (const link of outLinks[i]) outWeight[i] += link.weight;
  }

  let rank = new Float64Array(n).fill(1 / n);
  let next = new Float64Array(n);
  const base = (1 - damping) / n;

  for (let iter = 0; iter < iterations; iter++) {
    next.fill(base);
    for (let i = 0; i < n; i++) {
      for (const link of inLinks[i]) {
        if (outWeight[link.source] > 0) {
          next[i] += damping * rank[link.source] * (link.weight / outWeight[link.source]);
        }
      }
    }
    [rank, next] = [next, rank];
  }

  // Normalize to [0,1]
  let maxRank = 0;
  for (let i = 0; i < n; i++) if (rank[i] > maxRank) maxRank = rank[i];
  const result = new Map<string, number>();
  for (let i = 0; i < n; i++) {
    result.set(points[i].engram_id, maxRank > 0 ? rank[i] / maxRank : 0);
  }
  return result;
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

/** Find point at raycaster intersection index. */
export function pointAtIndex(
  points: ProjectionPoint[],
  index: number,
): ProjectionPoint | null {
  if (index < 0 || index >= points.length) return null;
  return points[index];
}

/** Build Float32Array of per-node sizes based on PageRank. */
export function buildSizeBuffer(
  points: ProjectionPoint[],
  ranks: Map<string, number>,
): Float32Array {
  // Find 85th percentile threshold
  const rankValues = points.map(p => ranks.get(p.engram_id) ?? 0);
  const sorted = [...rankValues].sort((a, b) => a - b);
  const p85 = sorted[Math.floor(sorted.length * 0.85)] ?? 0;

  const buf = new Float32Array(points.length);
  for (let i = 0; i < points.length; i++) {
    const r = rankValues[i];
    if (r > p85 && p85 < 1) {
      // Linear scale from 4px to 18px for nodes above 85th percentile
      const t = (r - p85) / (1 - p85);
      buf[i] = 4 + t * 14;
    } else {
      buf[i] = 4;
    }
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
