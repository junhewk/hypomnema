"use client";

import { memo, type CSSProperties } from "react";
import Link from "next/link";
import type { Document, ScoredDocument, EngramSummary } from "@/lib/types";
import { timeAgo } from "@/lib/timeAgo";
import { SOURCE_STYLES } from "@/lib/documentStyles";
import { StatusDot } from "./StatusDot";

interface DocumentCardProps {
  document: Document | ScoredDocument;
  engrams?: EngramSummary[];
  style?: CSSProperties;
  onEdit?: (doc: Document) => void;
}

export const DocumentCard = memo(function DocumentCard({
  document: doc,
  engrams = [],
  style,
  onEdit,
}: DocumentCardProps) {
  const score = "score" in doc ? doc.score : undefined;
  const source = SOURCE_STYLES[doc.source_type];
  const displayText = doc.tidy_text ?? doc.text;
  const preview =
    displayText.length > 280 ? displayText.slice(0, 280) + "\u2026" : displayText;

  return (
    <Link
      href={`/documents/${doc.id}`}
      className="block no-underline text-inherit"
      data-testid="document-link"
    >
      <article
        className="animate-fade-up relative border-l-2 bg-surface-raised py-3 pr-4 pl-4 mb-px transition-colors hover:bg-surface"
        style={{
          borderLeftColor: source.borderColor,
          ...style,
        }}
        data-testid="document-card"
      >
        {/* processing status dot */}
        <StatusDot processed={doc.processed} className="absolute top-3 right-3" />

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
        {(doc.tidy_title ?? doc.title) && (
          <h3 className="mb-1 font-sans text-sm font-medium leading-snug">
            {doc.tidy_title ?? doc.title}
          </h3>
        )}

        {/* text preview */}
        <p className="font-mono text-xs leading-relaxed text-muted">{preview}</p>

        {/* engram pills */}
        {engrams.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {engrams.slice(0, 3).map((eg) => (
              <Link
                key={eg.id}
                href={`/engrams/${eg.id}`}
                onClick={(e) => e.stopPropagation()}
                className="engram-pill rounded-sm bg-[var(--engram)]/8 px-1.5 py-0.5 font-mono text-[10px] text-[var(--engram)] no-underline"
              >
                {eg.canonical_name}
              </Link>
            ))}
            {engrams.length > 3 && (
              <span className="rounded-sm bg-[var(--engram)]/5 px-1.5 py-0.5 font-mono text-[10px] text-[var(--engram)]/60">
                +{engrams.length - 3}
              </span>
            )}
          </div>
        )}

        {/* timestamp + score */}
        <div className="mt-2 flex items-center gap-2">
          <time
            className="font-mono text-[10px] text-muted/60"
            dateTime={doc.created_at}
          >
            {timeAgo(doc.created_at)}
          </time>
          {score !== undefined && (
            <span
              className="rounded-sm px-1.5 py-0.5 font-mono text-[10px] text-[var(--accent)] bg-[var(--accent)]/10"
              data-testid="score-badge"
            >
              {(score * 100).toFixed(0)}% match
            </span>
          )}
          {onEdit && doc.source_type === "scribble" && (
            <button
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onEdit(doc);
              }}
              className="continue-btn ml-auto font-mono text-[10px] text-muted/50 transition-colors hover:text-[var(--accent)]"
              data-testid="continue-button"
            >
              continue
            </button>
          )}
        </div>
      </article>
    </Link>
  );
});
