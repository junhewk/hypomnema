"""Dark monospace theme for Hypomnema UI."""

from __future__ import annotations

# Quasar color overrides
COLORS = {
    "primary": "#a0a0a0",
    "secondary": "#4a4a4a",
    "accent": "#7eb8da",
    "dark": "#0d0d0d",
    "dark-page": "#0a0a0a",
    "positive": "#4caf50",
    "negative": "#ef5350",
    "info": "#7eb8da",
    "warning": "#ff9800",
}

# Source type styles matching frontend SOURCE_STYLES
SOURCE_STYLES: dict[str, dict[str, str]] = {
    "scribble": {"label": "scribble", "color": "#a0a0a0", "bg": "rgba(160,160,160,0.08)"},
    "file": {"label": "file", "color": "#7eb8da", "bg": "rgba(126,184,218,0.08)"},
    "url": {"label": "url", "color": "#b8a07e", "bg": "rgba(184,160,126,0.08)"},
    "feed": {"label": "feed", "color": "#8fb87e", "bg": "rgba(143,184,126,0.08)"},
}

# Custom CSS injected into every page
CUSTOM_CSS = """
<style>
:root {
    --bg: #0a0a0a;
    --fg: #d4d4d4;
    --muted: #6b6b6b;
    --border: #1e1e1e;
    --accent: #7eb8da;
}

body {
    background: var(--bg) !important;
    color: var(--fg) !important;
    font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Cascadia Code', monospace !important;
}

.q-card {
    background: #111111 !important;
    border: 1px solid var(--border) !important;
}

.q-drawer {
    background: #0d0d0d !important;
    border-right: 1px solid var(--border) !important;
}

.q-item:hover {
    background: rgba(255,255,255,0.03) !important;
}

.q-toolbar {
    background: transparent !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }

/* Source badges */
.source-badge {
    font-family: monospace;
    font-size: 10px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 2px 6px;
    border-radius: 2px;
}

/* Muted text */
.text-muted { color: var(--muted) !important; }
.text-xs { font-size: 10px !important; }

/* Animate fade-up */
@keyframes fade-up {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
}
.animate-fade-up { animation: fade-up 0.3s ease-out; }

/* Pulsing dot for loading states */
@keyframes pulse-dot {
    0%, 100% { opacity: 0.4; }
    50% { opacity: 1; }
}
.animate-pulse-dot { animation: pulse-dot 1.5s ease-in-out infinite; }
</style>
"""

# Mobile-responsive CSS — hides header on desktop, adjusts padding on mobile
MOBILE_CSS = """
<style>
/* Mobile header: only visible below 1024px */
.mobile-header { display: none !important; }

@media (max-width: 1023px) {
    .mobile-header { display: flex !important; align-items: center; }

    /* Tighten main content padding on small screens */
    main.mx-auto { padding-left: 12px; padding-right: 12px; padding-top: 16px; }

    /* Cards full-width on mobile */
    .q-card { border-radius: 4px !important; }
}

/* Prevent horizontal overflow on small screens */
html, body { overflow-x: hidden; max-width: 100vw; }
</style>
"""
