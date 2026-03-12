"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { AppSettings, ProvidersResponse } from "@/lib/types";

export interface UseSettingsReturn {
  settings: AppSettings | null;
  providers: ProvidersResponse | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useSettings(): UseSettingsReturn {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [s, p] = await Promise.all([
        api.getSettings(),
        api.getProviders(),
      ]);
      setSettings(s);
      setProviders(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  return { settings, providers, isLoading, error, refresh: fetchAll };
}
