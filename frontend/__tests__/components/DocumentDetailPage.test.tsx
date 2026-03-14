import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { DocumentDetailPage } from "@/components/DocumentDetailPage";
import { makeDocumentDetail } from "../helpers/makeEngram";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}));

const mockFetch = vi.fn();
global.fetch = mockFetch;

function mockJsonResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => data,
  };
}

/** Mock fetch for DocumentDetailPage: document detail + related docs */
function mockDocumentPageFetches(doc: object) {
  mockFetch.mockImplementation((url: string) => {
    if (typeof url === "string" && url.includes("/related")) {
      return Promise.resolve(mockJsonResponse([]));
    }
    return Promise.resolve(mockJsonResponse(doc));
  });
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
    mockDocumentPageFetches(doc);

    render(<DocumentDetailPage id="doc-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("document-text")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("document-text").textContent).toHaveLength(500);
  });

  it("renders document title", async () => {
    const doc = makeDocumentDetail({ id: "doc-1", title: "My Research" });
    mockDocumentPageFetches(doc);

    render(<DocumentDetailPage id="doc-1" />);
    await waitFor(() =>
      expect(screen.getByText("My Research")).toBeInTheDocument(),
    );
  });

  it("shows source type badge", async () => {
    const doc = makeDocumentDetail({ id: "doc-1", source_type: "file" });
    mockDocumentPageFetches(doc);

    render(<DocumentDetailPage id="doc-1" />);
    await waitFor(() =>
      expect(screen.getByText("file")).toBeInTheDocument(),
    );
  });

  it("renders without back link (sidebar provides navigation)", async () => {
    const doc = makeDocumentDetail({ id: "doc-1" });
    mockDocumentPageFetches(doc);

    render(<DocumentDetailPage id="doc-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("document-text")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("back-link")).not.toBeInTheDocument();
  });

  it("shows error state on API failure", async () => {
    mockFetch.mockImplementation(() =>
      Promise.resolve({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        text: async () => "crash",
      }),
    );

    render(<DocumentDetailPage id="doc-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toBeInTheDocument(),
    );
  });
});
