"use client";

import { useState, useRef, type FormEvent, type KeyboardEvent } from "react";
import { api } from "@/lib/api";
import type { Document } from "@/lib/types";

interface ScribbleInputProps {
  onSubmit: (doc: Document) => void;
}

export function ScribbleInput({ onSubmit }: ScribbleInputProps) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const canSubmit = text.trim().length > 0 && !isSubmitting;

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    if (!canSubmit) return;

    setIsSubmitting(true);
    setError(null);
    try {
      const doc = await api.createScribble(
        text.trim(),
        title.trim() || undefined,
      );
      setTitle("");
      setText("");
      onSubmit(doc);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  }

  function handleTextareaInput() {
    const el = textareaRef.current;
    if (el) {
      requestAnimationFrame(() => {
        el.style.height = "auto";
        el.style.height = el.scrollHeight + "px";
      });
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mb-8 rounded-lg border border-border bg-surface-raised p-4 transition-shadow focus-within:shadow-[0_0_0_1px_var(--border-focus)]"
    >
      <input
        type="text"
        value={title}
        onChange={(e) => {
          setTitle(e.target.value);
          setError(null);
        }}
        placeholder="Title (optional)"
        disabled={isSubmitting}
        className="mb-3 w-full bg-transparent font-sans text-sm font-medium outline-none placeholder:text-muted/50"
      />
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setError(null);
        }}
        onInput={handleTextareaInput}
        onKeyDown={handleKeyDown}
        placeholder="What are you thinking about?"
        disabled={isSubmitting}
        rows={3}
        className="w-full resize-none bg-transparent font-mono text-sm leading-relaxed outline-none placeholder:text-muted/40"
      />

      {error && (
        <p className="mt-2 font-mono text-xs text-red-500" role="alert">
          {error}
        </p>
      )}

      <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
        <span className="font-mono text-[10px] text-muted/40">
          {canSubmit ? "\u2318\u23CE to save" : ""}
        </span>
        <button
          type="submit"
          disabled={!canSubmit}
          className="rounded-md bg-foreground px-4 py-1.5 font-mono text-xs font-medium text-background transition-opacity disabled:opacity-20"
        >
          {isSubmitting ? "Saving..." : "Save"}
        </button>
      </div>
    </form>
  );
}
