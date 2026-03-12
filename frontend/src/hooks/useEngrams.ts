"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import type { EngramDetail } from "@/lib/types";

export interface UseEngramsReturn {
  engrams: Map<string, EngramDetail>;
  isLoading: boolean;
  error: string | null;
}

export function useEngrams(ids: string[]): UseEngramsReturn {
  const [engrams, setEngrams] = useState<Map<string, EngramDetail>>(
    () => new Map(),
  );
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const key = useMemo(() => [...ids].sort().join(","), [ids]);
  const activeKeyRef = useRef(key);

  const doFetch = useCallback(
    async (engramKey: string) => {
      activeKeyRef.current = engramKey;
      const currentIds = engramKey === "" ? [] : engramKey.split(",");
      setIsLoading(currentIds.length > 0);
      setError(null);
      try {
        const results = await Promise.allSettled(
          currentIds.map((id) => api.getEngram(id)),
        );
        if (activeKeyRef.current !== engramKey) return;
        const map = new Map<string, EngramDetail>();
        const errors: string[] = [];
        results.forEach((result, i) => {
          if (result.status === "fulfilled") {
            map.set(currentIds[i], result.value);
          } else {
            errors.push(
              result.reason instanceof Error
                ? result.reason.message
                : `Failed to fetch ${currentIds[i]}`,
            );
          }
        });
        setEngrams(map);
        if (errors.length > 0) setError(errors.join("; "));
      } catch (e) {
        if (activeKeyRef.current !== engramKey) return;
        setError(e instanceof Error ? e.message : "Unknown error");
      } finally {
        if (activeKeyRef.current === engramKey) setIsLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    doFetch(key);
  }, [key, doFetch]);

  return { engrams, isLoading, error };
}
