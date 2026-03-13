import { STATUS_COLOR, STATUS_ANIM, STATUS_LABEL } from "@/lib/documentStyles";

interface StatusDotProps {
  processed: number;
  className?: string;
}

export function StatusDot({ processed, className = "" }: StatusDotProps) {
  return (
    <div
      className={`status-dot h-1.5 w-1.5 rounded-full ${STATUS_COLOR[processed] ?? "bg-gray-400"} ${STATUS_ANIM[processed] ?? ""} ${className}`}
      data-testid="status-dot"
      data-label={STATUS_LABEL[processed] ?? "Unknown"}
      aria-label={STATUS_LABEL[processed] ?? `processing status ${processed}`}
    />
  );
}
