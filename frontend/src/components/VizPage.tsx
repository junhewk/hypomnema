"use client";

import { useVizDataCtx } from "@/hooks/useVizDataContext";
import { VizScene } from "./VizScene";

export function VizPage() {
  const { points, clusters, edges, isLoading, error } = useVizDataCtx();

  return (
    <div className="fixed inset-0 viz-viewport" data-testid="viz-page">
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
