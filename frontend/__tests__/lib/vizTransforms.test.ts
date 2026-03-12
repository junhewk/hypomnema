import { describe, it, expect } from "vitest";
import {
  clusterColor,
  buildPositionBuffer,
  buildColorBuffer,
  buildEdgeBuffer,
  buildPointIndex,
  pointAtIndex,
} from "@/lib/vizTransforms";
import { makeProjectionPoint } from "../helpers/makeViz";

describe("clusterColor", () => {
  it("returns distinct RGB for different IDs", () => {
    const c0 = clusterColor(0);
    const c1 = clusterColor(1);
    const c5 = clusterColor(5);
    expect(c0).not.toEqual(c1);
    expect(c1).not.toEqual(c5);
    // Each channel in [0, 1]
    for (const [r, g, b] of [c0, c1, c5]) {
      expect(r).toBeGreaterThanOrEqual(0);
      expect(r).toBeLessThanOrEqual(1);
      expect(g).toBeGreaterThanOrEqual(0);
      expect(g).toBeLessThanOrEqual(1);
      expect(b).toBeGreaterThanOrEqual(0);
      expect(b).toBeLessThanOrEqual(1);
    }
  });

  it("returns gray for null/noise", () => {
    const gray = [0.47, 0.44, 0.42];
    expect(clusterColor(null)).toEqual(gray);
    expect(clusterColor(-1)).toEqual(gray);
  });
});

describe("buildPositionBuffer", () => {
  it("creates correct Float32Array", () => {
    const points = [
      makeProjectionPoint({ x: 1, y: 2, z: 3 }),
      makeProjectionPoint({ engram_id: "eng-2", x: 4, y: 5, z: 6 }),
    ];
    const buf = buildPositionBuffer(points);
    expect(buf).toBeInstanceOf(Float32Array);
    expect(buf.length).toBe(6);
    expect(Array.from(buf)).toEqual([1, 2, 3, 4, 5, 6]);
  });
});

describe("buildColorBuffer", () => {
  it("creates array with cluster colors", () => {
    const points = [
      makeProjectionPoint({ cluster_id: 0 }),
      makeProjectionPoint({ engram_id: "eng-2", cluster_id: 1 }),
    ];
    const buf = buildColorBuffer(points);
    expect(buf).toBeInstanceOf(Float32Array);
    expect(buf.length).toBe(6);
    // First 3 values should match clusterColor(0)
    const c0 = clusterColor(0);
    expect(buf[0]).toBeCloseTo(c0[0], 5);
    expect(buf[1]).toBeCloseTo(c0[1], 5);
    expect(buf[2]).toBeCloseTo(c0[2], 5);
  });
});

describe("buildEdgeBuffer", () => {
  it("creates line vertex pairs", () => {
    const p1 = makeProjectionPoint({ engram_id: "eng-1", x: 1, y: 2, z: 3 });
    const p2 = makeProjectionPoint({ engram_id: "eng-2", x: 4, y: 5, z: 6 });
    const index = buildPointIndex([p1, p2]);
    const edges = [
      { source_engram_id: "eng-1", target_engram_id: "eng-2" },
    ];
    const buf = buildEdgeBuffer(edges, index);
    expect(buf.length).toBe(6);
    expect(Array.from(buf)).toEqual([1, 2, 3, 4, 5, 6]);
  });

  it("skips edges with missing endpoints", () => {
    const p1 = makeProjectionPoint({ engram_id: "eng-1" });
    const index = buildPointIndex([p1]);
    const edges = [
      { source_engram_id: "eng-1", target_engram_id: "eng-missing" },
    ];
    const buf = buildEdgeBuffer(edges, index);
    expect(buf.length).toBe(0);
  });
});

describe("buildPointIndex", () => {
  it("creates engram_id → point map", () => {
    const p1 = makeProjectionPoint({ engram_id: "eng-1" });
    const p2 = makeProjectionPoint({ engram_id: "eng-2" });
    const index = buildPointIndex([p1, p2]);
    expect(index.size).toBe(2);
    expect(index.get("eng-1")).toBe(p1);
    expect(index.get("eng-2")).toBe(p2);
  });
});

describe("pointAtIndex", () => {
  it("returns point at valid index", () => {
    const points = [
      makeProjectionPoint({ engram_id: "eng-1" }),
      makeProjectionPoint({ engram_id: "eng-2" }),
    ];
    expect(pointAtIndex(points, 0)?.engram_id).toBe("eng-1");
    expect(pointAtIndex(points, 1)?.engram_id).toBe("eng-2");
  });

  it("returns null for out-of-bounds", () => {
    const points = [makeProjectionPoint()];
    expect(pointAtIndex(points, -1)).toBeNull();
    expect(pointAtIndex(points, 5)).toBeNull();
  });
});
