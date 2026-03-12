import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { VizPage } from "@/components/VizPage";
import { makeProjectionPoint, makeCluster, makeVizEdge } from "../helpers/makeViz";

// Mock VizScene — Three.js cannot run in jsdom
vi.mock("@/components/VizScene", () => ({
  VizScene: () => <div data-testid="viz-scene-mock">VizScene</div>,
}));

// Mock useVizData
const mockUseVizData = vi.fn();
vi.mock("@/hooks/useVizData", () => ({
  useVizData: () => mockUseVizData(),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("VizPage", () => {
  it("shows loading state initially", () => {
    mockUseVizData.mockReturnValue({
      points: [],
      clusters: [],
      edges: [],
      isLoading: true,
      error: null,
    });
    render(<VizPage />);
    expect(screen.getByText(/Loading visualization/)).toBeInTheDocument();
  });

  it("shows error state on API failure", () => {
    mockUseVizData.mockReturnValue({
      points: [],
      clusters: [],
      edges: [],
      isLoading: false,
      error: "Network error",
    });
    render(<VizPage />);
    expect(screen.getByTestId("error-message")).toHaveTextContent(
      "Network error",
    );
  });

  it("shows empty state when points empty", () => {
    mockUseVizData.mockReturnValue({
      points: [],
      clusters: [],
      edges: [],
      isLoading: false,
      error: null,
    });
    render(<VizPage />);
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
  });

  it("renders nav links", () => {
    mockUseVizData.mockReturnValue({
      points: [makeProjectionPoint()],
      clusters: [makeCluster()],
      edges: [makeVizEdge()],
      isLoading: false,
      error: null,
    });
    render(<VizPage />);
    expect(screen.getByTestId("stream-link")).toHaveAttribute("href", "/");
    expect(screen.getByTestId("search-link")).toHaveAttribute("href", "/search");
    expect(screen.getByTestId("viz-scene-mock")).toBeInTheDocument();
  });
});
