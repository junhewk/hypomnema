"use client";

import { useState, useRef, useEffect, type FormEvent, type KeyboardEvent } from "react";
import { api } from "@/lib/api";
import type { Document } from "@/lib/types";

const DRAFT_KEY = "hypomnema_draft";

interface ScribbleInputProps {
  onSubmit: (doc: Document) => void;
  editingDocument?: Document | null;
  onCancelEdit?: () => void;
}

export function ScribbleInput({ onSubmit, editingDocument, onCancelEdit }: ScribbleInputProps) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draftStatus, setDraftStatus] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const canSubmit = text.trim().length > 0 && !isSubmitting;
  const isEditing = editingDocument != null;

  function syncTextareaHeight(nextText: string) {
    const el = textareaRef.current;
    if (!el) return;
    if (!nextText) {
      el.style.height = "";
      return;
    }
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  // Restore draft on mount (only when not editing)
  useEffect(() => {
    if (isEditing) return;
    try {
      const draft = localStorage.getItem(DRAFT_KEY);
      if (draft) {
        const { title: t, text: tx } = JSON.parse(draft);
        if (t || tx) {
          setTitle(t || "");
          setText(tx || "");
          setDraftStatus("draft restored");
          setTimeout(() => setDraftStatus(null), 2000);
        }
      }
    } catch {
      // ignore malformed draft
    }
  }, [isEditing]);

  // Auto-save draft (debounced, only when not editing)
  useEffect(() => {
    if (isEditing) return;
    const timer = setTimeout(() => {
      if (text || title) {
        localStorage.setItem(DRAFT_KEY, JSON.stringify({ title, text }));
      } else {
        localStorage.removeItem(DRAFT_KEY);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [title, text, isEditing]);

  // Pre-fill when editing
  useEffect(() => {
    if (editingDocument) {
      setTitle(editingDocument.title || "");
      setText(editingDocument.text);
      setError(null);
    }
  }, [editingDocument]);

  useEffect(() => {
    syncTextareaHeight(text);
  }, [text]);

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    if (!canSubmit) return;

    setIsSubmitting(true);
    setError(null);
    try {
      let doc: Document;
      if (isEditing) {
        doc = await api.updateDocument(editingDocument.id, {
          text: text.trim(),
          title: title.trim() || undefined,
        });
      } else {
        doc = await api.createScribble(text.trim(), title.trim() || undefined);
      }
      setTitle("");
      setText("");
      localStorage.removeItem(DRAFT_KEY);
      onSubmit(doc);
      if (isEditing && onCancelEdit) {
        onCancelEdit();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleCancel() {
    setTitle("");
    setText("");
    setError(null);
    onCancelEdit?.();
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
        syncTextareaHeight(el.value);
      });
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="editor-surface mb-8 rounded-lg border border-border p-5 transition-shadow focus-within:shadow-[0_0_0_1px_var(--border-focus)]"
    >
      {isEditing && (
        <div className="mb-4 flex items-center gap-2">
          <span className="editing-badge rounded bg-[var(--accent)]/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-[var(--accent)]">
            editing
          </span>
          {editingDocument.title && (
            <span className="font-mono text-[11px] text-muted truncate">
              {editingDocument.title}
            </span>
          )}
        </div>
      )}

      <input
        type="text"
        value={title}
        onChange={(e) => {
          setTitle(e.target.value);
          setError(null);
        }}
        placeholder="Title (optional)"
        disabled={isSubmitting}
        className="mb-3 w-full bg-transparent font-sans text-sm font-medium outline-none placeholder:text-muted/40"
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
        rows={10}
        className="w-full resize-none bg-transparent font-mono text-sm leading-[1.8] outline-none placeholder:text-muted/30"
      />

      {error && (
        <p className="mt-2 font-mono text-xs text-red-500" role="alert">
          {error}
        </p>
      )}

      <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
        <span className="font-mono text-[10px] text-muted/30">
          {draftStatus ? (
            <span className="draft-status text-[var(--engram)]/60">{draftStatus}</span>
          ) : canSubmit ? (
            "\u2318\u23CE to save"
          ) : (
            ""
          )}
        </span>
        <div className="flex items-center gap-2">
          {isEditing && (
            <button
              type="button"
              onClick={handleCancel}
              className="rounded border border-border px-3 py-1.5 font-mono text-[11px] text-muted transition-colors hover:border-border-focus hover:text-foreground"
            >
              Cancel
            </button>
          )}
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded bg-foreground px-4 py-1.5 font-mono text-[11px] font-medium text-background transition-opacity disabled:opacity-15"
          >
            {isSubmitting
              ? "Saving..."
              : isEditing
                ? "Save & Reprocess"
                : "Save"}
          </button>
        </div>
      </div>
    </form>
  );
}
