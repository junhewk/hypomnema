"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useVizData, type UseVizDataReturn } from "./useVizData";

const VizDataContext = createContext<UseVizDataReturn | null>(null);

export function VizDataProvider({ children }: { children: ReactNode }) {
  const data = useVizData();
  return (
    <VizDataContext.Provider value={data}>{children}</VizDataContext.Provider>
  );
}

export function useVizDataCtx(): UseVizDataReturn {
  const ctx = useContext(VizDataContext);
  if (!ctx) {
    throw new Error("useVizDataCtx must be used within a VizDataProvider");
  }
  return ctx;
}
