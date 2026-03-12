import type { ProjectionPoint, Cluster, VizEdge } from "@/lib/types";

export function makeProjectionPoint(
  overrides: Partial<ProjectionPoint> = {},
): ProjectionPoint {
  return {
    engram_id: "eng-1",
    canonical_name: "Test Concept",
    x: 1,
    y: 2,
    z: 0.5,
    cluster_id: 0,
    ...overrides,
  };
}

export function makeCluster(overrides: Partial<Cluster> = {}): Cluster {
  return {
    cluster_id: 0,
    label: "Test Cluster",
    engram_count: 5,
    centroid_x: 1,
    centroid_y: 2,
    centroid_z: 0.5,
    ...overrides,
  };
}

export function makeVizEdge(overrides: Partial<VizEdge> = {}): VizEdge {
  return {
    source_engram_id: "eng-1",
    target_engram_id: "eng-2",
    predicate: "supports",
    confidence: 0.8,
    ...overrides,
  };
}
