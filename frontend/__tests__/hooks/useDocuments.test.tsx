import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useDocuments } from "@/hooks/useDocuments";
import { makeDocs } from "../helpers/makeDocument";

const mockFetch = vi.fn();
global.fetch = mockFetch;

function mockListResponse(items: Array<{ id: string }>) {
  return {
    ok: true,
    status: 200,
    json: async () => items,
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
    mockFetch.mockResolvedValueOnce(mockListResponse(docs));

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.documents).toHaveLength(2);
  });

  it("returns documents from API", async () => {
    const docs = makeDocs(["a", "b", "c"]);
    mockFetch.mockResolvedValueOnce(mockListResponse(docs));

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.documents.map((d) => d.id)).toEqual(["a", "b", "c"]);
  });

  it("refresh re-fetches documents", async () => {
    const docs = makeDocs(["1", "2"]);
    mockFetch.mockResolvedValueOnce(mockListResponse(docs));

    const { result } = renderHook(() => useDocuments());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const refreshedDocs = makeDocs(["a", "b", "c"]);
    mockFetch.mockResolvedValueOnce(mockListResponse(refreshedDocs));
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
