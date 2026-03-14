"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { Rows3, Search, Settings, Network, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useSidebar } from "@/hooks/useSidebarContext";
import { VizMinimap } from "./VizMinimap";

export const NAV_ITEMS = [
  { href: "/", label: "Stream", key: "stream", icon: Rows3 },
  { href: "/search", label: "Search", key: "search", icon: Search },
  { href: "/settings", label: "Settings", key: "settings", icon: Settings },
];

export function isNavActive(href: string, pathname: string) {
  return href === "/"
    ? pathname === "/" || pathname.startsWith("/documents") || pathname.startsWith("/engrams")
    : pathname.startsWith(href);
}

function NavItem({ href, label, active, testId, icon: Icon, collapsed }: {
  href: string;
  label: string;
  active: boolean;
  testId: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  collapsed: boolean;
}) {
  return (
    <Link
      href={href}
      data-active={active}
      className={`sidebar-nav-item flex items-center gap-2.5 rounded px-3 py-1.5 font-mono text-[11px] no-underline transition-colors ${
        collapsed ? "justify-center" : ""
      } ${
        active
          ? "bg-surface-raised text-foreground"
          : "text-muted hover:bg-surface-raised/50 hover:text-foreground"
      }`}
      data-testid={testId}
      title={collapsed ? label : undefined}
    >
      <Icon size={14} className="shrink-0" />
      {!collapsed && (
        <span className="sidebar-label-fade">{label}</span>
      )}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const { collapsed, toggle } = useSidebar();

  const isActive = (href: string) => isNavActive(href, pathname);

  return (
    <aside data-collapsed={collapsed} className={`sidebar flex shrink-0 flex-col border-r border-border sidebar-transition ${collapsed ? "w-14" : "w-56"}`}>
      {/* Logo */}
      <div className={`pt-6 pb-6 ${collapsed ? "px-2 flex justify-center" : "px-4"}`}>
        <Link href="/" className={`no-underline ${collapsed ? "" : "flex items-center gap-2"}`}>
          <Image src="/hypomnema.png" width={collapsed ? 28 : 22} height={collapsed ? 28 : 22} alt="Hypomnema" unoptimized />
          {!collapsed && (
            <h1 className="sidebar-logo font-mono text-[11px] font-bold uppercase">
              hypomnema
            </h1>
          )}
        </Link>
        {!collapsed && (
          <p className="mt-1 font-mono text-[9px] text-muted/40 tracking-[0.15em] uppercase">
            ontological synthesizer
          </p>
        )}
      </div>

      {/* Divider */}
      <div className={`mb-3 h-px bg-border ${collapsed ? "mx-2" : "mx-4"}`} />

      {/* Nav */}
      <nav className={`flex flex-col gap-0.5 ${collapsed ? "px-1.5" : "px-3"}`}>
        {NAV_ITEMS.map(({ href, label, key, icon }) => (
          <NavItem
            key={href}
            href={href}
            label={label}
            active={isActive(href)}
            testId={`nav-${key}`}
            icon={icon}
            collapsed={collapsed}
          />
        ))}
      </nav>

      {/* Spacer */}
      <div className="flex-1 min-h-8" />

      {/* Minimap — hidden when collapsed */}
      {!collapsed && (
        <div className="px-3 pb-1">
          <p className="mb-1.5 px-1 font-mono text-[9px] uppercase tracking-[0.15em] text-muted/30">
            topology
          </p>
          <VizMinimap />
        </div>
      )}

      {/* Viz link + toggle */}
      <div className={`border-t border-border py-2 space-y-0.5 ${collapsed ? "px-1.5" : "px-3"}`}>
        <NavItem
          href="/viz"
          label="Visualization"
          active={pathname === "/viz"}
          testId="nav-viz"
          icon={Network}
          collapsed={collapsed}
        />
        <button
          onClick={toggle}
          className={`flex w-full items-center rounded px-3 py-1.5 font-mono text-[11px] text-muted hover:bg-surface-raised/50 hover:text-foreground transition-colors ${collapsed ? "justify-center" : ""}`}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand" : "Collapse"}
        >
          {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
        </button>
      </div>
    </aside>
  );
}
