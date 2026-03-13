import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { DocumentDetailPage } from "@/components/DocumentDetailPage";
import { makeDocumentDetail } from "../helpers/makeEngram";

const mockFetch = vi.fn();
global.fetch = mockFetch;

function mockDocResponse(doc: object) {
  return {
    ok: true,
    status: 200,
    json: async () => doc,
  };
}

describe("DocumentDetailPage", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("shows loading state initially", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    render(<DocumentDetailPage id="doc-1" />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders full document text (not truncated)", async () => {
    const longText = "a".repeat(500);
    const doc = makeDocumentDetail({ id: "doc-1", text: longText });
    mockFetch.mockResolvedValueOnce(mockDocResponse(doc));

    render(<DocumentDetailPage id="doc-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("document-text")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("document-text").textContent).toHaveLength(500);
  });

  it("renders document title", async () => {
    const doc = makeDocumentDetail({ id: "doc-1", title: "My Research" });
    mockFetch.mockResolvedValueOnce(mockDocResponse(doc));

    render(<DocumentDetailPage id="doc-1" />);
    await waitFor(() =>
      expect(screen.getByText("My Research")).toBeInTheDocument(),
    );
  });

  it("shows source type badge", async () => {
    const doc = makeDocumentDetail({ id: "doc-1", source_type: "file" });
    mockFetch.mockResolvedValueOnce(mockDocResponse(doc));

    render(<DocumentDetailPage id="doc-1" />);
    await waitFor(() =>
      expect(screen.getByText("file")).toBeInTheDocument(),
    );
  });

  it("renders without back link (sidebar provides navigation)", async () => {
    const doc = makeDocumentDetail({ id: "doc-1" });
    mockFetch.mockResolvedValueOnce(mockDocResponse(doc));

    render(<DocumentDetailPage id="doc-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("document-text")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("back-link")).not.toBeInTheDocument();
  });

  it("shows error state on API failure", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      text: async () => "crash",
    });

    render(<DocumentDetailPage id="doc-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toBeInTheDocument(),
    );
  });
});
