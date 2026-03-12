import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { DocumentCard } from "@/components/DocumentCard";
import { makeDoc, makeScoredDoc } from "../helpers/makeDocument";

describe("DocumentCard", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders title when present", () => {
    render(<DocumentCard document={makeDoc({ title: "My Title" })} />);
    expect(screen.getByText("My Title")).toBeInTheDocument();
  });

  it("renders text preview truncated to 280 chars", () => {
    const longText = "a".repeat(300);
    render(<DocumentCard document={makeDoc({ text: longText })} />);
    const preview = screen.getByText(/^a+\u2026$/);
    expect(preview.textContent).toHaveLength(281); // 280 + ellipsis
  });

  it("shows correct source type badge for scribble", () => {
    render(<DocumentCard document={makeDoc({ source_type: "scribble" })} />);
    expect(screen.getByText("scribble")).toBeInTheDocument();
  });

  it("shows correct source type badge for file", () => {
    render(<DocumentCard document={makeDoc({ source_type: "file" })} />);
    expect(screen.getByText("file")).toBeInTheDocument();
  });

  it("shows correct source type badge for feed", () => {
    render(<DocumentCard document={makeDoc({ source_type: "feed" })} />);
    expect(screen.getByText("feed")).toBeInTheDocument();
  });

  it("renders processing status dot with correct color", () => {
    const { rerender } = render(
      <DocumentCard document={makeDoc({ processed: 0 })} />,
    );
    let dot = screen.getByTestId("status-dot");
    expect(dot.className).toContain("bg-amber-400");

    rerender(<DocumentCard document={makeDoc({ processed: 1 })} />);
    dot = screen.getByTestId("status-dot");
    expect(dot.className).toContain("bg-blue-400");

    rerender(<DocumentCard document={makeDoc({ processed: 2 })} />);
    dot = screen.getByTestId("status-dot");
    expect(dot.className).toContain("bg-green-400");
  });

  it("shows relative timestamp", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T01:00:00Z"));
    render(
      <DocumentCard
        document={makeDoc({ created_at: "2026-01-01T00:00:00Z" })}
      />,
    );
    expect(screen.getByText("1h ago")).toBeInTheDocument();
  });

  it("handles null title", () => {
    render(<DocumentCard document={makeDoc({ title: null })} />);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });

  it("handles null mime_type", () => {
    render(<DocumentCard document={makeDoc({ mime_type: null })} />);
    // Should not crash and not show mime type text
    expect(screen.getByTestId("document-card")).toBeInTheDocument();
  });

  it("shows mime_type when present", () => {
    render(
      <DocumentCard document={makeDoc({ mime_type: "application/pdf" })} />,
    );
    expect(screen.getByText("application/pdf")).toBeInTheDocument();
  });

  it("card links to /documents/{id}", () => {
    render(<DocumentCard document={makeDoc({ id: "doc-42" })} />);
    const link = screen.getByTestId("document-link");
    expect(link).toHaveAttribute("href", "/documents/doc-42");
  });

  it("shows score badge when document has score", () => {
    render(<DocumentCard document={makeScoredDoc({ score: 0.92 })} />);
    expect(screen.getByTestId("score-badge")).toHaveTextContent("92% match");
  });
});
