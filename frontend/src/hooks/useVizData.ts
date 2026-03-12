"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import type { ProjectionPoint, Cluster, VizEdge } from "@/lib/types";

export interface UseVizDataReturn {
  points: ProjectionPoint[];
  clusters: Cluster[];
  edges: VizEdge[];
  isLoading: boolean;
  error: string | null;
}

export function useVizData(): UseVizDataReturn {
  const [points, setPoints] = useState<ProjectionPoint[]>([]);
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [edges, setEdges] = useState<VizEdge[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const activeRef = useRef(true);

  const fetchData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [p, c, e] = await Promise.all([
        api.getProjections(),
        api.getClusters(),
        api.getVizEdges(),
      ]);
      if (!activeRef.current) return;
      setPoints(p);
      setClusters(c);
      setEdges(e);
    } catch (err) {
      if (!activeRef.current) return;
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      if (activeRef.current) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    activeRef.current = true;
    fetchData();
    return () => {
      activeRef.current = false;
    };
  }, [fetchData]);

  return { points, clusters, edges, isLoading, error };
}
