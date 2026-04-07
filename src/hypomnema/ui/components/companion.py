"""Baby dinosaur companion widget — grows with engram count, mood reflects lint health."""

from __future__ import annotations

import logging

from nicegui import app, ui

logger = logging.getLogger(__name__)

_ACCENT = "#3ecfcf"
_ACCENT_DIM = "#2a8a8a"
_DISTRESS = "#e06c75"
_WARN = "#d4b06a"
_MUTED = "#3d4252"

_BODY_COLORS = {
    "sleeping": _MUTED,
    "happy": _ACCENT,
    "concerned": _WARN,
    "distressed": _DISTRESS,
}

_BODY_RX = [0, 8, 10, 12, 13]
_BODY_RY = [0, 7, 9, 10, 11]


def _eye(cx: float, cy: float, rx: float, ry: float, mood: str) -> str:
    if mood == "sleeping":
        return f'<ellipse class="dino-eye" cx="{cx}" cy="{cy}" rx="{rx}" ry="0.5" fill="#0a0a0a"/>'
    scale = 1.3 if mood == "distressed" else 1.15 if mood == "concerned" else 1
    return f'<ellipse class="dino-eye" cx="{cx}" cy="{cy}" rx="{rx * scale}" ry="{ry * scale}" fill="#0a0a0a"/>'


def _mouth(cx: float, cy: float, mood: str) -> str:
    if mood == "sleeping":
        return ""
    w = 3
    stroke = 'stroke="#0a0a0a" stroke-width="0.8" stroke-linecap="round"'
    if mood == "happy":
        return f'<path d="M{cx - w},{cy} Q{cx},{cy + 3} {cx + w},{cy}" fill="none" {stroke}/>'
    if mood == "distressed":
        d = f"M{cx - w},{cy + 1.5} Q{cx},{cy - 1.5} {cx + w},{cy + 1.5}"
        return f'<path d="{d}" fill="none" {stroke}/>'
    return f'<line x1="{cx - w}" y1="{cy}" x2="{cx + w}" y2="{cy}" {stroke}/>'


def _spikes(count: int, bx: float, by: float, body_ry: float) -> str:
    if count == 0:
        return ""
    import math

    parts = []
    for i in range(count):
        angle = -30 + (i * 60 / max(count - 1, 1))
        rad = angle * math.pi / 180
        sx = bx - math.sin(rad) * (body_ry - 1)
        sy = by - math.cos(rad) * (body_ry - 1)
        h = 3 + i * 0.3
        dx = -math.sin(rad) * h
        dy = -math.cos(rad) * h
        parts.append(
            f'<polygon points="{sx - 1.5},{sy} {sx + dx},{sy + dy} {sx + 1.5},{sy}" '
            f'fill="{_ACCENT_DIM}" opacity="0.7"/>'
        )
    return "".join(parts)


