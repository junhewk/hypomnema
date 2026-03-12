import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EngramBadge } from "@/components/EngramBadge";

describe("EngramBadge", () => {
  const engram = { id: "eng-1", canonical_name: "Test Concept" };

  it("renders canonical name text", () => {
    render(<EngramBadge engram={engram} />);
    expect(screen.getByText("Test Concept")).toBeInTheDocument();
  });

  it("links to /engrams/{id}", () => {
    render(<EngramBadge engram={engram} />);
    const link = screen.getByTestId("engram-badge");
    expect(link).toHaveAttribute("href", "/engrams/eng-1");
  });

  it("applies dimmed opacity when dimmed=true", () => {
    render(<EngramBadge engram={engram} dimmed />);
    const badge = screen.getByTestId("engram-badge");
    expect(badge.className).toContain("opacity-50");
  });

  it("default (no dimmed) has full opacity", () => {
    render(<EngramBadge engram={engram} />);
    const badge = screen.getByTestId("engram-badge");
    expect(badge.className).not.toContain("opacity-50");
  });
});
