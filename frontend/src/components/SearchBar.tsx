"use client";

import { memo } from "react";
import type { SearchMode } from "@/lib/types";

interface SearchBarProps {
  query: string;
  mode: SearchMode;
  onQueryChange: (query: string) => void;
  onModeChange: (mode: SearchMode) => void;
}

export const SearchBar = memo(function SearchBar({
  query,
  mode,
  onQueryChange,
  onModeChange,
}: SearchBarProps) {
  return (
    <div className="mb-8 rounded-lg border border-border bg-surface-raised p-4 transition-shadow focus-within:shadow-[0_0_0_1px_var(--border-focus)]">
      <div className="flex items-center gap-3">
        <span className="font-mono text-xs text-muted/40 select-none">/</span>
        <input
          type="text"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Search documents or knowledge…"
          className="w-full bg-transparent font-mono text-sm outline-none placeholder:text-muted/40"
          data-testid="search-input"
        />
      </div>
      <div className="mt-3 flex gap-1.5 border-t border-border pt-3">
        <button
          onClick={() => onModeChange("documents")}
          className={`rounded-full px-3 py-1 font-mono text-[10px] uppercase tracking-wider transition-colors ${
            mode === "documents"
              ? "bg-foreground text-background"
              : "border border-border text-muted hover:border-border-focus hover:text-foreground"
          }`}
          data-testid="mode-documents"
        >
          Documents
        </button>
        <button
          onClick={() => onModeChange("knowledge")}
          className={`rounded-full px-3 py-1 font-mono text-[10px] uppercase tracking-wider transition-colors ${
            mode === "knowledge"
              ? "bg-foreground text-background"
              : "border border-border text-muted hover:border-border-focus hover:text-foreground"
          }`}
          data-testid="mode-knowledge"
        >
          Knowledge
        </button>
      </div>
    </div>
  );
});
