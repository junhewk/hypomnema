"use client";

import { memo } from "react";
import Link from "next/link";
import type { Engram } from "@/lib/types";

interface EngramBadgeProps {
  engram: Pick<Engram, "id" | "canonical_name">;
  dimmed?: boolean;
}

export const EngramBadge = memo(function EngramBadge({
  engram,
  dimmed = false,
}: EngramBadgeProps) {
  return (
    <Link
      href={`/engrams/${engram.id}`}
      className={`inline-block rounded-full px-2 py-0.5 font-mono text-[11px] no-underline transition-colors text-[var(--engram)] bg-[var(--engram)]/10 hover:bg-[var(--engram)]/20 ${dimmed ? "opacity-50" : ""}`}
      data-testid="engram-badge"
    >
      {engram.canonical_name}
    </Link>
  );
});
