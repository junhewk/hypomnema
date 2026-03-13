"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useVizDataCtx } from "@/hooks/useVizDataContext";
import { VizScene } from "./VizScene";

export function VizPage() {
  const router = useRouter();
  const { points, clusters, edges, isLoading, error } = useVizDataCtx();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") router.push("/");
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [router]);

  return (
    <div className="fixed inset-0 viz-viewport" data-testid="viz-page">
      <button
        onClick={() => router.push("/")}
        className="viz-nav-pill fixed top-4 left-4 z-50 rounded-md border px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted/60"
        aria-label="Back to stream"
      >
        <span className="mr-1 text-[8px]">‹</span>
        back
      </button>

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
