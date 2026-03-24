"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import type { DocumentWithEngrams } from "@/lib/types";

export interface UseDocumentsReturn {
  documents: DocumentWithEngrams[];
  isLoading: boolean;
  error: string | null;
  refresh: () => void;
}

function hasUnprocessed(docs: DocumentWithEngrams[]): boolean {
  return docs.some((d) => {
    const processing = (d.metadata as Record<string, unknown> | null)?.processing as Record<string, unknown> | undefined;
    const status = processing?.status;
    return status === "queued" || status === "running";
  });
}

export function useDocuments(): UseDocumentsReturn {
  const [documents, setDocuments] = useState<DocumentWithEngrams[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasFetchedRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const fetchDocuments = useCallback(async () => {
    const isInitial = !hasFetchedRef.current;
    if (isInitial) setIsLoading(true);
    setError(null);
    try {
      const result = await api.listDocuments();
      setDocuments((prev) => {
        if (
          prev.length === result.length &&
          prev.every((d, i) => {
            const r = result[i];
            return (
              d.id === r.id &&
              d.processed === r.processed &&
              d.updated_at === r.updated_at
            );
          })
        ) {
          return prev;
        }
        return result;
      });
      hasFetchedRef.current = true;

      // Stop polling once everything is processed
      if (!hasUnprocessed(result)) {
        stopPolling();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      if (isInitial) setIsLoading(false);
    }
  }, [stopPolling]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  useEffect(() => {
    return stopPolling;
  }, [stopPolling]);

  const refresh = useCallback(() => {
    stopPolling();
    fetchDocuments();

    pollTimerRef.current = setInterval(() => {
      fetchDocuments();
    }, 5000);
  }, [fetchDocuments, stopPolling]);

  return {
    documents,
    isLoading,
    error,
    refresh,
  };
}
