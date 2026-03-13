import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ScribbleInput } from "@/components/ScribbleInput";
import { makeDoc } from "../helpers/makeDocument";

const mockFetch = vi.fn();
global.fetch = mockFetch;

const mockDoc = makeDoc({ id: "new-1", text: "hello" });

describe("ScribbleInput", () => {
  const onSubmit = vi.fn();

  beforeEach(() => {
    onSubmit.mockReset();
    mockFetch.mockReset();
  });

  it("renders textarea and submit button", () => {
    render(<ScribbleInput onSubmit={onSubmit} />);
    expect(
      screen.getByPlaceholderText("What are you thinking about?"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save/i })).toBeInTheDocument();
  });

  it("submit button is disabled when textarea is empty", () => {
    render(<ScribbleInput onSubmit={onSubmit} />);
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });

  it("submitting calls api.createScribble with correct args", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockDoc,
    });

    render(<ScribbleInput onSubmit={onSubmit} />);
    const textarea = screen.getByPlaceholderText(
      "What are you thinking about?",
    );
    fireEvent.change(textarea, { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/documents/scribbles"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ text: "hello" }),
      }),
    );
  });

  it("clears inputs after successful submit", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockDoc,
    });

    render(<ScribbleInput onSubmit={onSubmit} />);
    const textarea = screen.getByPlaceholderText(
      "What are you thinking about?",
    );
    fireEvent.change(textarea, { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(textarea).toHaveValue(""),
    );
  });

  it("resets textarea height after successful submit", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockDoc,
    });

    render(<ScribbleInput onSubmit={onSubmit} />);
    const textarea = screen.getByPlaceholderText(
      "What are you thinking about?",
    ) as HTMLTextAreaElement;
    textarea.style.height = "420px";
    fireEvent.change(textarea, { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(textarea).toHaveValue(""));
    await waitFor(() => expect(textarea.style.height).toBe(""));
  });

  it("calls onSubmit callback with returned document", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockDoc,
    });

    render(<ScribbleInput onSubmit={onSubmit} />);
    fireEvent.change(
      screen.getByPlaceholderText("What are you thinking about?"),
      { target: { value: "hello" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(mockDoc));
  });

  it("shows loading state during submission", async () => {
    mockFetch.mockReturnValueOnce(new Promise(() => {})); // never resolves

    render(<ScribbleInput onSubmit={onSubmit} />);
    fireEvent.change(
      screen.getByPlaceholderText("What are you thinking about?"),
      { target: { value: "hello" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByText("Saving...")).toBeInTheDocument();
  });

  it("shows error on API failure", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      text: async () => "crash",
    });

    render(<ScribbleInput onSubmit={onSubmit} />);
    fireEvent.change(
      screen.getByPlaceholderText("What are you thinking about?"),
      { target: { value: "hello" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });

  it("Cmd+Enter triggers submit", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockDoc,
    });

    render(<ScribbleInput onSubmit={onSubmit} />);
    const textarea = screen.getByPlaceholderText(
      "What are you thinking about?",
    );
    fireEvent.change(textarea, { target: { value: "hello" } });
    fireEvent.keyDown(textarea, { key: "Enter", metaKey: true });

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
  });
});
