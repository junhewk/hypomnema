import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useDocument } from "@/hooks/useDocument";
import { makeDocumentDetail } from "../helpers/makeEngram";
import { makeEngram } from "../helpers/makeEngram";

const mockFetch = vi.fn();
global.fetch = mockFetch;

function mockDocResponse(doc: object) {
  return {
    ok: true,
    status: 200,
    json: async () => doc,
  };
}

describe("useDocument", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("returns isLoading=true initially", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useDocument("doc-1"));
    expect(result.current.isLoading).toBe(true);
  });

  it("fetches document detail on mount", async () => {
    const doc = makeDocumentDetail({ id: "doc-1", text: "hello" });
    mockFetch.mockResolvedValueOnce(mockDocResponse(doc));

    const { result } = renderHook(() => useDocument("doc-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(mockFetch).toHaveBeenCalledOnce();
    expect(mockFetch.mock.calls[0][0]).toContain("/api/documents/doc-1");
  });

  it("returns document with engrams array", async () => {
    const doc = makeDocumentDetail({
      id: "doc-1",
      engrams: [makeEngram({ id: "eng-1" }), makeEngram({ id: "eng-2" })],
    });
    mockFetch.mockResolvedValueOnce(mockDocResponse(doc));

    const { result } = renderHook(() => useDocument("doc-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.document?.engrams).toHaveLength(2);
  });

  it("sets error on API failure", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: "Not Found",
      text: async () => "not found",
    });

    const { result } = renderHook(() => useDocument("bad-id"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.error).toBeTruthy();
    expect(result.current.document).toBeNull();
  });

  it("refetches when id changes", async () => {
    const doc1 = makeDocumentDetail({ id: "doc-1", text: "first" });
    const doc2 = makeDocumentDetail({ id: "doc-2", text: "second" });
    mockFetch.mockResolvedValueOnce(mockDocResponse(doc1));

    const { result, rerender } = renderHook(
      ({ id }) => useDocument(id),
      { initialProps: { id: "doc-1" } },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.document?.id).toBe("doc-1");

    mockFetch.mockResolvedValueOnce(mockDocResponse(doc2));
    rerender({ id: "doc-2" });
    await waitFor(() => expect(result.current.document?.id).toBe("doc-2"));
  });
});
