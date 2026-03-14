"use client";

import { useState, useEffect } from "react";

const STORAGE_KEY = "hypomnema-viz-hud-dismissed";

const NAV_CONTROLS = [
  ["drag", "pan"],
  ["R-drag", "orbit"],
  ["scroll", "zoom"],
  ["ctrl scroll", "spread"],
] as const;

const NODE_CONTROLS = [
  ["drag node", "move"],
  ["shift drag", "push / pull"],
  ["click", "focus"],
  ["dbl-click", "open"],
  ["esc", "back"],
] as const;

function ControlRow({ keyLabel, action }: { keyLabel: string; action: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <kbd className="viz-hud-key font-mono text-[9px] text-muted/70 leading-none">
        {keyLabel}
      </kbd>
      <span className="font-mono text-[9px] text-muted/40 leading-none">{action}</span>
    </div>
  );
}

function ControlGroup({ label, controls }: { label: string; controls: ReadonlyArray<readonly [string, string]> }) {
  return (
    <div>
      <p className="font-mono text-[7px] uppercase tracking-[0.2em] text-muted/30 mb-1">
        {label}
      </p>
      <div className="space-y-[3px]">
        {controls.map(([key, action]) => (
          <ControlRow key={key} keyLabel={key} action={action} />
        ))}
      </div>
    </div>
  );
}

interface VizControlsHUDProps {
  autoOrbit?: boolean;
  onToggleAutoOrbit?: () => void;
}

export function VizControlsHUD({ autoOrbit = false, onToggleAutoOrbit }: VizControlsHUDProps) {
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
        className="viz-nav-pill absolute bottom-4 right-4 z-50 rounded-md border px-2.5 py-1.5 font-mono text-[10px] text-muted/60"
        aria-label="Show controls"
      >
        ?
      </button>
    );
  }

  return (
    <div className="viz-controls-hud absolute bottom-4 right-4 z-50 rounded-md border px-3 py-2.5">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-[7px] uppercase tracking-[0.2em] text-muted/35">
          controls
        </span>
        <button
          onClick={handleDismiss}
          className="font-mono text-[10px] text-muted/30 hover:text-muted/60 ml-4 leading-none"
          aria-label="Dismiss controls"
        >
          ×
        </button>
      </div>
      <div className="space-y-2">
        <ControlGroup label="navigate" controls={NAV_CONTROLS} />
        <div className="viz-hud-divider" />
        <ControlGroup label="nodes" controls={NODE_CONTROLS} />
      </div>
      {onToggleAutoOrbit && (
        <>
          <div className="viz-hud-divider mt-2" />
          <button
            onClick={onToggleAutoOrbit}
            className="mt-2 w-full rounded-md px-3 py-1 font-mono text-[9px] text-muted/60 hover:text-muted/80 border border-transparent hover:border-muted/20 transition-colors"
          >
            {autoOrbit ? "stop" : "orbit"}
          </button>
        </>
      )}
    </div>
  );
}
