"""Theme system for Hypomnema UI.

Provides a registry of colour palettes, CSS generation, and Quasar color overrides.
Source-type and heat-tier styles are semantic (fixed across themes).
"""

from __future__ import annotations

from typing import Any

# ── Theme registry ─────────────────────────────────────────────────────────────

THEMES: dict[str, dict[str, Any]] = {
    "midnight": {
        "label": "Midnight",
        "colors": {
            "primary": "#9498a5",
            "secondary": "#3d4252",
            "accent": "#3ecfcf",
            "dark": "#0b0c12",
            "dark-page": "#0a0b10",
            "positive": "#56c9a0",
            "negative": "#e06c75",
            "info": "#5e9eff",
            "warning": "#d4b06a",
        },
        "css_vars": {
            "bg": "#0a0b10",
            "bg-surface": "#11131a",
            "bg-raised": "#181b25",
            "bg-sidebar": "#0b0c12",
            "fg": "#c8ccd6",
            "fg-muted": "#636978",
            "fg-dim": "#3d4252",
            "border": "#1c1f2c",
            "border-light": "#252838",
            "accent": "#3ecfcf",
            "accent-soft": "rgba(62,207,207,0.08)",
        },
    },
    "graphite": {
        "label": "Graphite",
        "colors": {
            "primary": "#a0a0a0",
            "secondary": "#4a4a4a",
            "accent": "#7eb8da",
            "dark": "#0d0d0d",
            "dark-page": "#0a0a0a",
            "positive": "#4caf50",
            "negative": "#ef5350",
            "info": "#7eb8da",
            "warning": "#ff9800",
        },
        "css_vars": {
            "bg": "#0a0a0a",
            "bg-surface": "#111111",
            "bg-raised": "#1a1a1a",
            "bg-sidebar": "#0d0d0d",
            "fg": "#d4d4d4",
            "fg-muted": "#6b6b6b",
            "fg-dim": "#4a4a4a",
            "border": "#1e1e1e",
            "border-light": "#2a2a2a",
            "accent": "#7eb8da",
            "accent-soft": "rgba(126,184,218,0.08)",
        },
    },
    "phantom": {
        "label": "Phantom",
        "colors": {
            "primary": "#a098b0",
            "secondary": "#453f55",
            "accent": "#b07cf7",
            "dark": "#0d0a14",
            "dark-page": "#0c0a12",
            "positive": "#7ccfa0",
            "negative": "#e06c75",
            "info": "#7ca0f7",
            "warning": "#d4a86a",
        },
        "css_vars": {
            "bg": "#0c0a12",
            "bg-surface": "#14111d",
            "bg-raised": "#1d1928",
            "bg-sidebar": "#0d0a14",
            "fg": "#d0cdd8",
            "fg-muted": "#6e6880",
            "fg-dim": "#453f55",
            "border": "#211d30",
            "border-light": "#2d2840",
            "accent": "#b07cf7",
            "accent-soft": "rgba(176,124,247,0.08)",
        },
    },
}

DEFAULT_THEME = "midnight"

# ── Semantic styles (fixed across themes) ──────────────────────────────────────

SOURCE_STYLES: dict[str, dict[str, str]] = {
    "scribble": {"label": "scribble", "color": "#9498a5", "bg": "rgba(148,152,165,0.07)"},
    "file": {"label": "file", "color": "#5e9eff", "bg": "rgba(94,158,255,0.07)"},
    "url": {"label": "url", "color": "#3ecfcf", "bg": "rgba(62,207,207,0.08)"},
    "feed": {"label": "feed", "color": "#56c9a0", "bg": "rgba(86,201,160,0.07)"},
    "synthesis": {"label": "synthesis", "color": "#d4b06a", "bg": "rgba(212,176,106,0.07)"},
}

HEAT_TIER_STYLES: dict[str, dict[str, str]] = {
    "active": {"icon": "local_fire_department", "color": "#56c9a0", "label": "Active"},
    "reference": {"icon": "menu_book", "color": "#5e9eff", "label": "Reference"},
    "dormant": {"icon": "bedtime", "color": "#3d4252", "label": "Dormant"},
}

# ── Font imports ───────────────────────────────────────────────────────────────

FONT_IMPORTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    "family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400"
    "&family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400"
    '&display=swap" rel="stylesheet">'
)

# ── CSS generation ─────────────────────────────────────────────────────────────

