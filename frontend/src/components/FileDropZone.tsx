"use client";

import { useState, useRef, type DragEvent } from "react";
import { api } from "@/lib/api";
import type { Document } from "@/lib/types";

interface FileDropZoneProps {
  onUpload: (doc: Document) => void;
}

export function FileDropZone({ onUpload }: FileDropZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setIsUploading(true);
    setError(null);
    try {
      const doc = await api.uploadFile(file);
      onUpload(doc);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault();
    setIsDragOver(true);
  }

  function handleDragLeave(e: DragEvent) {
    e.preventDefault();
    setIsDragOver(false);
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) upload(file);
  }

  function handleClick() {
    inputRef.current?.click();
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) upload(file);
    if (inputRef.current) inputRef.current.value = "";
  }

  let stateClass = "border-border/60 hover:border-border";
  if (isDragOver)
    stateClass = "border-accent bg-accent-soft scale-[1.01]";
  if (isUploading) stateClass = "border-muted animate-pulse";

  return (
    <div className="mb-8">
      <div
        role="button"
        tabIndex={0}
        onClick={handleClick}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") handleClick();
        }}
        className={`cursor-pointer rounded-lg border border-dashed ${stateClass} px-4 py-4 text-center transition-all duration-200`}
      >
        <p className="font-mono text-xs text-muted">
          {isUploading ? (
            "Uploading..."
          ) : (
            <>
              <span className="text-foreground/60">Drop</span>{" "}
              PDF, DOCX, or MD
            </>
          )}
        </p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.md"
        onChange={handleFileChange}
        className="hidden"
        data-testid="file-input"
      />
      {error && (
        <p className="mt-1 font-mono text-xs text-red-500" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