def _build_svg(stage: int, mood: str) -> str:
    w, h = 48, 48
    cx, cy = 22, 24
    body_rx = _BODY_RX[stage] if stage < len(_BODY_RX) else 13
    body_ry = _BODY_RY[stage] if stage < len(_BODY_RY) else 11
    color = _BODY_COLORS.get(mood, _ACCENT)

    cls = f"companion-dino companion-mood-{mood} companion-stage-{stage}"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"'
        f' class="{cls}" style="width:48px;height:48px">'
    )

    if stage == 0:
        # Egg
        svg += (
            f'<path d="M{cx - 10},{cy} Q{cx - 10},{cy - 12} {cx},{cy - 12} Q{cx + 10},{cy - 12} {cx + 10},{cy}'
            f' L{cx + 6},{cy - 1} L{cx + 3},{cy + 2} L{cx},{cy - 1} L{cx - 3},{cy + 2} L{cx - 6},{cy - 1} Z"'
            f' fill="#d4cfc0" stroke="#b8b3a3" stroke-width="0.5"/>'
            f'<path d="M{cx - 10},{cy} L{cx - 6},{cy - 1} L{cx - 3},{cy + 2} L{cx},{cy - 1} L{cx + 3},{cy + 2}'
            f' L{cx + 6},{cy - 1} L{cx + 10},{cy} Q{cx + 10},{cy + 12} {cx},{cy + 12}'
            f' Q{cx - 10},{cy + 12} {cx - 10},{cy} Z" fill="#e8e3d4" stroke="#b8b3a3" stroke-width="0.5"/>'
        )
        svg += _eye(cx - 3, cy - 2, 1.5, 2, "sleeping")
        svg += _eye(cx + 3, cy - 2, 1.5, 2, "sleeping")
    else:
        # Tail (stage 3+)
        if stage >= 3:
            tx = cx + body_rx - 2
            svg += (
                f'<path class="dino-tail" d="M{tx},{cy + 2} Q{tx + 6},{cy + 1} {tx + 8},{cy - 2}'
                f' Q{tx + 9},{cy - 4} {tx + 7},{cy - 3} Q{tx + 5},{cy - 1} {tx},{cy + 1}"'
                f' fill="{_ACCENT_DIM}" opacity="0.8"/>'
            )

        # Legs (stage 2+)
        if stage >= 2:
            ly = cy + body_ry - 1
            svg += (
                f'<g class="dino-legs">'
                f'<rect x="{cx - 6}" y="{ly}" width="3.5" height="4" rx="1.5" fill="{_ACCENT_DIM}"/>'
                f'<rect x="{cx + 2.5}" y="{ly}" width="3.5" height="4" rx="1.5" fill="{_ACCENT_DIM}"/>'
                f'</g>'
            )

        # Body
        svg += f'<ellipse class="dino-body" cx="{cx}" cy="{cy}" rx="{body_rx}" ry="{body_ry}" fill="{color}"/>'

        # Spikes
        spike_count = [0, 0, 2, 4, 5][stage] if stage < 5 else 5
        svg += _spikes(spike_count, cx, cy, body_ry)

        # Shell remnants for stage 1
        if stage == 1:
            svg += (
                f'<path d="M{cx - 8},{cy + 4} Q{cx - 9},{cy + body_ry + 3} {cx},{cy + body_ry + 2}'
                f' Q{cx + 9},{cy + body_ry + 3} {cx + 8},{cy + 4}"'
                f' fill="#e8e3d4" stroke="#b8b3a3" stroke-width="0.5" opacity="0.7"/>'
            )

        # Eyes
        eye_y = cy - body_ry * 0.25
        eye_spacing = body_rx * 0.4
        eye_rx = 1.8 + stage * 0.15
        eye_ry = 2.2 + stage * 0.2
        svg += _eye(cx - eye_spacing, eye_y, eye_rx, eye_ry, mood)
        svg += _eye(cx + eye_spacing, eye_y, eye_rx, eye_ry, mood)

        # Mouth
        svg += _mouth(cx, eye_y + body_ry * 0.45, mood)

    svg += "</svg>"
    return svg


async def render_companion(container: ui.element) -> None:
    """Render the baby dino companion into the given container."""
    db = getattr(app.state, "db", None)
    if db is None:
        return

    try:
        from hypomnema.api.companion import _compute_growth_stage, _compute_mood

        async def _count(sql: str) -> int:
            cursor = await db.execute(sql)
            row = await cursor.fetchone()
            await cursor.close()
            return row[0] if row else 0

        engram_count = await _count("SELECT COUNT(*) FROM engrams")
        edge_count = await _count("SELECT COUNT(*) FROM edges")

        # Lint severity counts
        cursor = await db.execute(
            "SELECT severity, COUNT(*) FROM lint_issues WHERE resolved = 0 GROUP BY severity"
        )
        severity_counts = {row[0]: row[1] for row in await cursor.fetchall()}
        await cursor.close()
        lint_errors = severity_counts.get("error", 0)
        lint_warnings = severity_counts.get("warning", 0)

        mood = _compute_mood(engram_count, lint_errors, lint_warnings)
        stage = _compute_growth_stage(engram_count)

        with container:
            ui.add_head_html(_COMPANION_CSS, shared=True)
            ui.html(_build_svg(stage, mood))
            ui.label(f"{engram_count} engrams \u00b7 {edge_count} edges").classes(
                "text-center"
            ).style(
                "font-size: 8px; color: var(--fg-dim); letter-spacing: 0.02em; margin-top: 4px"
            )
            ui.run_javascript(_idle_js(stage, mood))
    except Exception:
        logger.debug("Companion render failed", exc_info=True)


