"use client";

import { useMemo } from "react";
import { useEngram } from "@/hooks/useEngram";
import { useEngrams } from "@/hooks/useEngrams";
import { NetworkPanel } from "./NetworkPanel";
import { DocumentCard } from "./DocumentCard";
import { timeAgo } from "@/lib/timeAgo";

interface EngramDetailPageProps {
  id: string;
}

export function EngramDetailPage({ id }: EngramDetailPageProps) {
  const { engram, clusterDocs, isLoading, error } = useEngram(id);

  const neighborIds = useMemo(() => {
    if (!engram) return [];
    const ids = new Set<string>();
    for (const edge of engram.edges) {
      ids.add(edge.source_engram_id);
      ids.add(edge.target_engram_id);
    }
    ids.delete(id);
    return Array.from(ids);
  }, [engram, id]);

  const { engrams: neighborDetails, isLoading: neighborsLoading } =
    useEngrams(neighborIds);

  const allDetails = useMemo(() => {
    const map = new Map(neighborDetails);
    if (engram) map.set(id, engram);
    return map;
  }, [neighborDetails, engram, id]);

  const engramIdSet = useMemo(() => new Set([id]), [id]);

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

      {engram && (
        <article
          className="animate-fade-up border-l-2 pl-4"
          style={{ borderLeftColor: "var(--engram)" }}
        >
          <div className="mb-1.5 flex items-center gap-2">
            <span className="rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider text-[var(--engram)] bg-[var(--engram)]/10">
              engram
            </span>
            <span className="font-mono text-[10px] text-muted/40">
              {engram.concept_hash.slice(0, 12)}
            </span>
          </div>

          <h1 className="mb-2 font-mono text-lg font-bold">
            {engram.canonical_name}
          </h1>
          {engram.description && (
            <p className="mb-4 font-mono text-sm leading-relaxed text-muted">
              {engram.description}
            </p>
          )}
          <time
            className="mb-8 block font-mono text-[10px] text-muted/60"
            dateTime={engram.created_at}
          >
            {timeAgo(engram.created_at)}
          </time>

          <div className="border-t border-border pt-6 mb-8">
            <NetworkPanel
              documentEngramIds={engramIdSet}
              engramDetails={allDetails}
              isLoading={neighborsLoading}
            />
          </div>

          {clusterDocs.length > 0 && (
            <div className="border-t border-border pt-6">
              <h2 className="mb-4 font-mono text-xs uppercase tracking-wider text-muted">
                Documents
              </h2>
              {clusterDocs.map((doc, i) => (
                <DocumentCard
                  key={doc.id}
                  document={doc}
                  style={{ animationDelay: `${i * 50}ms` }}
                />
              ))}
            </div>
          )}
        </article>
      )}
    </div>
  );
}
