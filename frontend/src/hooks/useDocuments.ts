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

export function useDocuments(): UseDocumentsReturn {
  const [documents, setDocuments] = useState<DocumentWithEngrams[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasFetchedRef = useRef(false);

  const fetchDocuments = useCallback(async () => {
    const isInitial = !hasFetchedRef.current;
    if (isInitial) setIsLoading(true);
    setError(null);
    try {
      const result = await api.listDocuments();
      setDocuments((prev) => {
        if (
          prev.length === result.length &&
          prev.every(
            (d, i) =>
              d.id === result[i].id && d.processed === result[i].processed,
          )
        ) {
          return prev;
        }
        return result;
      });
      hasFetchedRef.current = true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      if (isInitial) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
  }, []);

  useEffect(() => {
    return stopPolling;
  }, [stopPolling]);

  const refresh = useCallback(() => {
    stopPolling();
    fetchDocuments();

    pollTimerRef.current = setInterval(() => {
      fetchDocuments();
    }, 5000);

    pollTimeoutRef.current = setTimeout(() => {
      stopPolling();
    }, 30000);
  }, [fetchDocuments, stopPolling]);

  return {
    documents,
    isLoading,
    error,
    refresh,
  };
}