_COMPANION_CSS = (  # noqa: E501
    "<style>"
    ".companion-mood-sleeping{animation:companion-breathe 4s ease-in-out infinite}"
    ".companion-mood-happy{animation:companion-pulse 3s ease-in-out infinite}"
    ".companion-mood-concerned{animation:companion-sway 4s ease-in-out infinite}"
    ".companion-mood-distressed{animation:companion-shake 2s ease-in-out infinite}"
    "@keyframes companion-breathe{0%,100%{opacity:.6}50%{opacity:.85}}"
    "@keyframes companion-pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.03)}}"
    "@keyframes companion-sway{0%,100%{transform:rotate(0)}25%{transform:rotate(-1.5deg)}"
    "75%{transform:rotate(1.5deg)}}"
    "@keyframes companion-shake{0%,100%{transform:rotate(0)}20%{transform:rotate(-2deg)}"
    "40%{transform:rotate(2deg)}60%{transform:rotate(-1.5deg)}80%{transform:rotate(1deg)}}"
    ".action-rock{animation:dino-rock .8s ease-in-out!important}"
    ".action-hop{animation:dino-hop .5s ease-out!important}"
    ".action-nod{animation:dino-nod .4s ease-in-out!important}"
    ".action-roar{animation:dino-roar .6s ease-in-out!important}"
    ".action-spin{animation:dino-spin .7s ease-in-out!important}"
    ".action-shiver{animation:dino-shiver .5s ease-in-out!important}"
    ".action-peek{animation:dino-peek .6s ease-in-out!important}"
    "@keyframes dino-rock{0%,100%{transform:rotate(0)}25%{transform:rotate(-4deg)}"
    "75%{transform:rotate(4deg)}}"
    "@keyframes dino-hop{0%,100%{transform:translateY(0)}40%{transform:translateY(-6px)}}"
    "@keyframes dino-nod{0%,100%{transform:translateY(0)}50%{transform:translateY(2px)}}"
    "@keyframes dino-roar{0%,100%{transform:scale(1)}50%{transform:scale(1.12)}}"
    "@keyframes dino-spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}"
    "@keyframes dino-shiver{0%,100%{transform:translateX(0)}"
    "20%{transform:translateX(-1.5px)}40%{transform:translateX(1.5px)}"
    "60%{transform:translateX(-1px)}80%{transform:translateX(1px)}}"
    "@keyframes dino-peek{0%,100%{transform:translateY(0)}50%{transform:translateY(4px)}}"
    "</style>"
)


def _idle_js(stage: int, mood: str) -> str:
    """Generate JS idle animation loop for the companion."""
    # Build available actions based on stage and mood
    actions: dict[str, dict[str, object]] = {}
    if stage == 0:
        actions["rock"] = {"duration": 800}
    if stage >= 1 and mood != "sleeping":
        actions["nod"] = {"duration": 400}
    if stage >= 2 and mood in ("happy", "concerned"):
        actions["hop"] = {"duration": 500}
    if stage >= 2 and mood == "concerned":
        actions["peek"] = {"duration": 600}
    if stage >= 2 and mood == "distressed":
        actions["shiver"] = {"duration": 500}
    if stage >= 4 and mood == "happy":
        actions["roar"] = {"duration": 600}
        actions["spin"] = {"duration": 700}

    if not actions:
        return ""

    import json

    return f"""
    (function() {{
        var actions = {json.dumps(actions)};
        var names = Object.keys(actions);
        var timer = null;
        function tick() {{
            var name = names[Math.floor(Math.random() * names.length)];
            var el = document.querySelector('.companion-dino');
            if (!el) return;
            el.classList.add('action-' + name);
            setTimeout(function() {{ el.classList.remove('action-' + name); }}, actions[name].duration);
            timer = setTimeout(tick, 8000 + Math.random() * 7000);
        }}
        timer = setTimeout(tick, 3000 + Math.random() * 5000);
    }})();
    """
