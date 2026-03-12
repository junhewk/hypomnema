import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { SearchPage } from "@/components/SearchPage";
import { makeScoredDoc } from "../helpers/makeDocument";
import { makeEdge, makeEngramDetail } from "../helpers/makeEngram";
import { mockJsonResponse, mockErrorResponse } from "../helpers/mockResponse";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

const mockFetch = vi.fn();
global.fetch = mockFetch;

describe("SearchPage", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("renders search bar", () => {
    render(<SearchPage />);
    expect(screen.getByTestId("search-input")).toBeInTheDocument();
  });

  it("shows document results as DocumentCards", async () => {
    const docs = [
      makeScoredDoc({ id: "doc-1", text: "Result one", score: 0.9 }),
    ];
    mockFetch.mockResolvedValueOnce(mockJsonResponse(docs));

    render(<SearchPage />);
    fireEvent.change(screen.getByTestId("search-input"), {
      target: { value: "test" },
    });

    await waitFor(() =>
      expect(screen.getByText("Result one")).toBeInTheDocument(),
    );
  });

  it("shows knowledge results with engram badges", async () => {
    const edges = [
      makeEdge({
        id: "edge-1",
        source_engram_id: "eng-1",
        target_engram_id: "eng-2",
        predicate: "supports",
      }),
    ];
    const eng1 = makeEngramDetail({ id: "eng-1", engram: { canonical_name: "Concept A" } });
    const eng2 = makeEngramDetail({ id: "eng-2", engram: { canonical_name: "Concept B" } });

    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(edges))
      .mockResolvedValueOnce(mockJsonResponse(eng1))
      .mockResolvedValueOnce(mockJsonResponse(eng2));

    render(<SearchPage />);
    fireEvent.click(screen.getByTestId("mode-knowledge"));
    fireEvent.change(screen.getByTestId("search-input"), {
      target: { value: "test" },
    });

    await waitFor(() =>
      expect(screen.getByTestId("knowledge-results")).toBeInTheDocument(),
    );
  });

  it('shows "No results found." for empty results', async () => {
    mockFetch.mockResolvedValueOnce(mockJsonResponse([]));

    render(<SearchPage />);
    fireEvent.change(screen.getByTestId("search-input"), {
      target: { value: "nothing" },
    });

    await waitFor(() =>
      expect(screen.getByText("No results found.")).toBeInTheDocument(),
    );
  });

  it("shows loading state while searching", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));

    render(<SearchPage />);
    fireEvent.change(screen.getByTestId("search-input"), {
      target: { value: "loading" },
    });

    // Loading shows immediately before debounce fires
    expect(screen.getByText("Searching…")).toBeInTheDocument();
  });

  it("shows error state on failure", async () => {
    mockFetch.mockResolvedValueOnce(
      mockErrorResponse(500, "Internal Server Error", "crash"),
    );

    render(<SearchPage />);
    fireEvent.change(screen.getByTestId("search-input"), {
      target: { value: "fail" },
    });

    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toBeInTheDocument(),
    );
  });
});
