import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useVizData } from "@/hooks/useVizData";
import { makeProjectionPoint, makeCluster, makeVizEdge } from "../helpers/makeViz";
import { mockJsonResponse, mockErrorResponse } from "../helpers/mockResponse";

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("useVizData", () => {
  it("returns isLoading=true initially", () => {
    vi.spyOn(global, "fetch").mockImplementation(
      () => new Promise(() => {}), // never resolves
    );
    const { result } = renderHook(() => useVizData());
    expect(result.current.isLoading).toBe(true);
    expect(result.current.points).toEqual([]);
    expect(result.current.clusters).toEqual([]);
    expect(result.current.edges).toEqual([]);
  });

  it("fetches projections, clusters, edges in parallel", async () => {
    const points = [makeProjectionPoint()];
    const clusters = [makeCluster()];
    const edges = [makeVizEdge()];

    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/projections")) return mockJsonResponse(points) as Response;
      if (url.includes("/clusters")) return mockJsonResponse(clusters) as Response;
      if (url.includes("/edges")) return mockJsonResponse(edges) as Response;
      return mockJsonResponse([]) as Response;
    });

    const { result } = renderHook(() => useVizData());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.points).toEqual(points);
    expect(result.current.clusters).toEqual(clusters);
    expect(result.current.edges).toEqual(edges);
    expect(result.current.error).toBeNull();
  });

  it("returns data after successful fetch", async () => {
    const points = [makeProjectionPoint({ engram_id: "eng-42" })];

    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/projections")) return mockJsonResponse(points) as Response;
      return mockJsonResponse([]) as Response;
    });

    const { result } = renderHook(() => useVizData());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.points[0].engram_id).toBe("eng-42");
  });

  it("sets error on API failure", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      mockErrorResponse(500, "Internal Server Error") as Response,
    );

    const { result } = renderHook(() => useVizData());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBeTruthy();
  });
});
