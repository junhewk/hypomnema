"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useVizDataCtx } from "@/hooks/useVizDataContext";
import { useInputDevice } from "@/hooks/useInputDevice";
import { VizScene } from "./VizScene";
import { VizControlsHUD } from "./VizControlsHUD";
import type { ProjectionPoint } from "@/lib/types";

const SPREAD_MIN = 0.3;
const SPREAD_MAX = 3.0;
const SPREAD_STEP = 0.15;

export function VizPage() {
  const router = useRouter();
  const { points, clusters, edges, isLoading, error } = useVizDataCtx();
  const [focusedNode, setFocusedNode] = useState<ProjectionPoint | null>(null);
  const [autoOrbit, setAutoOrbit] = useState(false);
  const [explodeFactor, setExplodeFactor] = useState(1.0);
  const { device, modKey } = useInputDevice();

  const handleNavigateNode = useCallback(
    (engramId: string) => {
      router.push(`/engrams/${engramId}`);
    },
    [router],
  );

  const handleToggleAutoOrbit = useCallback(() => {
    setAutoOrbit((prev) => !prev);
  }, []);

  const handleAutoOrbitStop = useCallback(() => {
    setAutoOrbit(false);
  }, []);

  const handleSpreadChange = useCallback((newFactor: number) => {
    setExplodeFactor(Math.max(SPREAD_MIN, Math.min(SPREAD_MAX, newFactor)));
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (focusedNode) {
          setFocusedNode(null);
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [focusedNode]);

  return (
    <div className="h-full w-full relative viz-viewport" data-testid="viz-page">
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
          <VizScene
            points={points}
            clusters={clusters}
            edges={edges}
            focusedNode={focusedNode}
            onFocusNode={setFocusedNode}
            onNavigateNode={handleNavigateNode}
            autoOrbit={autoOrbit}
            onAutoOrbitStop={handleAutoOrbitStop}
            explodeFactor={explodeFactor}
            onSpreadChange={handleSpreadChange}
            device={device}
          />
        </div>
      )}

      <VizControlsHUD
        autoOrbit={autoOrbit}
        onToggleAutoOrbit={handleToggleAutoOrbit}
        device={device}
        modKey={modKey}
        explodeFactor={explodeFactor}
        onSpreadChange={handleSpreadChange}
        spreadStep={SPREAD_STEP}
      />
    </div>
  );
}
