import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useDocuments } from "@/hooks/useDocuments";
import { makeDocs } from "../helpers/makeDocument";

const mockFetch = vi.fn();
global.fetch = mockFetch;

function mockListResponse(
  items: Array<{ id: string }>,
  total: number,
  offset = 0,
) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ items, total, offset, limit: 20 }),
  };
}

describe("useDocuments", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("returns isLoading=true initially", () => {
    mockFetch.mockReturnValue(
      new Promise(() => {}), // never resolves
    );
    const { result } = renderHook(() => useDocuments());
    expect(result.current.isLoading).toBe(true);
  });

  it("fetches documents on mount", async () => {
    const docs = makeDocs(["1", "2"]);
    mockFetch.mockResolvedValueOnce(mockListResponse(docs, 2));

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.documents).toHaveLength(2);
    expect(result.current.total).toBe(2);
  });

  it("returns documents from API", async () => {
    const docs = makeDocs(["a", "b", "c"]);
    mockFetch.mockResolvedValueOnce(mockListResponse(docs, 3));

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.documents.map((d) => d.id)).toEqual(["a", "b", "c"]);
  });

  it("loadMore appends next page", async () => {
    const page1 = makeDocs(["1", "2"]);
    const page2 = makeDocs(["3", "4"]);
    mockFetch.mockResolvedValueOnce(mockListResponse(page1, 4));

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    mockFetch.mockResolvedValueOnce(mockListResponse(page2, 4, 2));
    await act(async () => {
      result.current.loadMore();
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.documents).toHaveLength(4);
  });

  it("hasMore is true when documents.length < total", async () => {
    const docs = makeDocs(["1"]);
    mockFetch.mockResolvedValueOnce(mockListResponse(docs, 5));

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.hasMore).toBe(true);
  });

  it("hasMore is false when all loaded", async () => {
    const docs = makeDocs(["1", "2"]);
    mockFetch.mockResolvedValueOnce(mockListResponse(docs, 2));

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.hasMore).toBe(false);
  });

  it("refresh resets to first page", async () => {
    const docs = makeDocs(["1", "2"]);
    mockFetch.mockResolvedValueOnce(mockListResponse(docs, 2));

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const refreshedDocs = makeDocs(["a", "b", "c"]);
    mockFetch.mockResolvedValueOnce(mockListResponse(refreshedDocs, 3));
    await act(async () => {
      result.current.refresh();
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.documents.map((d) => d.id)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  it("sets error on API failure", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      text: async () => "crash",
    });

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.error).toBeTruthy();
  });
});
