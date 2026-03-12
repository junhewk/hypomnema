import type { ProjectionPoint } from "./types";

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

/** Build Float32Array of colors from points (r, g, b triples based on cluster_id). */
export function buildColorBuffer(points: ProjectionPoint[]): Float32Array {
  const buf = new Float32Array(points.length * 3);
  for (let i = 0; i < points.length; i++) {
    const [r, g, b] = clusterColor(points[i].cluster_id);
    buf[i * 3] = r;
    buf[i * 3 + 1] = g;
    buf[i * 3 + 2] = b;
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

/** Build edge line positions buffer — two vertices per edge. */
export function buildEdgeBuffer(
  edges: Array<{ source_engram_id: string; target_engram_id: string }>,
  pointIndex: Map<string, ProjectionPoint>,
): Float32Array {
  let validCount = 0;
  for (const e of edges) {
    if (pointIndex.has(e.source_engram_id) && pointIndex.has(e.target_engram_id)) {
      validCount++;
    }
  }
  const buf = new Float32Array(validCount * 6);
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
