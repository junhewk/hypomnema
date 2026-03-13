"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { VizDataProvider } from "@/hooks/useVizDataContext";
import { Sidebar } from "./Sidebar";
import { MobileNav } from "./MobileNav";
import { SetupWizard } from "./SetupWizard";
import { api } from "@/lib/api";

export function LayoutShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isViz = pathname === "/viz";
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null);
  const [mode, setMode] = useState<string>("local");

  useEffect(() => {
    api.checkHealth().then((h) => {
      setNeedsSetup(h.needs_setup);
      setMode(h.mode);
    }).catch(() => {
      // If health check fails, assume no setup needed (backend may be starting)
      setNeedsSetup(false);
    });
  }, []);

  if (needsSetup === null) return null;
  if (needsSetup) return <SetupWizard mode={mode} onComplete={() => setNeedsSetup(false)} />;

  return (
    <VizDataProvider>
      {isViz ? (
        children
      ) : (
        <div className="flex h-screen">
          <div className="hidden md:flex">
            <Sidebar />
          </div>
          <MobileNav />
          <main className="flex-1 overflow-y-auto pt-12 md:pt-0">{children}</main>
        </div>
      )}
    </VizDataProvider>
  );
}
