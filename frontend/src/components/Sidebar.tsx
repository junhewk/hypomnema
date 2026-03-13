"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { VizMinimap } from "./VizMinimap";

const NAV_ITEMS = [
  { href: "/", label: "Stream", key: "stream" },
  { href: "/search", label: "Search", key: "search" },
  { href: "/settings", label: "Settings", key: "settings" },
];

function NavItem({ href, label, active, testId }: {
  href: string;
  label: string;
  active: boolean;
  testId: string;
}) {
  return (
    <Link
      href={href}
      data-active={active}
      className={`sidebar-nav-item block rounded px-3 py-1.5 font-mono text-[11px] no-underline transition-colors ${
        active
          ? "bg-surface-raised text-foreground"
          : "text-muted hover:bg-surface-raised/50 hover:text-foreground"
      }`}
      data-testid={testId}
    >
      {label}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();

  function isActive(href: string) {
    return href === "/"
      ? pathname === "/" || pathname.startsWith("/documents") || pathname.startsWith("/engrams")
      : pathname.startsWith(href);
  }

  return (
    <aside className="sidebar flex w-56 shrink-0 flex-col border-r border-border">
      {/* Logo */}
      <div className="px-4 pt-6 pb-6">
        <Link href="/" className="no-underline">
          <h1 className="sidebar-logo font-mono text-[11px] font-bold uppercase">
            hypomnema
          </h1>
        </Link>
        <p className="mt-1 font-mono text-[9px] text-muted/40 tracking-[0.15em] uppercase">
          ontological synthesizer
        </p>
      </div>

      {/* Divider */}
      <div className="mx-4 mb-3 h-px bg-border" />

      {/* Nav */}
      <nav className="flex flex-col gap-0.5 px-3">
        {NAV_ITEMS.map(({ href, label, key }) => (
          <NavItem
            key={href}
            href={href}
            label={label}
            active={isActive(href)}
            testId={`nav-${key}`}
          />
        ))}
      </nav>

      {/* Spacer */}
      <div className="flex-1 min-h-8" />

      {/* Minimap */}
      <div className="px-3 pb-1">
        <p className="mb-1.5 px-1 font-mono text-[9px] uppercase tracking-[0.15em] text-muted/30">
          topology
        </p>
        <VizMinimap />
      </div>

      {/* Viz link */}
      <div className="border-t border-border px-3 py-2">
        <NavItem
          href="/viz"
          label="Visualization"
          active={pathname === "/viz"}
          testId="nav-viz"
        />
      </div>
    </aside>
  );
}
