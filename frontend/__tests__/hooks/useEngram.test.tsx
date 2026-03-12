import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useEngram } from "@/hooks/useEngram";
import { makeEngramDetail } from "../helpers/makeEngram";
import { makeDoc } from "../helpers/makeDocument";
import { mockJsonResponse, mockErrorResponse } from "../helpers/mockResponse";

const mockFetch = vi.fn();
global.fetch = mockFetch;

describe("useEngram", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("returns isLoading=true initially", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useEngram("eng-1"));
    expect(result.current.isLoading).toBe(true);
  });

  it("fetches engram detail and cluster in parallel", async () => {
    const detail = makeEngramDetail({ id: "eng-1" });
    const cluster = [makeDoc({ id: "doc-1" })];
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(detail))
      .mockResolvedValueOnce(mockJsonResponse(cluster));

    const { result } = renderHook(() => useEngram("eng-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("returns engram with edges and cluster docs", async () => {
    const detail = makeEngramDetail({
      id: "eng-1",
      engram: { canonical_name: "Test Concept" },
    });
    const cluster = [makeDoc({ id: "doc-1" }), makeDoc({ id: "doc-2" })];
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(detail))
      .mockResolvedValueOnce(mockJsonResponse(cluster));

    const { result } = renderHook(() => useEngram("eng-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.engram?.canonical_name).toBe("Test Concept");
    expect(result.current.clusterDocs).toHaveLength(2);
  });

  it("sets error on 404", async () => {
    mockFetch.mockResolvedValue(
      mockErrorResponse(404, "Not Found", "not found"),
    );

    const { result } = renderHook(() => useEngram("bad-id"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.error).toBeTruthy();
    expect(result.current.engram).toBeNull();
  });

  it("refetches when id changes", async () => {
    const detail1 = makeEngramDetail({ id: "eng-1", engram: { canonical_name: "First" } });
    const detail2 = makeEngramDetail({ id: "eng-2", engram: { canonical_name: "Second" } });
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(detail1))
      .mockResolvedValueOnce(mockJsonResponse([]))
      .mockResolvedValueOnce(mockJsonResponse(detail2))
      .mockResolvedValueOnce(mockJsonResponse([]));

    const { result, rerender } = renderHook(
      ({ id }) => useEngram(id),
      { initialProps: { id: "eng-1" } },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.engram?.canonical_name).toBe("First");

    rerender({ id: "eng-2" });
    await waitFor(() => expect(result.current.engram?.canonical_name).toBe("Second"));
  });
});
