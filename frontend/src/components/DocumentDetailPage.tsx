"use client";

import { useMemo } from "react";
import { useDocument } from "@/hooks/useDocument";
import { useEngrams } from "@/hooks/useEngrams";
import { SOURCE_STYLES } from "@/lib/documentStyles";
import { timeAgo } from "@/lib/timeAgo";
import { BackButton } from "./BackButton";
import { NetworkPanel } from "./NetworkPanel";
import { StatusDot } from "./StatusDot";

interface DocumentDetailPageProps {
  id: string;
}

export function DocumentDetailPage({ id }: DocumentDetailPageProps) {
  const { document: doc, isLoading, error } = useDocument(id);
  const engramIds = useMemo(
    () => doc?.engrams.map((e) => e.id) ?? [],
    [doc],
  );
  const { engrams: engramDetails, isLoading: engramsLoading } =
    useEngrams(engramIds);
  const documentEngramIds = useMemo(
    () => new Set(engramIds),
    [engramIds],
  );

  const source = doc ? SOURCE_STYLES[doc.source_type] : null;

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <BackButton />

      {isLoading && (
        <p className="animate-pulse-dot font-mono text-sm text-muted">
          Loading…
        </p>
      )}

      {error && (
        <p className="font-mono text-sm text-red-500" data-testid="error-message">
          {error}
        </p>
      )}

      {doc && source && (
        <article
          className="animate-fade-up border-l-2 pl-4"
          style={{ borderLeftColor: source.borderColor }}
        >
          <div className="mb-4">
            <div className="mb-2 flex items-center gap-2">
              <span
                className={`rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider ${source.className}`}
              >
                {source.label}
              </span>
              <StatusDot processed={doc.processed} />
              {doc.mime_type && (
                <span className="font-mono text-[10px] text-muted">
                  {doc.mime_type}
                </span>
              )}
            </div>

            <h1 className="mb-1 font-sans text-lg font-medium">
              {doc.tidy_title ?? doc.title ?? "Untitled"}
            </h1>

            <time
              className="font-mono text-[10px] text-muted/60"
              dateTime={doc.created_at}
            >
              {timeAgo(doc.created_at)}
            </time>
          </div>

          <div className="mb-8" data-testid="document-text">
            {doc.tidy_text ? (
              <>
                <div className="tidy-surface">
                  <p className="font-mono text-sm leading-relaxed whitespace-pre-wrap">
                    {doc.tidy_text}
                  </p>
                </div>
                <details className="mt-6 border-t border-border/50 pt-4">
                  <summary className="raw-text-toggle font-mono text-[10px] uppercase tracking-wider text-muted/40 hover:text-muted/70">
                    Original text
                  </summary>
                  <p className="mt-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-muted/60">
                    {doc.text}
                  </p>
                </details>
              </>
            ) : (
              <p className="font-mono text-sm leading-relaxed whitespace-pre-wrap">
                {doc.text}
              </p>
            )}
          </div>

          <div className="border-t border-border pt-6">
            <NetworkPanel
              documentEngramIds={documentEngramIds}
              engramDetails={engramDetails}
              isLoading={engramsLoading}
            />
          </div>
        </article>
      )}
    </div>
  );
}
