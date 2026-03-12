"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import type { Document } from "@/lib/types";

const PAGE_SIZE = 20;

export interface UseDocumentsReturn {
  documents: Document[];
  total: number;
  isLoading: boolean;
  error: string | null;
  hasMore: boolean;
  loadMore: () => void;
  refresh: () => void;
}

export function useDocuments(): UseDocumentsReturn {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const offsetRef = useRef(0);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchPage = useCallback(
    async (offset: number, replace: boolean) => {
      setIsLoading(true);
      setError(null);
      try {
        const result = await api.listDocuments(offset, PAGE_SIZE);
        setTotal(result.total);
        if (replace) {
          setDocuments((prev) => {
            if (
              prev.length === result.items.length &&
              prev.every((d, i) => d.id === result.items[i].id && d.processed === result.items[i].processed)
            ) {
              return prev; // same reference — skip re-render
            }
            return result.items;
          });
        } else {
          setDocuments((prev) => [...prev, ...result.items]);
        }
        offsetRef.current = offset + result.items.length;
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unknown error");
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    fetchPage(0, true);
  }, [fetchPage]);

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

  const loadMore = useCallback(() => {
    fetchPage(offsetRef.current, false);
  }, [fetchPage]);

  const refresh = useCallback(() => {
    stopPolling();
    offsetRef.current = 0;
    fetchPage(0, true);

    pollTimerRef.current = setInterval(() => {
      fetchPage(0, true);
    }, 5000);

    pollTimeoutRef.current = setTimeout(() => {
      stopPolling();
    }, 30000);
  }, [fetchPage, stopPolling]);

  return {
    documents,
    total,
    isLoading,
    error,
    hasMore: documents.length < total,
    loadMore,
    refresh,
  };
}
