"use client";

import { useState, useEffect, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import type { SearchMode } from "@/lib/types";
import { useSearch } from "@/hooks/useSearch";
import { useEngrams } from "@/hooks/useEngrams";
import { SearchBar } from "./SearchBar";
import { DocumentCard } from "./DocumentCard";
import { EngramBadge } from "./EngramBadge";
import { formatPredicate } from "@/lib/predicates";
import { resolveEngram } from "@/lib/resolveEngram";

export function SearchPage() {
  const searchParams = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const [mode, setMode] = useState<SearchMode>(
    (searchParams.get("mode") as SearchMode) ?? "documents",
  );

  useEffect(() => {
    const url = new URL(window.location.href);
    if (query) url.searchParams.set("q", query);
    else url.searchParams.delete("q");
    url.searchParams.set("mode", mode);
    history.replaceState(null, "", url.toString());
  }, [query, mode]);

  const { result, isLoading, error } = useSearch(query, mode);

  const edgeEngramIds = useMemo(() => {
    if (!result || result.mode !== "knowledge") return [];
    const ids = new Set<string>();
    for (const edge of result.results) {
      ids.add(edge.source_engram_id);
      ids.add(edge.target_engram_id);
    }
    return Array.from(ids);
  }, [result]);

  const { engrams: engramDetails } = useEngrams(edgeEngramIds);

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <SearchBar
        query={query}
        mode={mode}
        onQueryChange={setQuery}
        onModeChange={setMode}
      />

      {isLoading && (
        <p className="animate-pulse-dot font-mono text-xs text-muted">
          Searching…
        </p>
      )}

      {error && (
        <p className="font-mono text-sm text-red-500" data-testid="error-message">
          {error}
        </p>
      )}

      {!query.trim() && !isLoading && !error && (
        <div className="py-12 text-center">
          <p className="font-mono text-xs text-muted">Type to search.</p>
          <p className="mt-2 font-mono text-[10px] text-muted/40">
            Search across documents or explore the knowledge graph.
          </p>
        </div>
      )}

      {result && result.results.length === 0 && (
        <div className="py-12 text-center">
          <p className="font-mono text-xs text-muted">No results found.</p>
        </div>
      )}

      {result && result.mode === "documents" && result.results.length > 0 && (
        <section>
          {result.results.map((doc, i) => (
            <DocumentCard
              key={doc.id}
              document={doc}
              style={{ animationDelay: `${i * 50}ms` }}
            />
          ))}
        </section>
      )}

      {result && result.mode === "knowledge" && result.results.length > 0 && (
        <section className="space-y-px" data-testid="knowledge-results">
          {result.results.map((edge, i) => (
            <div
              key={edge.id}
              className="animate-fade-up flex items-center gap-2 border-l-2 bg-surface-raised py-2.5 pr-4 pl-4 font-mono text-xs transition-colors hover:bg-surface"
              style={{
                borderLeftColor: "var(--engram)",
                animationDelay: `${i * 50}ms`,
              }}
            >
              <EngramBadge engram={resolveEngram(edge.source_engram_id, engramDetails)} />
              <span className="text-muted/60 text-[10px] uppercase tracking-wider">
                {formatPredicate(edge.predicate)}
              </span>
              <span className="text-muted/40">→</span>
              <EngramBadge engram={resolveEngram(edge.target_engram_id, engramDetails)} />
              <span className="ml-auto font-mono text-[10px] text-muted/40">
                {Math.round(edge.confidence * 100)}%
              </span>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
