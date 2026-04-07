// Baby dinosaur companion — grows with engram count, mood reflects lint health.
// Pure inline SVG, CSS animations, no image assets.

const ACCENT = '#3ecfcf';
const ACCENT_DIM = '#2a8a8a';
const DISTRESS = '#e06c75';
const WARN = '#d4b06a';
const MUTED = '#3d4252';

// ---------- SVG building blocks ----------

function eyeEllipse(cx, cy, rx, ry, mood) {
    const cls = 'dino-eye';
    if (mood === 'sleeping') {
        // Closed eyes — thin horizontal lines
        return `<ellipse class="${cls}" cx="${cx}" cy="${cy}" rx="${rx}" ry="0.5" fill="#0a0a0a"/>`;
    }
    const scale = mood === 'distressed' ? 1.3 : mood === 'concerned' ? 1.15 : 1;
    return `<ellipse class="${cls}" cx="${cx}" cy="${cy}" rx="${rx * scale}" ry="${ry * scale}" fill="#0a0a0a"/>`;
}

function mouth(cx, cy, mood) {
    if (mood === 'sleeping') return '';
    const w = 3;
    if (mood === 'happy') {
        return `<path class="dino-mouth" d="M${cx - w},${cy} Q${cx},${cy + 3} ${cx + w},${cy}" fill="none" stroke="#0a0a0a" stroke-width="0.8" stroke-linecap="round"/>`;
    }
    if (mood === 'distressed') {
        return `<path class="dino-mouth" d="M${cx - w},${cy + 1.5} Q${cx},${cy - 1.5} ${cx + w},${cy + 1.5}" fill="none" stroke="#0a0a0a" stroke-width="0.8" stroke-linecap="round"/>`;
    }
    // concerned — flat line
    return `<line class="dino-mouth" x1="${cx - w}" y1="${cy}" x2="${cx + w}" y2="${cy}" stroke="#0a0a0a" stroke-width="0.8" stroke-linecap="round"/>`;
}

function spikes(count, bodyX, bodyY, bodyRY) {
    if (count === 0) return '';
    const spikes = [];
    for (let i = 0; i < count; i++) {
        const angle = -30 + (i * 60 / Math.max(count - 1, 1));
        const rad = angle * Math.PI / 180;
        const bx = bodyX - Math.sin(rad) * (bodyRY - 1);
        const by = bodyY - Math.cos(rad) * (bodyRY - 1);
        const h = 3 + i * 0.3;
        const dx = -Math.sin(rad) * h;
        const dy = -Math.cos(rad) * h;
        spikes.push(`<polygon points="${bx - 1.5},${by} ${bx + dx},${by + dy} ${bx + 1.5},${by}" fill="${ACCENT_DIM}" opacity="0.7"/>`);
    }
    return spikes.join('');
}

function eggShell(cx, cy, rx, ry) {
    // Two half-shell pieces with zigzag crack
    const top = `<path class="dino-shell-top" d="M${cx - rx},${cy} Q${cx - rx},${cy - ry} ${cx},${cy - ry} Q${cx + rx},${cy - ry} ${cx + rx},${cy} L${cx + rx * 0.6},${cy - 1} L${cx + rx * 0.3},${cy + 2} L${cx},${cy - 1} L${cx - rx * 0.3},${cy + 2} L${cx - rx * 0.6},${cy - 1} Z" fill="#d4cfc0" stroke="#b8b3a3" stroke-width="0.5"/>`;
    const bottom = `<path class="dino-shell-bottom" d="M${cx - rx},${cy} L${cx - rx * 0.6},${cy - 1} L${cx - rx * 0.3},${cy + 2} L${cx},${cy - 1} L${cx + rx * 0.3},${cy + 2} L${cx + rx * 0.6},${cy - 1} L${cx + rx},${cy} Q${cx + rx},${cy + ry} ${cx},${cy + ry} Q${cx - rx},${cy + ry} ${cx - rx},${cy} Z" fill="#e8e3d4" stroke="#b8b3a3" stroke-width="0.5"/>`;
    return bottom + top;
}

function legs(cx, cy, bodyRY, visible) {
    if (!visible) return '';
    const y = cy + bodyRY - 1;
    return `<g class="dino-legs">
        <rect x="${cx - 6}" y="${y}" width="3.5" height="4" rx="1.5" fill="${ACCENT_DIM}"/>
        <rect x="${cx + 2.5}" y="${y}" width="3.5" height="4" rx="1.5" fill="${ACCENT_DIM}"/>
    </g>`;
}

function tail(cx, cy, bodyRX, visible) {
    if (!visible) return '';
    const tx = cx + bodyRX - 2;
    return `<path class="dino-tail" d="M${tx},${cy + 2} Q${tx + 6},${cy + 1} ${tx + 8},${cy - 2} Q${tx + 9},${cy - 4} ${tx + 7},${cy - 3} Q${tx + 5},${cy - 1} ${tx},${cy + 1}" fill="${ACCENT_DIM}" opacity="0.8"/>`;
}

// ---------- Full dinosaur SVG ----------

