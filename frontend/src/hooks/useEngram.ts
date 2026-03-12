"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import type { EngramDetail, Document } from "@/lib/types";

export interface UseEngramReturn {
  engram: EngramDetail | null;
  clusterDocs: Document[];
  isLoading: boolean;
  error: string | null;
}

export function useEngram(id: string): UseEngramReturn {
  const [engram, setEngram] = useState<EngramDetail | null>(null);
  const [clusterDocs, setClusterDocs] = useState<Document[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const activeIdRef = useRef(id);

  const fetchEngram = useCallback(async (engramId: string) => {
    activeIdRef.current = engramId;
    setIsLoading(true);
    setError(null);
    setEngram(null);
    setClusterDocs([]);
    try {
      const [detail, cluster] = await Promise.all([
        api.getEngram(engramId),
        api.getEngramCluster(engramId),
      ]);
      if (activeIdRef.current !== engramId) return;
      setEngram(detail);
      setClusterDocs(cluster);
    } catch (e) {
      if (activeIdRef.current !== engramId) return;
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      if (activeIdRef.current === engramId) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEngram(id);
  }, [id, fetchEngram]);

  return { engram, clusterDocs, isLoading, error };
}
