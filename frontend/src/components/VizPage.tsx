"use client";

import Link from "next/link";
import { useVizData } from "@/hooks/useVizData";
import { VizScene } from "./VizScene";

export function VizPage() {
  const { points, clusters, edges, isLoading, error } = useVizData();

  return (
    <div className="fixed inset-0 viz-viewport" data-testid="viz-page">
      <nav className="absolute top-4 left-4 z-10 flex gap-2">
        <Link
          href="/"
          className="viz-nav-pill rounded-full border px-3 py-0.5 font-mono text-[10px] text-muted no-underline"
          data-testid="stream-link"
        >
          ← stream
        </Link>
        <Link
          href="/search"
          className="viz-nav-pill rounded-full border px-3 py-0.5 font-mono text-[10px] text-muted no-underline"
          data-testid="search-link"
        >
          search
        </Link>
      </nav>

      {isLoading && (
        <div className="flex h-full items-center justify-center">
          <div className="text-center">
            <p className="font-mono text-[10px] tracking-[0.3em] uppercase text-muted/60 animate-pulse-dot">
              Loading visualization…
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="flex h-full items-center justify-center">
          <p
            className="font-mono text-xs text-red-400/80"
            data-testid="error-message"
          >
            {error}
          </p>
        </div>
      )}

      {!isLoading && !error && points.length === 0 && (
        <div className="flex h-full items-center justify-center">
          <p
            className="font-mono text-[10px] tracking-wide text-muted/50"
            data-testid="empty-state"
          >
            No projection data available.
          </p>
        </div>
      )}

      {!isLoading && !error && points.length > 0 && (
        <div className="h-full w-full animate-viz-in">
          <VizScene points={points} clusters={clusters} edges={edges} />
        </div>
      )}
    </div>
  );
}
