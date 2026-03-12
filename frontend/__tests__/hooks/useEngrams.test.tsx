import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useEngrams } from "@/hooks/useEngrams";
import { makeEngramDetail } from "../helpers/makeEngram";

const mockFetch = vi.fn();
global.fetch = mockFetch;

function mockEngramResponse(engram: object) {
  return {
    ok: true,
    status: 200,
    json: async () => engram,
  };
}

describe("useEngrams", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("returns empty map for empty ID array", async () => {
    const { result } = renderHook(() => useEngrams([]));
    expect(result.current.engrams.size).toBe(0);
    expect(result.current.isLoading).toBe(false);
  });

  it("returns isLoading=true initially", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useEngrams(["eng-1"]));
    expect(result.current.isLoading).toBe(true);
  });

  it("fetches all engram details in parallel", async () => {
    const e1 = makeEngramDetail({ id: "eng-1", engram: { id: "eng-1", canonical_name: "Concept A" } });
    const e2 = makeEngramDetail({ id: "eng-2", engram: { id: "eng-2", canonical_name: "Concept B" } });
    mockFetch
      .mockResolvedValueOnce(mockEngramResponse(e1))
      .mockResolvedValueOnce(mockEngramResponse(e2));

    const { result } = renderHook(() => useEngrams(["eng-1", "eng-2"]));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("returns map keyed by engram ID", async () => {
    const e1 = makeEngramDetail({ id: "eng-1", engram: { id: "eng-1", canonical_name: "Concept A" } });
    const e2 = makeEngramDetail({ id: "eng-2", engram: { id: "eng-2", canonical_name: "Concept B" } });
    mockFetch
      .mockResolvedValueOnce(mockEngramResponse(e1))
      .mockResolvedValueOnce(mockEngramResponse(e2));

    const { result } = renderHook(() => useEngrams(["eng-1", "eng-2"]));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.engrams.get("eng-1")?.canonical_name).toBe("Concept A");
    expect(result.current.engrams.get("eng-2")?.canonical_name).toBe("Concept B");
  });

  it("handles partial failure", async () => {
    const e1 = makeEngramDetail({ id: "eng-1", engram: { id: "eng-1" } });
    mockFetch
      .mockResolvedValueOnce(mockEngramResponse(e1))
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
        statusText: "Not Found",
        text: async () => "not found",
      });

    const { result } = renderHook(() => useEngrams(["eng-1", "eng-bad"]));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.engrams.size).toBe(1);
    expect(result.current.engrams.has("eng-1")).toBe(true);
    expect(result.current.error).toBeTruthy();
  });

  it("refetches when IDs change", async () => {
    const e1 = makeEngramDetail({ id: "eng-1", engram: { id: "eng-1" } });
    const e2 = makeEngramDetail({ id: "eng-2", engram: { id: "eng-2" } });
    mockFetch.mockResolvedValueOnce(mockEngramResponse(e1));

    const { result, rerender } = renderHook(
      ({ ids }) => useEngrams(ids),
      { initialProps: { ids: ["eng-1"] } },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.engrams.size).toBe(1);

    mockFetch.mockResolvedValueOnce(mockEngramResponse(e2));
    rerender({ ids: ["eng-2"] });
    await waitFor(() => expect(result.current.engrams.has("eng-2")).toBe(true));
  });
});