function buildDinoSVG(stage, mood) {
    const w = 48, h = 48;
    const cx = 22, cy = 24;

    // Body size grows with stage
    const bodyRX = [0, 8, 10, 12, 13][stage] || 10;
    const bodyRY = [0, 7, 9, 10, 11][stage] || 9;

    // Body color by mood
    let bodyColor = ACCENT;
    if (mood === 'sleeping') bodyColor = MUTED;
    else if (mood === 'distressed') bodyColor = DISTRESS;
    else if (mood === 'concerned') bodyColor = WARN;

    let svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" class="companion-dino companion-mood-${mood} companion-stage-${stage}">`;

    if (stage === 0) {
        // Egg only — with eyes peeking through crack
        svg += eggShell(cx, cy, 10, 12);
        svg += eyeEllipse(cx - 3, cy - 2, 1.5, 2, 'sleeping');
        svg += eyeEllipse(cx + 3, cy - 2, 1.5, 2, 'sleeping');
    } else {
        // Tail (stage 3+)
        svg += tail(cx, cy, bodyRX, stage >= 3);

        // Legs (stage 2+)
        svg += legs(cx, cy, bodyRY, stage >= 2);

        // Body
        svg += `<ellipse class="dino-body" cx="${cx}" cy="${cy}" rx="${bodyRX}" ry="${bodyRY}" fill="${bodyColor}"/>`;

        // Spikes
        const spikeCount = [0, 0, 2, 4, 5][stage] || 0;
        svg += spikes(spikeCount, cx, cy, bodyRY);

        // Shell remnants for stage 1
        if (stage === 1) {
            svg += `<path d="M${cx - 8},${cy + 4} Q${cx - 9},${cy + bodyRY + 3} ${cx},${cy + bodyRY + 2} Q${cx + 9},${cy + bodyRY + 3} ${cx + 8},${cy + 4}" fill="#e8e3d4" stroke="#b8b3a3" stroke-width="0.5" opacity="0.7"/>`;
        }

        // Eyes
        const eyeY = cy - bodyRY * 0.25;
        const eyeSpacing = bodyRX * 0.4;
        const eyeRX = 1.8 + stage * 0.15;
        const eyeRY = 2.2 + stage * 0.2;
        svg += eyeEllipse(cx - eyeSpacing, eyeY, eyeRX, eyeRY, mood);
        svg += eyeEllipse(cx + eyeSpacing, eyeY, eyeRX, eyeRY, mood);

        // Mouth
        svg += mouth(cx, eyeY + bodyRY * 0.45, mood);
    }

    svg += '</svg>';
    return svg;
}

// ---------- Stats label ----------

function buildStatsLabel(state) {
    const { engram_count, edge_count } = state;
    return `<div class="companion-stats">${engram_count} engrams · ${edge_count} edges</div>`;
}

// ---------- Idle action system ----------

const ACTIONS = {
    rock:        { duration: 800,  stages: [0],        moods: ['sleeping', 'happy', 'concerned', 'distressed'] },
    blink:       { duration: 300,  stages: [1,2,3,4],  moods: ['happy', 'concerned', 'distressed'] },
    'look-around': { duration: 600, stages: [1,2,3,4], moods: ['happy', 'concerned', 'distressed'] },
    hop:         { duration: 500,  stages: [2,3,4],    moods: ['happy', 'concerned'] },
    nod:         { duration: 400,  stages: [2,3,4],    moods: ['happy', 'concerned'] },
    'tail-wag':  { duration: 600,  stages: [3,4],      moods: ['happy'] },
    stomp:       { duration: 500,  stages: [3,4],      moods: ['happy'] },
    roar:        { duration: 600,  stages: [4],         moods: ['happy'] },
    spin:        { duration: 700,  stages: [4],         moods: ['happy'] },
    shiver:      { duration: 500,  stages: [2,3,4],    moods: ['distressed'] },
    peek:        { duration: 600,  stages: [2,3,4],    moods: ['concerned'] },
};

let _idleTimer = null;

function startIdleLoop(stage, mood) {
    stopIdleLoop();
    const available = Object.entries(ACTIONS).filter(([, a]) =>
        a.stages.includes(stage) && a.moods.includes(mood)
    ).map(([name]) => name);

    if (available.length === 0) return;

    function tick() {
        const action = available[Math.floor(Math.random() * available.length)];
        const el = document.querySelector('.companion-dino');
        if (!el) return;
        el.classList.add('action-' + action);
        setTimeout(() => el.classList.remove('action-' + action), ACTIONS[action].duration);
        _idleTimer = setTimeout(tick, 8000 + Math.random() * 7000);
    }
    _idleTimer = setTimeout(tick, 3000 + Math.random() * 5000);
}

function stopIdleLoop() {
    if (_idleTimer) { clearTimeout(_idleTimer); _idleTimer = null; }
}

// ---------- Public API ----------

let _lastState = null;

export async function loadCompanion() {
    const container = document.getElementById('companion');
    if (!container) return;

    try {
        const state = await fetch('/api/companion/state').then(r => r.json());
        _lastState = state;

        container.innerHTML = buildDinoSVG(state.growth_stage, state.mood) + buildStatsLabel(state);
        startIdleLoop(state.growth_stage, state.mood);

        // Milestone toast
        if (state.new_milestone) {
            const notify = window.notify || (msg => console.log(msg));
            notify(state.new_milestone.message);
        }
    } catch (e) {
        // Companion is optional
    }
}

export function destroyCompanion() {
    stopIdleLoop();
}
