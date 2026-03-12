import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NetworkPanel } from "@/components/NetworkPanel";
import { makeEngramDetail, makeEdge } from "../helpers/makeEngram";
import type { EngramDetail } from "@/lib/types";

function makeMap(details: EngramDetail[]): Map<string, EngramDetail> {
  return new Map(details.map((d) => [d.id, d]));
}

describe("NetworkPanel", () => {
  it('renders "Network" heading', () => {
    render(
      <NetworkPanel
        documentEngramIds={new Set()}
        engramDetails={new Map()}
        isLoading={false}
      />,
    );
    expect(screen.getByText("Network")).toBeInTheDocument();
  });

  it("shows loading state when isLoading=true", () => {
    render(
      <NetworkPanel
        documentEngramIds={new Set(["eng-1"])}
        engramDetails={new Map()}
        isLoading={true}
      />,
    );
    expect(screen.getByText("Loading network…")).toBeInTheDocument();
  });

  it("shows empty message when no engrams", () => {
    render(
      <NetworkPanel
        documentEngramIds={new Set()}
        engramDetails={new Map()}
        isLoading={false}
      />,
    );
    expect(screen.getByText("No engrams extracted yet.")).toBeInTheDocument();
  });

  it("renders engram badges for each document engram", () => {
    const e1 = makeEngramDetail({ id: "eng-1", engram: { id: "eng-1", canonical_name: "Concept A" } });
    const e2 = makeEngramDetail({ id: "eng-2", engram: { id: "eng-2", canonical_name: "Concept B" } });

    render(
      <NetworkPanel
        documentEngramIds={new Set(["eng-1", "eng-2"])}
        engramDetails={makeMap([e1, e2])}
        isLoading={false}
      />,
    );

    expect(screen.getByText("Concept A")).toBeInTheDocument();
    expect(screen.getByText("Concept B")).toBeInTheDocument();
  });

  it("groups edges by predicate with formatted headers", () => {
    const e1 = makeEngramDetail({
      id: "eng-1",
      engram: { id: "eng-1", canonical_name: "A" },
      edges: [
        makeEdge({ id: "e1", predicate: "supports", source_engram_id: "eng-1", target_engram_id: "eng-2" }),
        makeEdge({ id: "e2", predicate: "contradicts", source_engram_id: "eng-1", target_engram_id: "eng-3" }),
      ],
    });

    render(
      <NetworkPanel
        documentEngramIds={new Set(["eng-1"])}
        engramDetails={makeMap([e1])}
        isLoading={false}
      />,
    );

    expect(screen.getByText("Supports")).toBeInTheDocument();
    expect(screen.getByText("Contradicts")).toBeInTheDocument();
  });

  it("renders edge rows with source and target badges", () => {
    const e1 = makeEngramDetail({
      id: "eng-1",
      engram: { id: "eng-1", canonical_name: "Source Concept" },
      edges: [
        makeEdge({ id: "e1", predicate: "supports", source_engram_id: "eng-1", target_engram_id: "eng-2" }),
      ],
    });
    const e2 = makeEngramDetail({
      id: "eng-2",
      engram: { id: "eng-2", canonical_name: "Target Concept" },
    });

    render(
      <NetworkPanel
        documentEngramIds={new Set(["eng-1", "eng-2"])}
        engramDetails={makeMap([e1, e2])}
        isLoading={false}
      />,
    );

    // Each engram appears in the badges row AND in the edge row
    const sourceBadges = screen.getAllByText("Source Concept");
    expect(sourceBadges.length).toBe(2);
    const targetBadges = screen.getAllByText("Target Concept");
    expect(targetBadges.length).toBe(2);
    expect(screen.getByText("85%")).toBeInTheDocument();
  });

  it("deduplicates edges from multiple engram details", () => {
    const sharedEdge = makeEdge({
      id: "shared-edge",
      predicate: "supports",
      source_engram_id: "eng-1",
      target_engram_id: "eng-2",
    });

    const e1 = makeEngramDetail({
      id: "eng-1",
      engram: { id: "eng-1", canonical_name: "A" },
      edges: [sharedEdge],
    });
    const e2 = makeEngramDetail({
      id: "eng-2",
      engram: { id: "eng-2", canonical_name: "B" },
      edges: [sharedEdge],
    });

    render(
      <NetworkPanel
        documentEngramIds={new Set(["eng-1", "eng-2"])}
        engramDetails={makeMap([e1, e2])}
        isLoading={false}
      />,
    );

    // Should show "Supports" header only once
    const headers = screen.getAllByText("Supports");
    expect(headers).toHaveLength(1);

    // The "85%" confidence should appear only once (deduplicated edge)
    const confidences = screen.getAllByText("85%");
    expect(confidences).toHaveLength(1);
  });
});
