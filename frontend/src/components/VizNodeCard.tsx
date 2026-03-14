import { memo } from "react";

interface VizNodeCardProps {
  name: string;
  clusterLabel: string | null;
  onOpen: () => void;
}

export const VizNodeCard = memo(function VizNodeCard({
  name,
  clusterLabel,
  onOpen,
}: VizNodeCardProps) {
  return (
    <div
      data-testid="viz-node-card"
      className="viz-tooltip rounded-md px-3 py-2 min-w-[140px]"
    >
      <p className="font-mono text-[13px] font-semibold leading-tight">
        {name}
      </p>
      {clusterLabel != null && (
        <p className="font-mono text-[11px] mt-1 tracking-wide viz-tooltip-cluster">
          {clusterLabel}
        </p>
      )}
      <button
        onClick={onOpen}
        className="mt-2 font-mono text-[11px] text-accent hover:text-accent/80 tracking-wide uppercase"
      >
        open →
      </button>
    </div>
  );
});
