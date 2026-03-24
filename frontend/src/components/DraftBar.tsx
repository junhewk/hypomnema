"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { readLocalStorage, writeLocalStorage } from "@/lib/storage";
import { timeAgo } from "@/lib/timeAgo";
import type { Document } from "@/lib/types";

const COLLAPSED_KEY = "hypomnema-drafts-collapsed";

interface DraftBarProps {
  onEdit: (doc: Document) => void;
  refreshSignal: number;
}

export function DraftBar({ onEdit, refreshSignal }: DraftBarProps) {
  const [drafts, setDrafts] = useState<Document[]>([]);
  const [collapsed, setCollapsed] = useState(() => {
    return readLocalStorage(COLLAPSED_KEY) !== "false";
  });

  const fetchDrafts = useCallback(async () => {
    try {
      const result = await api.listDrafts();
      setDrafts(result);
    } catch {
      // silently ignore
    }
  }, []);

  useEffect(() => {
    fetchDrafts();
  }, [fetchDrafts, refreshSignal]);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      writeLocalStorage(COLLAPSED_KEY, String(next));
      return next;
    });
  }

  if (drafts.length === 0) return null;

  return (
    <div className="draft-bar mb-6 rounded-r-sm pl-3 py-2">
      <button
        onClick={toggleCollapsed}
        data-open={!collapsed}
        className="draft-bar-toggle w-full text-left font-mono text-[11px] text-muted/50 hover:text-muted py-0.5"
      >
        {drafts.length} draft{drafts.length !== 1 ? "s" : ""} held
      </button>

      {!collapsed && (
        <div className="draft-items-enter mt-1.5 space-y-px overflow-hidden">
          {drafts.map((draft) => (
            <button
              key={draft.id}
              onClick={() => onEdit(draft)}
              className="draft-item w-full text-left rounded-r-sm px-3 py-1.5 font-mono text-[11px] text-muted hover:text-foreground"
            >
              <span className="italic">{draft.title || "untitled"}</span>
              <span className="ml-2 text-muted/30">{timeAgo(draft.updated_at)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
