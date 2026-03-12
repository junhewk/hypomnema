"use client";

import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";
import type { ScoredDocument, Edge, SearchMode } from "@/lib/types";

export interface DocumentSearchResult {
  mode: "documents";
  results: ScoredDocument[];
}

export interface KnowledgeSearchResult {
  mode: "knowledge";
  results: Edge[];
}

export type SearchResult = DocumentSearchResult | KnowledgeSearchResult;

export interface UseSearchReturn {
  result: SearchResult | null;
  isLoading: boolean;
  error: string | null;
}

export function useSearch(query: string, mode: SearchMode): UseSearchReturn {
  const [result, setResult] = useState<SearchResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRequestRef = useRef("");

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);

    if (!query.trim()) {
      setResult(null);
      setIsLoading(false);
      setError(null);
      activeRequestRef.current = "";
      return;
    }

    setIsLoading(true);
    setError(null);

    const key = `${query}:${mode}`;

    timerRef.current = setTimeout(async () => {
      activeRequestRef.current = key;
      try {
        const results = mode === "documents"
          ? await api.searchDocuments(query)
          : await api.searchKnowledge(query);
        if (activeRequestRef.current !== key) return;
        setResult({ mode, results } as SearchResult);
      } catch (e) {
        if (activeRequestRef.current !== key) return;
        setError(e instanceof Error ? e.message : "Unknown error");
        setResult(null);
      } finally {
        if (activeRequestRef.current === key) setIsLoading(false);
      }
    }, 300);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      activeRequestRef.current = "";
    };
  }, [query, mode]);

  return { result, isLoading, error };
}
