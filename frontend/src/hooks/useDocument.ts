"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import type { DocumentDetail } from "@/lib/types";

export interface UseDocumentReturn {
  document: DocumentDetail | null;
  isLoading: boolean;
  error: string | null;
}

export function useDocument(id: string): UseDocumentReturn {
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const activeIdRef = useRef(id);

  const fetchDocument = useCallback(async (docId: string) => {
    activeIdRef.current = docId;
    setIsLoading(true);
    setError(null);
    setDocument(null);
    try {
      const doc = await api.getDocument(docId);
      if (activeIdRef.current !== docId) return;
      setDocument(doc);
    } catch (e) {
      if (activeIdRef.current !== docId) return;
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      if (activeIdRef.current === docId) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDocument(id);
  }, [id, fetchDocument]);

  return { document, isLoading, error };
}
