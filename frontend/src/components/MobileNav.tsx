"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Network } from "lucide-react";
import { NAV_ITEMS, isNavActive } from "./Sidebar";

export function MobileNav() {
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const pathname = usePathname();
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const close = useCallback(() => {
    setClosing(true);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      setOpen(false);
      setClosing(false);
      timeoutRef.current = null;
    }, 200);
  }, []);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  // Auto-close on route change
  useEffect(() => {
    if (open) close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  const isActive = (href: string) => isNavActive(href, pathname);

  return (
    <div className="md:hidden">
      {/* Fixed top header bar */}
      <header className="mobile-header fixed inset-x-0 top-0 z-40 flex h-12 items-center justify-between px-4">
        <button
          onClick={() => (open ? close() : setOpen(true))}
          className="mobile-hamburger flex h-8 w-8 items-center justify-center rounded"
          aria-label="Toggle menu"
          data-open={open && !closing}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <line className="hamburger-top" x1="3" y1="4.5" x2="15" y2="4.5" />
            <line className="hamburger-mid" x1="3" y1="9" x2="15" y2="9" />
            <line className="hamburger-bot" x1="3" y1="13.5" x2="15" y2="13.5" />
          </svg>
        </button>
        <Link href="/" className="no-underline">
          <span className="sidebar-logo font-mono text-[10px] font-bold uppercase">
            hypomnema
          </span>
        </Link>
        {/* Spacer to balance the hamburger */}
        <div className="w-8" />
      </header>

      {/* Drawer overlay + panel */}
      {(open || closing) && (
        <>
          {/* Backdrop with blur */}
          <div
            className="mobile-backdrop fixed inset-0 z-40"
            style={{ animation: closing ? "backdrop-out 0.2s ease-out forwards" : "backdrop-in 0.25s ease-out forwards" }}
            onClick={close}
          />
          {/* Slide-in panel — uses sidebar background treatment */}
          <nav
            className="sidebar mobile-drawer fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-border"
            style={{ animation: closing ? "slide-out-left 0.2s ease-in forwards" : "slide-in-left 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards" }}
          >
            {/* Logo */}
            <div className="px-4 pt-6 pb-6">
              <Link href="/" className="no-underline" onClick={close}>
                <h1 className="sidebar-logo font-mono text-[11px] font-bold uppercase">
                  hypomnema
                </h1>
              </Link>
              <p className="mt-1 font-mono text-[9px] text-muted/40 tracking-[0.15em] uppercase">
                ontological synthesizer
              </p>
            </div>

            <div className="mx-4 mb-3 h-px bg-border" />

            {/* Nav items — staggered fade-in */}
            <div className="flex flex-col gap-0.5 px-3">
              {NAV_ITEMS.map(({ href, label, key, icon: Icon }, i) => {
                return (
                  <Link
                    key={href}
                    href={href}
                    data-active={isActive(href)}
                    className={`sidebar-nav-item flex items-center gap-2.5 rounded px-3 py-2 font-mono text-[11px] no-underline transition-colors ${
                      isActive(href)
                        ? "bg-surface-raised text-foreground"
                        : "text-muted hover:bg-surface-raised/50 hover:text-foreground"
                    }`}
                    style={{
                      animation: closing ? "none" : `fade-up 0.3s ease-out ${80 + i * 50}ms both`,
                    }}
                    data-testid={`mobile-nav-${key}`}
                    onClick={close}
                  >
                    <Icon size={14} className="shrink-0" />
                    {label}
                  </Link>
                );
              })}
            </div>

            <div className="flex-1" />

            {/* Viz link */}
            <div className="border-t border-border px-3 py-2">
              <Link
                href="/viz"
                data-active={pathname === "/viz"}
                className={`sidebar-nav-item flex items-center gap-2.5 rounded px-3 py-2 font-mono text-[11px] no-underline transition-colors ${
                  pathname === "/viz"
                    ? "bg-surface-raised text-foreground"
                    : "text-muted hover:bg-surface-raised/50 hover:text-foreground"
                }`}
                style={{
                  animation: closing ? "none" : "fade-up 0.3s ease-out 230ms both",
                }}
                onClick={close}
              >
                <Network size={14} className="shrink-0" />
                Visualization
              </Link>
            </div>
          </nav>
        </>
      )}
    </div>
  );
}
