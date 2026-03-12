"use client";

import { useMemo } from "react";
import type { EngramDetail, Edge, Predicate } from "@/lib/types";
import { EngramBadge } from "./EngramBadge";
import { formatPredicate } from "@/lib/predicates";
import { resolveEngram } from "@/lib/resolveEngram";

interface NetworkPanelProps {
  documentEngramIds: Set<string>;
  engramDetails: Map<string, EngramDetail>;
  isLoading: boolean;
}

export function NetworkPanel({
  documentEngramIds,
  engramDetails,
  isLoading,
}: NetworkPanelProps) {
  const { documentEngrams, grouped } = useMemo(() => {
    // Collect and deduplicate all edges
    const seenEdges = new Map<string, Edge>();
    for (const detail of engramDetails.values()) {
      for (const edge of detail.edges) {
        if (!seenEdges.has(edge.id)) {
          seenEdges.set(edge.id, edge);
        }
      }
    }

    // Group edges by predicate
    const g = new Map<Predicate, Edge[]>();
    for (const edge of seenEdges.values()) {
      const group = g.get(edge.predicate) ?? [];
      group.push(edge);
      g.set(edge.predicate, group);
    }

    const engrams = Array.from(documentEngramIds)
      .map((id) => engramDetails.get(id))
      .filter(Boolean) as EngramDetail[];

    return { documentEngrams: engrams, grouped: g };
  }, [documentEngramIds, engramDetails]);

  return (
    <section data-testid="network-panel">
      <h2 className="mb-4 font-mono text-xs uppercase tracking-wider text-muted">
        Network
      </h2>

      {isLoading && (
        <p className="animate-pulse-dot font-mono text-xs text-muted">
          Loading network…
        </p>
      )}

      {!isLoading && documentEngramIds.size === 0 && (
        <p className="font-mono text-xs text-muted">
          No engrams extracted yet.
        </p>
      )}

      {!isLoading && documentEngrams.length > 0 && (
        <>
          <div className="mb-4 flex flex-wrap gap-1.5">
            {documentEngrams.map((engram) => (
              <EngramBadge key={engram.id} engram={engram} />
            ))}
          </div>

          {Array.from(grouped.entries()).map(([predicate, edges]) => (
            <div key={predicate} className="mb-3">
              <h3 className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-muted">
                {formatPredicate(predicate)}
              </h3>
              <div className="space-y-1.5">
                {edges.map((edge) => (
                  <div
                    key={edge.id}
                    className="flex items-center gap-1.5 font-mono text-xs"
                  >
                    <EngramBadge
                      engram={resolveEngram(edge.source_engram_id, engramDetails)}
                      dimmed={!documentEngramIds.has(edge.source_engram_id)}
                    />
                    <span className="text-muted">→</span>
                    <EngramBadge
                      engram={resolveEngram(edge.target_engram_id, engramDetails)}
                      dimmed={!documentEngramIds.has(edge.target_engram_id)}
                    />
                    <span className="text-muted/60 text-[10px]">
                      {Math.round(edge.confidence * 100)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </>
      )}
    </section>
  );
}
