"use client";

import { useState, useEffect } from "react";

const STORAGE_KEY = "hypomnema-viz-hud-dismissed";

const CONTROLS = [
  ["drag", "rotate"],
  ["R-drag", "pan"],
  ["scroll", "zoom"],
  ["click", "focus"],
  ["dbl-click", "open"],
  ["esc", "back"],
] as const;

export function VizControlsHUD() {
  const [dismissed, setDismissed] = useState(true); // start hidden to avoid flash

  useEffect(() => {
    setDismissed(localStorage.getItem(STORAGE_KEY) === "true");
  }, []);

  const handleDismiss = () => {
    setDismissed(true);
    localStorage.setItem(STORAGE_KEY, "true");
  };

  const handleExpand = () => {
    setDismissed(false);
    localStorage.removeItem(STORAGE_KEY);
  };

  if (dismissed) {
    return (
      <button
        onClick={handleExpand}
        className="viz-nav-pill fixed bottom-4 right-4 z-50 rounded-md border px-2.5 py-1.5 font-mono text-[10px] text-muted/60"
        aria-label="Show controls"
      >
        ?
      </button>
    );
  }

  return (
    <div className="viz-controls-hud fixed bottom-4 right-4 z-50 rounded-md border px-3 py-2.5">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="font-mono text-[8px] uppercase tracking-widest text-muted/40">
          controls
        </span>
        <button
          onClick={handleDismiss}
          className="font-mono text-[10px] text-muted/40 hover:text-muted/70 ml-4"
          aria-label="Dismiss controls"
        >
          ×
        </button>
      </div>
      <div className="space-y-0.5">
        {CONTROLS.map(([key, action]) => (
          <div key={key} className="flex justify-between gap-4 font-mono text-[10px]">
            <span className="text-muted/60">{key}</span>
            <span className="text-muted/40">{action}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
