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
      <p className="font-mono text-[13px] font-semibold leading-tight">
        {name}
      </p>
      {clusterLabel != null && (
        <p className="font-mono text-[11px] mt-1 tracking-wide viz-tooltip-cluster">
          {clusterLabel}
        </p>
      )}
    </div>
  );
});
