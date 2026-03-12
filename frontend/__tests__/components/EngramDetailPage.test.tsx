import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { EngramDetailPage } from "@/components/EngramDetailPage";
import { makeEngramDetail, makeEdge } from "../helpers/makeEngram";
import { makeDoc } from "../helpers/makeDocument";
import { mockJsonResponse, mockErrorResponse } from "../helpers/mockResponse";

const mockFetch = vi.fn();
global.fetch = mockFetch;

describe("EngramDetailPage", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("shows loading state initially", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    render(<EngramDetailPage id="eng-1" />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders engram canonical name as heading", async () => {
    const detail = makeEngramDetail({
      id: "eng-1",
      engram: { canonical_name: "Quantum Entanglement" },
    });
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(detail))
      .mockResolvedValueOnce(mockJsonResponse([]));

    render(<EngramDetailPage id="eng-1" />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Quantum Entanglement" }),
      ).toBeInTheDocument(),
    );
  });

  it("renders engram description", async () => {
    const detail = makeEngramDetail({
      id: "eng-1",
      engram: { description: "A spooky action at a distance" },
    });
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(detail))
      .mockResolvedValueOnce(mockJsonResponse([]));

    render(<EngramDetailPage id="eng-1" />);
    await waitFor(() =>
      expect(
        screen.getByText("A spooky action at a distance"),
      ).toBeInTheDocument(),
    );
  });

  it("shows NetworkPanel with edges", async () => {
    const detail = makeEngramDetail({
      id: "eng-1",
      engram: { canonical_name: "Source" },
      edges: [
        makeEdge({
          id: "edge-1",
          source_engram_id: "eng-1",
          target_engram_id: "eng-2",
        }),
      ],
    });
    const neighborDetail = makeEngramDetail({
      id: "eng-2",
      engram: { canonical_name: "Target" },
    });

    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(detail))
      .mockResolvedValueOnce(mockJsonResponse([]))
      .mockResolvedValueOnce(mockJsonResponse(neighborDetail));

    render(<EngramDetailPage id="eng-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("network-panel")).toBeInTheDocument(),
    );
  });

  it("shows cluster documents as DocumentCards", async () => {
    const detail = makeEngramDetail({ id: "eng-1" });
    const cluster = [
      makeDoc({ id: "doc-1", text: "Cluster doc one" }),
      makeDoc({ id: "doc-2", text: "Cluster doc two" }),
    ];
    mockFetch
      .mockResolvedValueOnce(mockJsonResponse(detail))
      .mockResolvedValueOnce(mockJsonResponse(cluster));

    render(<EngramDetailPage id="eng-1" />);
    await waitFor(() =>
      expect(screen.getByText("Cluster doc one")).toBeInTheDocument(),
    );
    expect(screen.getByText("Cluster doc two")).toBeInTheDocument();
  });

  it("shows error state on 404", async () => {
    mockFetch.mockResolvedValue(
      mockErrorResponse(404, "Not Found", "not found"),
    );

    render(<EngramDetailPage id="bad-id" />);
    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toBeInTheDocument(),
    );
  });
});