# Static CSS rules that apply regardless of which theme is active.
# They reference CSS custom properties set in :root.
_CSS_RULES = """\
/* ── Base ────────────────────────────────────────────────── */
body {
    background: var(--bg) !important;
    color: var(--fg) !important;
    font-family: var(--font-body) !important;
    font-weight: 400;
    font-size: 14px;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* ── Quasar overrides ────────────────────────────────────── */
.q-card {
    background: var(--bg-surface) !important;
    border: 1px solid var(--border) !important;
    box-shadow: none !important;
}

.q-drawer {
    background: var(--bg-sidebar) !important;
    border-right: 1px solid var(--border) !important;
}

.q-item:hover {
    background: var(--accent-soft) !important;
}

.q-toolbar {
    background: transparent !important;
}

.q-separator {
    background: var(--border) !important;
}

.q-field--outlined .q-field__control {
    border-color: var(--border) !important;
    transition: border-color 0.2s ease;
}

.q-field--outlined .q-field__control:hover {
    border-color: var(--border-light) !important;
}

.q-field--focused .q-field__control {
    border-color: var(--accent) !important;
}

.q-field__label {
    color: var(--fg-muted) !important;
}

.q-field__native, .q-field__input {
    color: var(--fg) !important;
    font-family: var(--font-body) !important;
}

.q-stepper--dark {
    background: transparent !important;
}

.q-stepper__step-inner {
    color: var(--fg) !important;
}

/* ── Typography ──────────────────────────────────────────── */
.font-display {
    font-family: var(--font-display) !important;
}

.text-display-lg {
    font-family: var(--font-display) !important;
    font-weight: 600;
    font-size: 1.5rem;
    line-height: 1.3;
    letter-spacing: -0.01em;
    color: var(--fg);
}

.text-display-sm {
    font-family: var(--font-display) !important;
    font-weight: 500;
    font-size: 1.125rem;
    line-height: 1.4;
    color: var(--fg);
}

/* ── Scrollbar ───────────────────────────────────────────── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-light); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--fg-dim); }

/* ── Source & label badges ───────────────────────────────── */
.source-badge {
    font-family: var(--font-body);
    font-size: 9px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 3px 8px;
    border-radius: 3px;
}

.section-label {
    font-family: var(--font-body);
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--accent);
}

/* ── Utility classes ─────────────────────────────────────── */
.text-muted { color: var(--fg-muted) !important; }
.text-dim   { color: var(--fg-dim) !important; }
.text-xs    { font-size: 11px !important; }
.text-2xs   { font-size: 9px !important; }

/* ── Animations ──────────────────────────────────────────── */
@keyframes fade-up {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}
.animate-fade-up {
    animation: fade-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.animate-fade-up:nth-child(1)     { animation-delay: 0ms; }
.animate-fade-up:nth-child(2)     { animation-delay: 50ms; }
.animate-fade-up:nth-child(3)     { animation-delay: 100ms; }
.animate-fade-up:nth-child(4)     { animation-delay: 140ms; }
.animate-fade-up:nth-child(5)     { animation-delay: 170ms; }
.animate-fade-up:nth-child(n+6)   { animation-delay: 200ms; }

@keyframes pulse-dot {
    0%, 100% { opacity: 0.4; }
    50%      { opacity: 1; }
}
.animate-pulse-dot { animation: pulse-dot 1.5s ease-in-out infinite; }

/* ── Card hover ──────────────────────────────────────────── */
.doc-card {
    transition: border-color 0.3s ease, transform 0.3s ease, box-shadow 0.3s ease;
}
.doc-card:hover {
    border-color: var(--border-light) !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 20px rgba(0,0,0,0.25) !important;
}

/* ── Links ───────────────────────────────────────────────── */
a.engram-link {
    color: var(--accent);
    text-decoration: none;
    transition: color 0.15s;
}
a.engram-link:hover { opacity: 0.8; }
"""


def get_theme(name: str) -> dict[str, Any]:
    """Return a theme definition by name, falling back to default."""
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def get_theme_names() -> dict[str, str]:
    """Return {id: label} mapping of all available themes."""
    return {tid: t["label"] for tid, t in THEMES.items()}


def get_colors(name: str) -> dict[str, str]:
    """Return Quasar color overrides for a theme."""
    colors: dict[str, str] = get_theme(name)["colors"]
    return colors


def get_theme_css(name: str) -> str:
    """Generate the full <style> block for a given theme."""
    theme = get_theme(name)
    css_vars = theme["css_vars"]
    root_lines = "\n".join(f"    --{k}: {v};" for k, v in css_vars.items())
    return (
        "<style>\n"
        ":root {\n"
        f"{root_lines}\n"
        "    --font-display: 'Cormorant Garamond', 'Georgia', serif;\n"
        "    --font-body: 'DM Sans', -apple-system, 'Segoe UI', sans-serif;\n"
        "}\n"
        f"{_CSS_RULES}\n"
        "</style>"
    )


MOBILE_CSS = """
<style>
.mobile-header { display: none !important; }

@media (max-width: 1023px) {
    .mobile-header { display: flex !important; align-items: center; }
    main.mx-auto { padding-left: 12px; padding-right: 12px; padding-top: 16px; }
    .q-card { border-radius: 4px !important; }
}

html, body { overflow-x: hidden; max-width: 100vw; }
</style>
"""
