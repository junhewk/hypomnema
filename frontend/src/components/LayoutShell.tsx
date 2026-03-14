"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { VizDataProvider } from "@/hooks/useVizDataContext";
import { SidebarProvider } from "@/hooks/useSidebarContext";
import { Sidebar } from "./Sidebar";
import { MobileNav } from "./MobileNav";
import { SetupWizard } from "./SetupWizard";
import { AuthGate } from "./AuthGate";
import { api } from "@/lib/api";
import type { AuthStatus } from "@/lib/types";

const LOCAL_AUTH: AuthStatus = { auth_required: false, authenticated: true, has_passphrase: false };

export function LayoutShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isViz = pathname === "/viz";
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null);
  const [mode, setMode] = useState<string>("local");
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [serverError, setServerError] = useState(false);

  useEffect(() => {
    api.checkHealth()
      .then(async (h) => {
        setNeedsSetup(h.needs_setup);
        setMode(h.mode);
        if (h.mode === "server") {
          const auth = await api.getAuthStatus();
          setAuthStatus(auth);
        } else {
          setAuthStatus(LOCAL_AUTH);
        }
      })
      .catch(() => {
        setServerError(true);
      });
  }, []);

  if (serverError) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="max-w-sm mx-auto px-4 text-center">
          <h1 className="font-mono text-lg font-bold tracking-tight mb-2">hypomnema</h1>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted/60">
            cannot reach server
          </p>
        </div>
      </div>
    );
  }

  if (needsSetup === null || authStatus === null) return null;

  // Auth gate: must authenticate before seeing anything
  if (authStatus.auth_required && !authStatus.authenticated) {
    return (
      <AuthGate
        authStatus={authStatus}
        onAuthenticated={() => window.location.reload()}
      />
    );
  }

  if (needsSetup) return <SetupWizard mode={mode} onComplete={() => setNeedsSetup(false)} />;

  return (
    <VizDataProvider>
      <SidebarProvider>
        <div className="flex h-screen">
          <div className="hidden md:flex">
            <Sidebar />
          </div>
          <MobileNav />
          <main className={`flex-1 ${isViz ? "overflow-hidden" : "overflow-y-auto pt-12 md:pt-0"}`}>
            {children}
          </main>
        </div>
      </SidebarProvider>
    </VizDataProvider>
  );
}
