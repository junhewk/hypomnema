"use client";

import { useMemo } from "react";
import { useDocument } from "@/hooks/useDocument";
import { useEngrams } from "@/hooks/useEngrams";
import { SOURCE_STYLES, STATUS_COLOR, STATUS_ANIM } from "@/lib/documentStyles";
import { timeAgo } from "@/lib/timeAgo";
import { NetworkPanel } from "./NetworkPanel";

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
              <div
                className={`h-1.5 w-1.5 rounded-full ${STATUS_COLOR[doc.processed] ?? "bg-gray-400"} ${STATUS_ANIM[doc.processed] ?? ""}`}
                data-testid="status-dot"
              />
              {doc.mime_type && (
                <span className="font-mono text-[10px] text-muted">
                  {doc.mime_type}
                </span>
              )}
            </div>

            {doc.title && (
              <h1 className="mb-1 font-sans text-lg font-medium">
                {doc.title}
              </h1>
            )}

            <time
              className="font-mono text-[10px] text-muted/60"
              dateTime={doc.created_at}
            >
              {timeAgo(doc.created_at)}
            </time>
          </div>

          <div className="mb-8" data-testid="document-text">
            <p className="font-mono text-sm leading-relaxed whitespace-pre-wrap">
              {doc.text}
            </p>
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
