"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

interface StreamFooterProps {
  visibleCount: number;
}

export function StreamFooter({ visibleCount }: StreamFooterProps) {
  const [totalCount, setTotalCount] = useState<number | null>(null);

  useEffect(() => {
    api.getDocumentCount().then((r) => setTotalCount(r.total)).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- total count is stable, fetch once

  const olderCount = totalCount !== null ? totalCount - visibleCount : 0;

  if (olderCount <= 0) return null;

  return (
    <div className="stream-footer mt-8 mb-4 text-center">
      <p className="font-mono text-[11px] text-muted/40 tracking-wide">
        {olderCount} older document{olderCount !== 1 ? "s" : ""} live in your knowledge graph
      </p>
      <div className="mt-3 flex justify-center gap-6">
        <Link
          href="/search"
          className="stream-footer-link font-mono text-[11px] text-muted/40 hover:text-[var(--accent)] no-underline"
        >
          search
        </Link>
        <Link
          href="/viz"
          className="stream-footer-link font-mono text-[11px] text-muted/40 hover:text-[var(--engram)] no-underline"
        >
          explore viz
        </Link>
      </div>
    </div>
  );
}
