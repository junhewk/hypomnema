"use client";

import { memo, type CSSProperties } from "react";
import type { Document, SourceType } from "@/lib/types";
import { timeAgo } from "@/lib/timeAgo";

interface DocumentCardProps {
  document: Document;
  style?: CSSProperties;
}

const SOURCE_STYLES: Record<
  SourceType,
  { label: string; className: string; borderColor: string }
> = {
  scribble: {
    label: "scribble",
    className:
      "text-[var(--source-scribble)] bg-[var(--source-scribble)]/10",
    borderColor: "var(--source-scribble)",
  },
  file: {
    label: "file",
    className:
      "text-[var(--source-file)] bg-[var(--source-file)]/10",
    borderColor: "var(--source-file)",
  },
  feed: {
    label: "feed",
    className:
      "text-[var(--source-feed)] bg-[var(--source-feed)]/10",
    borderColor: "var(--source-feed)",
  },
};

const STATUS_COLOR: Record<number, string> = {
  0: "bg-amber-400",
  1: "bg-blue-400",
  2: "bg-green-400",
};

const STATUS_ANIM: Record<number, string> = {
  0: "animate-pulse-dot",
  1: "animate-pulse-dot",
  2: "",
};

export const DocumentCard = memo(function DocumentCard({
  document: doc,
  style,
}: DocumentCardProps) {
  const source = SOURCE_STYLES[doc.source_type];
  const preview =
    doc.text.length > 280 ? doc.text.slice(0, 280) + "\u2026" : doc.text;

  return (
    <article
      className="animate-fade-up relative border-l-2 bg-surface-raised py-3 pr-4 pl-4 mb-px transition-colors hover:bg-surface"
      style={{
        borderLeftColor: source.borderColor,
        ...style,
      }}
      data-testid="document-card"
    >
      {/* processing status dot */}
      <div
        className={`absolute top-3 right-3 h-1.5 w-1.5 rounded-full ${STATUS_COLOR[doc.processed] ?? "bg-gray-400"} ${STATUS_ANIM[doc.processed] ?? ""}`}
        data-testid="status-dot"
        aria-label={`processing status ${doc.processed}`}
      />

      {/* header row: badge + mime */}
      <div className="mb-1.5 flex items-center gap-2">
        <span
          className={`rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider ${source.className}`}
        >
          {source.label}
        </span>
        {doc.mime_type && (
          <span className="font-mono text-[10px] text-muted">
            {doc.mime_type}
          </span>
        )}
      </div>

      {/* title */}
      {doc.title && (
        <h3 className="mb-1 font-sans text-sm font-medium leading-snug">
          {doc.title}
        </h3>
      )}

      {/* text preview */}
      <p className="font-mono text-xs leading-relaxed text-muted">{preview}</p>

      {/* timestamp */}
      <time
        className="mt-2 block font-mono text-[10px] text-muted/60"
        dateTime={doc.created_at}
      >
        {timeAgo(doc.created_at)}
      </time>
    </article>
  );
});
