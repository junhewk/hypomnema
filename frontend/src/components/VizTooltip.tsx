import { memo } from "react";

interface VizTooltipProps {
  name: string;
  clusterLabel: string | null;
}

export const VizTooltip = memo(function VizTooltip({
  name,
  clusterLabel,
}: VizTooltipProps) {
  return (
    <div
      data-testid="viz-tooltip"
      className="viz-tooltip rounded-md px-3 py-2 pointer-events-none whitespace-nowrap"
    >
      <p className="font-mono text-[11px] font-semibold text-foreground leading-tight">
        {name}
      </p>
      {clusterLabel != null && (
        <p className="font-mono text-[9px] text-muted mt-1 tracking-wide">
          {clusterLabel}
        </p>
      )}
    </div>
  );
});
