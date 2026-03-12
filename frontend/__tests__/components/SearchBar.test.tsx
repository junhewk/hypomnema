import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SearchBar } from "@/components/SearchBar";

describe("SearchBar", () => {
  const defaultProps = {
    query: "",
    mode: "documents" as const,
    onQueryChange: vi.fn(),
    onModeChange: vi.fn(),
  };

  it("renders search input with placeholder", () => {
    render(<SearchBar {...defaultProps} />);
    expect(
      screen.getByPlaceholderText("Search documents or knowledge…"),
    ).toBeInTheDocument();
  });

  it("calls onQueryChange on input", () => {
    const onQueryChange = vi.fn();
    render(<SearchBar {...defaultProps} onQueryChange={onQueryChange} />);
    fireEvent.change(screen.getByTestId("search-input"), {
      target: { value: "test" },
    });
    expect(onQueryChange).toHaveBeenCalledWith("test");
  });

  it("shows active state on current mode pill", () => {
    render(<SearchBar {...defaultProps} mode="documents" />);
    const docBtn = screen.getByTestId("mode-documents");
    const kgBtn = screen.getByTestId("mode-knowledge");
    expect(docBtn.className).toContain("bg-foreground");
    expect(kgBtn.className).not.toContain("bg-foreground");
  });

  it("calls onModeChange when clicking mode pill", () => {
    const onModeChange = vi.fn();
    render(<SearchBar {...defaultProps} onModeChange={onModeChange} />);
    fireEvent.click(screen.getByTestId("mode-knowledge"));
    expect(onModeChange).toHaveBeenCalledWith("knowledge");
  });

  it("defaults documents mode as active", () => {
    render(<SearchBar {...defaultProps} />);
    const docBtn = screen.getByTestId("mode-documents");
    expect(docBtn.className).toContain("bg-foreground");
  });
});
