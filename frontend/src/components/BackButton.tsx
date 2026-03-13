"use client";

import { useRouter } from "next/navigation";

export function BackButton() {
  const router = useRouter();
  return (
    <button
      onClick={() => router.back()}
      className="back-nav mb-6 inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-muted/50 transition-colors hover:text-foreground"
    >
      <span className="text-[8px]">‹</span> back
    </button>
  );
}
