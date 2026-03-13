"use client";

import { usePathname } from "next/navigation";
import { VizDataProvider } from "@/hooks/useVizDataContext";
import { Sidebar } from "./Sidebar";

export function LayoutShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isViz = pathname === "/viz";

  return (
    <VizDataProvider>
      {isViz ? (
        children
      ) : (
        <div className="flex h-screen">
          <Sidebar />
          <main className="flex-1 overflow-y-auto">{children}</main>
        </div>
      )}
    </VizDataProvider>
  );
}
