import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { FileDropZone } from "@/components/FileDropZone";
import { makeDoc } from "../helpers/makeDocument";

const mockFetch = vi.fn();
global.fetch = mockFetch;

const mockDoc = makeDoc({
  id: "file-1",
  source_type: "file",
  title: "test.pdf",
  text: "extracted text",
  mime_type: "application/pdf",
});

describe("FileDropZone", () => {
  const onUpload = vi.fn();

  beforeEach(() => {
    onUpload.mockReset();
    mockFetch.mockReset();
  });

  it("renders drop zone with instruction text", () => {
    render(<FileDropZone onUpload={onUpload} />);
    expect(
      screen.getByText(
        (_, el) =>
          el?.tagName === "P" &&
          el?.textContent === "Drop PDF, DOCX, or MD",
      ),
    ).toBeInTheDocument();
  });

  it("click triggers file input", () => {
    render(<FileDropZone onUpload={onUpload} />);
    const input = screen.getByTestId("file-input") as HTMLInputElement;
    const clickSpy = vi.spyOn(input, "click");
    fireEvent.click(screen.getByRole("button"));
    expect(clickSpy).toHaveBeenCalled();
  });

  it("file selection calls api.uploadFile", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockDoc,
    });

    render(<FileDropZone onUpload={onUpload} />);
    const input = screen.getByTestId("file-input");
    const file = new File(["content"], "test.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/documents/files"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("calls onUpload after success", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => mockDoc,
    });

    render(<FileDropZone onUpload={onUpload} />);
    const input = screen.getByTestId("file-input");
    const file = new File(["content"], "test.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(onUpload).toHaveBeenCalledWith(mockDoc));
  });

  it("shows error on failure", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      text: async () => "crash",
    });

    render(<FileDropZone onUpload={onUpload} />);
    const input = screen.getByTestId("file-input");
    const file = new File(["content"], "test.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });
});
