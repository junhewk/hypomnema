import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { VizTooltip } from "@/components/VizTooltip";

describe("VizTooltip", () => {
  it("shows canonical_name", () => {
    render(<VizTooltip name="Test Concept" clusterLabel={null} />);
    expect(screen.getByText("Test Concept")).toBeInTheDocument();
  });

  it("shows cluster label when provided", () => {
    render(<VizTooltip name="Test Concept" clusterLabel="Science Cluster" />);
    expect(screen.getByText("Science Cluster")).toBeInTheDocument();
  });

  it("omits cluster label when null", () => {
    const { container } = render(
      <VizTooltip name="Test Concept" clusterLabel={null} />,
    );
    const tooltip = container.querySelector('[data-testid="viz-tooltip"]')!;
    expect(tooltip.querySelectorAll("p")).toHaveLength(1);
  });
});
