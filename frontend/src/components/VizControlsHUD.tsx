"use client";

import { useState, useEffect } from "react";
import type { InputDevice } from "@/hooks/useInputDevice";

const STORAGE_KEY = "hypomnema-viz-hud-dismissed";

function getNavControls(device: InputDevice, modKey: string): [string, string][] {
  if (device === "touch") {
    return [
      ["drag", "pan"],
      ["2-finger rotate", "orbit"],
      ["pinch", "zoom"],
    ];
  }
  return [
    ["drag", "pan"],
    ["right-click drag", "orbit"],
    ["scroll", "zoom"],
    [`${modKey} + scroll`, "spread"],
  ];
}

function getNodeControls(device: InputDevice): [string, string][] {
  if (device === "touch") {
    return [
      ["drag", "move"],
      ["long-press", "focus"],
      ["double-tap", "open"],
      ["tap empty", "unfocus"],
    ];
  }
  return [
    ["drag", "move"],
    ["shift + drag", "push / pull"],
    ["click", "focus"],
    ["double-click", "open"],
    ["esc", "unfocus"],
  ];
}

function ControlRow({ keyLabel, action }: { keyLabel: string; action: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <kbd className="viz-hud-key font-mono text-[11px] text-muted/80 leading-none">
        {keyLabel}
      </kbd>
      <span className="font-mono text-[11px] text-muted/60 leading-none">{action}</span>
    </div>
  );
}

function ControlGroup({ label, controls }: { label: string; controls: [string, string][] }) {
  return (
    <div>
      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted/50 mb-1">
        {label}
      </p>
      <div className="space-y-1">
        {controls.map(([key, action]) => (
          <ControlRow key={key} keyLabel={key} action={action} />
        ))}
      </div>
    </div>
  );
}

const SPREAD_MIN = 0.3;
const SPREAD_MAX = 3.0;

interface VizControlsHUDProps {
  autoOrbit?: boolean;
  onToggleAutoOrbit?: () => void;
  device?: InputDevice;
  modKey?: string;
  explodeFactor?: number;
  onSpreadChange?: (factor: number) => void;
  spreadStep?: number;
}

export function VizControlsHUD({
  autoOrbit = false,
  onToggleAutoOrbit,
  device = "pointer",
  modKey = "alt",
  explodeFactor = 1.0,
  onSpreadChange,
  spreadStep = 0.15,
}: VizControlsHUDProps) {
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
        className="viz-nav-pill absolute bottom-4 right-4 z-50 rounded-md border px-2.5 py-1.5 font-mono text-[11px] text-muted/70"
        aria-label="Show controls"
      >
        ?
      </button>
    );
  }

  const navControls = getNavControls(device, modKey);
  const nodeControls = getNodeControls(device);

  return (
    <div className="viz-controls-hud absolute bottom-4 right-4 z-50 rounded-md border px-3 py-2.5 min-w-[180px]">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted/50">
          controls
        </span>
        <button
          onClick={handleDismiss}
          className="font-mono text-[11px] text-muted/50 hover:text-muted/70 ml-4 leading-none"
          aria-label="Dismiss controls"
        >
          ×
        </button>
      </div>
      <div className="space-y-2">
        <ControlGroup label="navigate" controls={navControls} />
        {device === "touch" && onSpreadChange && (
          <div className="flex items-center justify-between gap-2 mt-1">
            <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted/50">
              spread
            </span>
            <div className="viz-hud-spread-group">
              <button
                onClick={() => onSpreadChange(explodeFactor - spreadStep)}
                disabled={explodeFactor <= SPREAD_MIN}
                className="viz-hud-spread-btn font-mono text-[13px] text-muted/80 leading-none"
                aria-label="Decrease spread"
              >
                −
              </button>
              <button
                onClick={() => onSpreadChange(explodeFactor + spreadStep)}
                disabled={explodeFactor >= SPREAD_MAX}
                className="viz-hud-spread-btn font-mono text-[13px] text-muted/80 leading-none"
                aria-label="Increase spread"
              >
                +
              </button>
            </div>
          </div>
        )}
        <div className="viz-hud-divider" />
        <ControlGroup label="nodes" controls={nodeControls} />
      </div>
      {onToggleAutoOrbit && (
        <>
          <div className="viz-hud-divider mt-2" />
          <button
            onClick={onToggleAutoOrbit}
            className="mt-2 w-full rounded-md px-3 py-1 font-mono text-[11px] text-muted/70 hover:text-muted/90 border border-transparent hover:border-muted/20 transition-colors"
          >
            {autoOrbit ? "stop" : "orbit"}
          </button>
        </>
      )}
    </div>
  );
}
