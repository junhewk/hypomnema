"use client";

import { useState, useRef, useEffect, type FormEvent, type KeyboardEvent, type DragEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { readLocalStorage, removeLocalStorage, writeLocalStorage } from "@/lib/storage";
import type { Document } from "@/lib/types";

const DRAFT_KEY = "hypomnema_draft";
const URL_RE = /^https?:\/\/\S+$/;

interface ScribbleInputProps {
  onSubmit: (doc: Document) => void;
  onDraft?: (doc: Document) => void;
  editingDocument?: Document | null;
  onCancelEdit?: () => void;
}

export function ScribbleInput({ onSubmit, onDraft, editingDocument, onCancelEdit }: ScribbleInputProps) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draftStatus, setDraftStatus] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isEditing = editingDocument != null;
  const trimmed = text.trim();
  const canSubmit = trimmed.length > 0 && !isSubmitting;
  const isUrl = canSubmit && URL_RE.test(trimmed) && !trimmed.includes("\n") && !isEditing;

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
      const draft = readLocalStorage(DRAFT_KEY);
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
        writeLocalStorage(DRAFT_KEY, JSON.stringify({ title, text }));
      } else {
        removeLocalStorage(DRAFT_KEY);
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

  const uploadRef = useRef<(file: File) => void>(undefined);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  async function uploadFile(file: File) {
    setIsUploading(true);
    setError(null);
    try {
      const doc = await api.uploadFile(file);
      onSubmit(doc);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  }
  uploadRef.current = uploadFile;

  // Global drag-and-drop: prevent default everywhere, show overlay via debounce
  useEffect(() => {
    function onDragOver(e: globalThis.DragEvent) {
      e.preventDefault();
      // Reset hide timer on every dragover — keeps overlay visible while dragging
      clearTimeout(hideTimerRef.current);
      setIsDragOver(true);
      hideTimerRef.current = setTimeout(() => setIsDragOver(false), 150);
    }
    function onDrop(e: globalThis.DragEvent) {
      e.preventDefault();
      e.stopPropagation();
      clearTimeout(hideTimerRef.current);
      setIsDragOver(false);
      const file = e.dataTransfer?.files[0];
      if (file) uploadRef.current?.(file);
    }
    function onDragLeave(e: globalThis.DragEvent) {
      // Only hide when leaving the window entirely
      if (!e.relatedTarget) {
        clearTimeout(hideTimerRef.current);
        hideTimerRef.current = setTimeout(() => setIsDragOver(false), 100);
      }
    }
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("drop", onDrop);
    window.addEventListener("dragleave", onDragLeave);
    return () => {
      clearTimeout(hideTimerRef.current);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("drop", onDrop);
      window.removeEventListener("dragleave", onDragLeave);
    };
  }, []);

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
      } else if (isUrl) {
        doc = await api.fetchUrl(trimmed);
      } else {
        doc = await api.createScribble(text.trim(), title.trim() || undefined);
      }
      setTitle("");
      setText("");
      removeLocalStorage(DRAFT_KEY);
      onSubmit(doc);
      if (isEditing && onCancelEdit) {
        onCancelEdit();
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("This URL has already been fetched.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to save");
      }
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

  async function handleDraft() {
    if (!canSubmit) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const doc = await api.createScribble(text.trim(), title.trim() || undefined, true);
      setTitle("");
      setText("");
      removeLocalStorage(DRAFT_KEY);
      onDraft?.(doc);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save draft");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
    if ((e.metaKey || e.ctrlKey) && e.key === "d" && !isEditing && !isUrl) {
      e.preventDefault();
      handleDraft();
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
      data-url-mode={isUrl || undefined}
      className="editor-surface relative mb-8 rounded-lg border border-border p-5 transition-shadow focus-within:shadow-[0_0_0_1px_var(--border-focus)]"
    >
      {isDragOver && (
        <div className="drop-overlay pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
          <span className="font-mono text-[11px] uppercase tracking-wider text-[var(--accent)]">Drop file</span>
        </div>
      )}

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
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-muted/30">
            {isUploading ? (
              <span className="text-[var(--accent)]/60">Uploading...</span>
            ) : draftStatus ? (
              <span className="draft-status text-[var(--engram)]/60">{draftStatus}</span>
            ) : canSubmit ? (
              isUrl ? (
                <span>{"\u2318\u23CE"} fetch</span>
              ) : (
                <><span>{"\u2318\u23CE"} save</span>{!isEditing && <span className="ml-2 text-muted/20">{"\u2318"}D draft</span>}</>
              )
            ) : (
              <span className="text-muted/20">drop <span className="text-[var(--source-file)]/20">.pdf .docx .md</span> · paste a <span className="text-[var(--source-url)]/20">URL</span></span>
            )}
          </span>
        </div>
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
          {!isEditing && !isUrl && (
            <button
              type="button"
              onClick={handleDraft}
              disabled={!canSubmit}
              className="draft-save-btn rounded border px-3 py-1.5 font-mono text-[11px] text-muted disabled:opacity-15"
            >
              Draft
            </button>
          )}
          <button
            type="submit"
            disabled={!canSubmit}
            className={`rounded px-4 py-1.5 font-mono text-[11px] font-medium disabled:opacity-15 ${
              isUrl
                ? "fetch-btn"
                : "bg-foreground text-background transition-opacity"
            }`}
          >
            {isSubmitting
              ? isUrl ? "Fetching..." : "Saving..."
              : isEditing
                ? "Save & Reprocess"
                : isUrl
                  ? "Fetch"
                  : "Save"}
          </button>
        </div>
      </div>
    </form>
  );
}
