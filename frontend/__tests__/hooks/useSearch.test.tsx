import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useSearch } from "@/hooks/useSearch";
import { makeScoredDoc } from "../helpers/makeDocument";
import { makeEdge } from "../helpers/makeEngram";
import { mockJsonResponse, mockErrorResponse } from "../helpers/mockResponse";

const mockFetch = vi.fn();
global.fetch = mockFetch;

describe("useSearch", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("returns null result for empty query", () => {
    const { result } = renderHook(() => useSearch("", "documents"));
    expect(result.current.result).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it("fetches document search results", async () => {
    const docs = [makeScoredDoc({ id: "doc-1" })];
    mockFetch.mockResolvedValueOnce(mockJsonResponse(docs));

    const { result } = renderHook(() => useSearch("test", "documents"));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
      expect(result.current.result).not.toBeNull();
    });
    expect(result.current.result?.mode).toBe("documents");
    expect(result.current.result?.results).toHaveLength(1);
  });

  it("fetches knowledge search results", async () => {
    const edges = [makeEdge({ id: "edge-1" })];
    mockFetch.mockResolvedValueOnce(mockJsonResponse(edges));

    const { result } = renderHook(() => useSearch("test", "knowledge"));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
      expect(result.current.result).not.toBeNull();
    });
    expect(result.current.result?.mode).toBe("knowledge");
    expect(result.current.result?.results).toHaveLength(1);
  });

  it("debounces rapid query changes (300ms)", async () => {
    mockFetch.mockResolvedValue(mockJsonResponse([]));

    const { rerender } = renderHook(
      ({ query }) => useSearch(query, "documents"),
      { initialProps: { query: "a" } },
    );

    rerender({ query: "ab" });
    rerender({ query: "abc" });

    await waitFor(() => expect(mockFetch).toHaveBeenCalledOnce());
    expect(mockFetch.mock.calls[0][0]).toContain("abc");
  });

  it("cancels previous request on new query (race condition)", async () => {
    const fastDoc = makeScoredDoc({ id: "fast" });

    // First call hangs forever (slow), second resolves fast
    mockFetch
      .mockImplementationOnce(() => new Promise(() => {}))
      .mockResolvedValueOnce(mockJsonResponse([fastDoc]));

    const { result, rerender } = renderHook(
      ({ query }) => useSearch(query, "documents"),
      { initialProps: { query: "slow" } },
    );

    // Wait for first debounce to fire
    await new Promise((r) => setTimeout(r, 350));

    // Change query — new debounce starts, old request key is stale
    rerender({ query: "fast" });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
      expect(result.current.result).not.toBeNull();
    });

    expect(result.current.result!.results[0]).toHaveProperty("id", "fast");
  });

  it("sets error on API failure", async () => {
    mockFetch.mockResolvedValueOnce(
      mockErrorResponse(500, "Internal Server Error", "crash"),
    );

    const { result } = renderHook(() => useSearch("fail", "documents"));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeTruthy();
    });
    expect(result.current.result).toBeNull();
  });
});
