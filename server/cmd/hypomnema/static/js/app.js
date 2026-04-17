// Hypomnema — Client-side SPA
// Vanilla JS, no framework, no build step.
// Feature parity with the Python NiceGUI version.

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const page = () => $('#page-content');

function bindAutogrowTextarea(el) {
    if (!el || el.dataset.autogrowBound === 'true') return;
    const resize = () => {
        el.style.height = 'auto';
        el.style.height = `${el.scrollHeight}px`;
    };
    el.dataset.autogrowBound = 'true';
    el.style.boxSizing = 'border-box';
    el.style.overflowY = 'hidden';
    el.addEventListener('input', resize);
    resize();
}

// ── Provider / model constants (matching Python utils.py) ──

const LLM_PROVIDERS = {
    claude: 'Anthropic Claude',
    google: 'Google Gemini',
    openai: 'OpenAI',
    ollama: 'Ollama (local)',
};

const LLM_MODELS = {
    claude: ['claude-sonnet-4-20250514', 'claude-3-5-haiku-20241022'],
    google: ['gemini-2.5-flash', 'gemini-3-flash-preview', 'gemini-2.5-pro', 'gemini-3-pro-preview'],
    openai: ['gpt-5.4', 'gpt-5-mini', 'gpt-4.1-mini', 'gpt-4o'],
    ollama: [],
};

const DEFAULT_LLM_MODELS = {
    claude: 'claude-sonnet-4-20250514',
    google: 'gemini-2.5-flash',
    openai: 'gpt-5-mini',
    ollama: 'llama3.1',
};

const API_KEY_FIELD = { claude: 'anthropic_api_key', google: 'google_api_key', openai: 'openai_api_key' };

const EMBEDDING_PROVIDERS = { openai: 'OpenAI Embeddings', google: 'Google Embeddings' };

const SOURCE_STYLES = {
    scribble: { label: 'scribble', color: '#9498a5', bg: 'rgba(148,152,165,0.07)' },
    file:     { label: 'file',     color: '#5e9eff', bg: 'rgba(94,158,255,0.07)' },
    url:      { label: 'url',      color: '#3ecfcf', bg: 'rgba(62,207,207,0.08)' },
    feed:     { label: 'feed',     color: '#56c9a0', bg: 'rgba(86,201,160,0.07)' },
    synthesis:{ label: 'synthesis',color: '#d4b06a', bg: 'rgba(212,176,106,0.07)' },
};

const HEAT_STYLES = {
    active:    { icon: 'local_fire_department', color: '#56c9a0', label: 'Active' },
    reference: { icon: 'menu_book',             color: '#5e9eff', label: 'Reference' },
    dormant:   { icon: 'bedtime',               color: '#3d4252', label: 'Dormant' },
};

// ── Router ──────────────────────────────────────────────────

const routes = {
    '/':         renderStream,
    '/search':   renderSearch,
    '/lint':     renderLint,
    '/settings': renderSettings,
    '/setup':    renderSetup,
    '/login':    renderLogin,
    '/viz':      renderViz,
};

window.navigate = function(path) {
    history.pushState(null, '', path);
    route();
};

async function route() {
    const path = location.pathname;

    // Restore layout if leaving viz
    if (path !== '/viz' && typeof restoreLayout === 'function') {
        restoreLayout();
    }
    // Clean up viz HUD/panel from previous render
    document.getElementById('hypo-detail-panel')?.remove();
    document.querySelectorAll('#app ~ div').forEach(el => {
        if (el.id !== 'toast-container') el.remove();
    });

    // Update active nav
    $$('.nav-item[data-route]').forEach(el => {
        el.classList.toggle('active', el.dataset.route === path);
    });

    // Dynamic routes
    if (path.startsWith('/documents/')) {
        renderDocument(path.split('/')[2]);
        return;
    }
    if (path.startsWith('/engrams/')) {
        renderEngram(path.split('/')[2]);
        return;
    }

    const handler = routes[path] || renderStream;
    handler();
}

// Intercept link clicks for SPA navigation
document.addEventListener('click', (e) => {
    const a = e.target.closest('a[href]');
    if (!a || a.target || a.href.startsWith('http')) return;
    e.preventDefault();
    navigate(a.getAttribute('href'));
});

window.addEventListener('popstate', route);

// ── Sidebar collapse ────────────────────────────────────────

window.toggleSidebar = function() {
    const sb = $('#sidebar');
    sb.classList.toggle('open');
};

document.addEventListener('DOMContentLoaded', () => {
    const collapseBtn = $('#collapse-btn');
    if (collapseBtn) {
        collapseBtn.addEventListener('click', () => {
            const sb = $('#sidebar');
            sb.classList.toggle('mini');
            document.body.classList.toggle('sidebar-mini');
            const icon = $('#collapse-icon');
            icon.textContent = sb.classList.contains('mini') ? 'chevron_right' : 'chevron_left';
        });
    }

    // Init
    initApp();
});

async function initApp() {
    try {
        const health = await api('/health');
        if (health.needs_setup) {
            navigate('/setup');
            return;
        }
        // Check auth in server mode — only redirect if passphrase is set
        const auth = await api('/auth/status');
        if (auth.auth_required && auth.has_passphrase && !auth.authenticated) {
            navigate('/login');
            return;
        }
    } catch (e) {
        // If health fails, just continue normally
    }

    // Apply font size from settings
    try {
        const s = await api('/settings');
        const scales = {small: 0.9, normal: 1, large: 1.1, xlarge: 1.2};
        document.documentElement.style.setProperty('--font-size-scale', scales[s.ui_font_size] || 1);
    } catch (e) { /* ignore */ }

    route();
    loadMinimap();
    import('/js/companion.js').then(m => m.loadCompanion()).catch(() => {});
}

// ── API helpers ─────────────────────────────────────────────

async function api(path, opts = {}) {
    const headers = { ...opts.headers };
    if (!(opts.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
    }
    const resp = await fetch('/api' + path, { headers, ...opts });
    if (resp.status === 401 && !path.startsWith('/auth/') && path !== '/health') {
        navigate('/login');
        throw new Error('authentication required');
    }
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`${resp.status}: ${text}`);
    }
    return resp.json();
}

function timeAgo(iso) {
    if (!iso) return '';
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return `${Math.floor(diff)}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
    return new Date(iso).toLocaleDateString();
}

function escapeHTML(s) {
    const div = document.createElement('div');
    div.textContent = s || '';
    return div.innerHTML;
}

function notify(msg, type = 'info') {
    const container = $('#toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

function materialIcon(name, style = '') {
    return `<span class="material-icons" style="font-size:inherit;vertical-align:middle;${style}">${name}</span>`;
}

// ── Document card component (matching NiceGUI render_document_card) ──

function documentCard(doc, { showScore = false, score = null, matchType = null } = {}) {
    const src = doc.source_type || 'scribble';
    const style = SOURCE_STYLES[src] || SOURCE_STYLES.scribble;
    const title = doc.tidy_title || doc.title || 'Untitled';
    const preview = (doc.tidy_text || doc.text || '').slice(0, 280);
    const heatTier = doc.heat_tier;
    const heatStyle = heatTier ? HEAT_STYLES[heatTier] : null;

    let badgeRow = `<span class="source-badge" style="color:${style.color};background:${style.bg}">${style.label}</span>`;

    if (showScore && score != null && matchType) {
        const matchColors = { hybrid: '#5e9eff', semantic: '#9b8afb', keyword: '#3ecfcf' };
        const mc = matchColors[matchType] || '#636978';
        badgeRow += ` <span class="source-badge" style="color:${mc};background:rgba(255,255,255,0.03)">${matchType} ${score.toFixed(3)}</span>`;
    } else {
        if (doc.processed >= 2) {
            badgeRow += ` <span class="material-icons" style="font-size:12px;color:#56c9a0">check_circle</span>`;
        } else {
            badgeRow += ` <span class="material-icons animate-pulse-dot" style="font-size:12px;color:#d4b06a">pending</span>`;
        }
        if (doc.mime_type) {
            badgeRow += ` <span class="text-muted text-xs">${escapeHTML(doc.mime_type)}</span>`;
        }
    }

    if (heatStyle) {
        badgeRow += `<span style="margin-left:auto"><span class="material-icons" style="font-size:11px;color:${heatStyle.color}" title="${heatStyle.label}">${heatStyle.icon}</span></span>`;
    }

    return `<a href="/documents/${doc.id}" class="card doc-card animate-fade-up" style="text-decoration:none;color:inherit;display:block;border-left:2px solid ${style.color}">
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem">${badgeRow}</div>
        <div class="card-title">${escapeHTML(title)}</div>
        ${preview ? `<div class="card-text">${escapeHTML(preview)}</div>` : ''}
        <div class="card-meta"><span>${timeAgo(doc.created_at)}</span></div>
    </a>`;
}

// ── Pages ───────────────────────────────────────────────────

// --- Login ---

async function renderLogin() {
    page().innerHTML = `
        <div style="max-width:320px;margin:4rem auto;text-align:center">
            <div class="text-display-lg" style="letter-spacing:0.15em;text-transform:uppercase;margin-bottom:0.25rem">hypomnema</div>
            <div style="color:var(--fg-dim);font-size:9px;letter-spacing:0.1em;margin-bottom:2rem">AUTHENTICATION REQUIRED</div>
            <div id="login-form">
                <input type="password" id="login-pass" placeholder="Passphrase..." style="margin-bottom:0.75rem">
                <div style="display:flex;gap:0.5rem;justify-content:center">
                    <button id="login-btn">Login</button>
                </div>
                <div id="login-status" style="margin-top:0.75rem;font-size:11px"></div>
            </div>
            <div id="setup-pass-form" style="display:none">
                <div style="font-size:11px;color:var(--fg-muted);margin-bottom:0.75rem">No passphrase set. Create one to continue.</div>
                <input type="password" id="setup-pass" placeholder="New passphrase (min 8 chars)..." style="margin-bottom:0.75rem">
                <div style="display:flex;gap:0.5rem;justify-content:center">
                    <button id="setup-pass-btn">Set Passphrase</button>
                </div>
                <div id="setup-pass-status" style="margin-top:0.75rem;font-size:11px"></div>
            </div>
        </div>`;

    try {
        const auth = await api('/auth/status');
        if (!auth.has_passphrase) {
            $('#login-form').style.display = 'none';
            $('#setup-pass-form').style.display = 'block';
        }
    } catch (e) { /* ignore */ }

    $('#login-btn')?.addEventListener('click', async () => {
        const pass = $('#login-pass').value;
        if (!pass) return;
        try {
            await api('/auth/login', { method: 'POST', body: JSON.stringify({ passphrase: pass }) });
            navigate('/');
        } catch (e) {
            $('#login-status').innerHTML = `<span class="status-error">Invalid passphrase</span>`;
        }
    });

    $('#setup-pass-btn')?.addEventListener('click', async () => {
        const pass = $('#setup-pass').value;
        if (!pass || pass.length < 8) {
            $('#setup-pass-status').innerHTML = `<span class="status-error">Minimum 8 characters</span>`;
            return;
        }
        try {
            await api('/auth/setup', { method: 'POST', body: JSON.stringify({ passphrase: pass }) });
            navigate('/');
        } catch (e) {
            $('#setup-pass-status').innerHTML = `<span class="status-error">${escapeHTML(e.message)}</span>`;
        }
    });
}

// --- Setup ---

async function renderSetup() {
    const state = {
        emb_provider: 'google', emb_validated: false,
        llm_provider: 'google', llm_tested: false,
        step: 1,
    };

    page().innerHTML = `
        <div style="text-align:center;margin-bottom:2rem">
            <div class="text-display-lg" style="letter-spacing:0.15em;text-transform:uppercase">hypomnema</div>
            <div style="color:var(--fg-dim);font-size:9px;letter-spacing:0.1em">FIRST-RUN SETUP</div>
        </div>
        <div class="stepper">
            <div class="stepper-step active" data-step="1" id="step-1">
                <div class="stepper-title">${materialIcon('memory')} Embedding Provider</div>
                <div class="stepper-content">
                    <div style="font-size:11px;color:var(--fg-muted);margin-bottom:1rem">Choose how document and engram embeddings are computed.</div>
                    <label class="input-label">Provider</label>
                    <select id="setup-emb-provider" style="margin-bottom:0.75rem">
                        ${Object.entries(EMBEDDING_PROVIDERS).map(([k, v]) => `<option value="${k}" ${k === 'google' ? 'selected' : ''}>${v}</option>`).join('')}
                    </select>
                    <label class="input-label">API Key</label>
                    <input type="password" id="setup-emb-key" placeholder="Enter API key..." style="margin-bottom:0.75rem">
                    <div id="setup-emb-status" style="font-size:11px;margin-bottom:0.75rem"></div>
                    <div style="display:flex;gap:0.5rem">
                        <button id="setup-emb-validate">Validate</button>
                        <button id="setup-emb-next">Next</button>
                    </div>
                </div>
            </div>
            <div class="stepper-step" data-step="2" id="step-2">
                <div class="stepper-title">${materialIcon('smart_toy')} LLM Provider</div>
                <div class="stepper-content" id="step-2-content" style="display:none">
                    <div style="font-size:11px;color:var(--fg-muted);margin-bottom:1rem">Choose the LLM that powers ontology extraction.</div>
                    <label class="input-label">Provider</label>
                    <select id="setup-llm-provider" style="margin-bottom:0.75rem">
                        ${Object.entries(LLM_PROVIDERS).map(([k, v]) => `<option value="${k}" ${k === 'google' ? 'selected' : ''}>${v}</option>`).join('')}
                    </select>
                    <label class="input-label">Model</label>
                    <select id="setup-llm-model" style="margin-bottom:0.75rem">
                        ${LLM_MODELS.google.map(m => `<option value="${m}" ${m === 'gemini-2.5-flash' ? 'selected' : ''}>${m}</option>`).join('')}
                    </select>
                    <div id="setup-llm-custom-row" style="display:none">
                        <label class="input-label">Custom model name</label>
                        <input type="text" id="setup-llm-custom" placeholder="e.g. llama3.1" style="margin-bottom:0.75rem">
                    </div>
                    <div id="setup-llm-key-row">
                        <label class="input-label">API Key</label>
                        <input type="password" id="setup-llm-key" placeholder="Enter API key..." style="margin-bottom:0.75rem">
                    </div>
                    <div id="setup-llm-ollama-row" style="display:none">
                        <label class="input-label">Ollama Base URL</label>
                        <input type="text" id="setup-llm-ollama-url" value="http://localhost:11434" style="margin-bottom:0.75rem">
                    </div>
                    <div id="setup-llm-openai-row" style="display:none">
                        <label class="input-label">OpenAI Base URL (optional)</label>
                        <input type="text" id="setup-llm-openai-url" placeholder="Leave empty for default" style="margin-bottom:0.75rem">
                    </div>
                    <div id="setup-llm-status" style="font-size:11px;margin-bottom:0.75rem"></div>
                    <div style="display:flex;gap:0.5rem">
                        <button id="setup-llm-back">Back</button>
                        <button id="setup-llm-test">Test Connection</button>
                        <button id="setup-llm-complete">Complete Setup</button>
                    </div>
                </div>
            </div>
        </div>`;

    // Step 1: Embedding validation
    $('#setup-emb-validate').addEventListener('click', async () => {
        const provider = $('#setup-emb-provider').value;
        const apiKey = $('#setup-emb-key').value;
        if (!apiKey) {
            $('#setup-emb-status').innerHTML = `<span class="status-error">API key is required.</span>`;
            return;
        }
        $('#setup-emb-status').innerHTML = `<span class="status-muted">Validating...</span>`;
        try {
            await api('/settings/check-connection', {
                method: 'POST',
                body: JSON.stringify({ kind: 'embedding', provider, api_key: apiKey }),
            });
            state.emb_validated = true;
            state.emb_provider = provider;
            $('#setup-emb-status').innerHTML = `<span class="status-ok">Connection validated.</span>`;
        } catch (e) {
            state.emb_validated = false;
            $('#setup-emb-status').innerHTML = `<span class="status-error">Validation failed: ${escapeHTML(e.message)}</span>`;
        }
    });

    $('#setup-emb-next').addEventListener('click', () => {
        if (!state.emb_validated) {
            $('#setup-emb-status').innerHTML = `<span class="status-error">Please validate before continuing.</span>`;
            return;
        }
        state.step = 2;
        $('#step-1').classList.replace('active', 'done');
        $('#step-2').classList.add('active');
        $('#step-2-content').style.display = 'block';
    });

    // Step 2: LLM provider
    $('#setup-llm-provider').addEventListener('change', () => {
        const p = $('#setup-llm-provider').value;
        state.llm_provider = p;
        state.llm_tested = false;
        $('#setup-llm-status').innerHTML = '';

        const models = LLM_MODELS[p] || [];
        const modelSel = $('#setup-llm-model');
        modelSel.innerHTML = models.length
            ? models.map(m => `<option value="${m}">${m}</option>`).join('')
            : '<option value="(custom)">(custom)</option>';
        if (models.length) modelSel.value = DEFAULT_LLM_MODELS[p] || models[0];

        $('#setup-llm-custom-row').style.display = p === 'ollama' ? 'block' : 'none';
        $('#setup-llm-key-row').style.display = p in API_KEY_FIELD ? 'block' : 'none';
        $('#setup-llm-ollama-row').style.display = p === 'ollama' ? 'block' : 'none';
        $('#setup-llm-openai-row').style.display = p === 'openai' ? 'block' : 'none';
    });

    $('#setup-llm-test').addEventListener('click', async () => {
        const provider = $('#setup-llm-provider').value;
        const model = provider === 'ollama'
            ? ($('#setup-llm-custom').value || DEFAULT_LLM_MODELS.ollama)
            : ($('#setup-llm-model').value || DEFAULT_LLM_MODELS[provider]);
        const apiKey = $('#setup-llm-key').value || '';
        let baseURL = '';
        if (provider === 'ollama') baseURL = $('#setup-llm-ollama-url').value;
        if (provider === 'openai') baseURL = $('#setup-llm-openai-url').value;

        $('#setup-llm-status').innerHTML = `<span class="status-muted">Testing connection...</span>`;
        try {
            await api('/settings/check-connection', {
                method: 'POST',
                body: JSON.stringify({ kind: 'llm', provider, model, api_key: apiKey, base_url: baseURL }),
            });
            state.llm_tested = true;
            state.llm_provider = provider;
            $('#setup-llm-status').innerHTML = `<span class="status-ok">Connected: ${escapeHTML(model)} is reachable.</span>`;
        } catch (e) {
            state.llm_tested = false;
            $('#setup-llm-status').innerHTML = `<span class="status-error">Connection failed: ${escapeHTML(e.message)}</span>`;
        }
    });

    $('#setup-llm-back').addEventListener('click', () => {
        state.step = 1;
        $('#step-2').classList.remove('active');
        $('#step-2-content').style.display = 'none';
        $('#step-1').classList.replace('done', 'active');
    });

    $('#setup-llm-complete').addEventListener('click', async () => {
        if (!state.llm_tested) {
            $('#setup-llm-status').innerHTML = `<span class="status-warning">Please test the connection first.</span>`;
            return;
        }
        $('#setup-llm-status').innerHTML = `<span class="status-muted">Completing setup...</span>`;

        const provider = $('#setup-llm-provider').value;
        const model = provider === 'ollama'
            ? ($('#setup-llm-custom').value || DEFAULT_LLM_MODELS.ollama)
            : ($('#setup-llm-model').value || DEFAULT_LLM_MODELS[provider]);

        const body = {
            embedding_provider: state.emb_provider,
            llm_provider: provider,
            llm_model: model,
        };

        // API keys
        const embKey = $('#setup-emb-key').value;
        const llmKey = $('#setup-llm-key').value;

        if (state.emb_provider === 'google' || provider === 'google') {
            body.google_api_key = embKey || llmKey;
        }
        if (state.emb_provider === 'openai') body.openai_api_key = embKey;
        if (provider === 'openai') body.openai_api_key = llmKey || body.openai_api_key;
        if (provider === 'claude') body.anthropic_api_key = llmKey;
        if (provider === 'ollama') body.ollama_base_url = $('#setup-llm-ollama-url').value;
        if (provider === 'openai' && $('#setup-llm-openai-url').value) {
            body.openai_base_url = $('#setup-llm-openai-url').value;
        }

        try {
            await api('/settings/setup', { method: 'POST', body: JSON.stringify(body) });
            notify('Setup complete!', 'positive');
            navigate('/');
        } catch (e) {
            $('#setup-llm-status').innerHTML = `<span class="status-error">Setup failed: ${escapeHTML(e.message)}</span>`;
        }
    });
}

// --- Stream ---

let _allDocs = [];
let _pollTimer = null;

async function renderStream() {
    page().innerHTML = `
        <div class="input-area" id="drop-zone">
            <textarea id="scribble-input" rows="3" placeholder="Drop a thought, paste a URL, or drag a file..."></textarea>
            <div style="display:flex;gap:0.5rem;margin-top:0.5rem;justify-content:flex-end;align-items:center">
                <label style="cursor:pointer">
                    <button type="button" onclick="this.parentElement.querySelector('input').click()">
                        ${materialIcon('attach_file')} Upload
                    </button>
                    <input type="file" style="display:none" accept=".pdf,.docx,.md,.txt" onchange="handleFileUpload(this)">
                </label>
                <button onclick="submitScribble()">${materialIcon('send')} Submit</button>
            </div>
        </div>
        <div class="filter-tabs" id="heat-tabs">
            <button class="filter-tab active" style="color:#9498a5" data-tier="all">All</button>
            <button class="filter-tab" style="color:#56c9a0" data-tier="active">Active</button>
            <button class="filter-tab" style="color:#5e9eff" data-tier="reference">Reference</button>
            <button class="filter-tab" style="color:#3d4252" data-tier="dormant">Dormant</button>
        </div>
        <div id="doc-list"><span class="spinner"></span> Loading...</div>`;

    bindAutogrowTextarea($('#scribble-input'));

    // Drag-and-drop
    const zone = $('#drop-zone');
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('dragover');
        if (e.dataTransfer?.files.length) {
            uploadFileObj(e.dataTransfer.files[0]);
        }
    });

    // Heat filter tabs
    $$('#heat-tabs .filter-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            $$('#heat-tabs .filter-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const tier = tab.dataset.tier;
            const filtered = tier === 'all' ? _allDocs : _allDocs.filter(d => d.heat_tier === tier);
            renderDocList(filtered);
        });
    });

    try {
        const docs = await api('/documents?days=100');
        _allDocs = docs || [];
        renderDocList(_allDocs);
        startPollIfNeeded();
    } catch (e) {
        $('#doc-list').innerHTML = `<div style="color:var(--fg-dim);font-size:11px">Failed to load documents.</div>`;
    }
}

function renderDocList(docs) {
    const list = $('#doc-list');
    if (!list) return;
    if (!docs || docs.length === 0) {
        list.innerHTML = '<div style="color:var(--fg-muted);font-size:11px;text-align:center;padding:2rem 0">No documents yet.</div>';
        return;
    }
    list.innerHTML = docs.map(d => documentCard(d)).join('')
        + `<div style="text-align:center;font-size:10px;color:var(--fg-muted);margin-top:1rem">${docs.length} documents</div>`;
}

function startPollIfNeeded() {
    if (_pollTimer) clearInterval(_pollTimer);
    const hasUnprocessed = _allDocs.some(d => !d.processed || d.processed < 2);
    if (!hasUnprocessed) return;
    _pollTimer = setInterval(async () => {
        try {
            const docs = await api('/documents?days=100');
            const oldSnap = _allDocs.map(d => `${d.id}:${d.processed}`).join(',');
            const newSnap = (docs || []).map(d => `${d.id}:${d.processed}`).join(',');
            if (oldSnap !== newSnap) {
                _allDocs = docs || [];
                const active = document.querySelector('#heat-tabs .filter-tab.active');
                const tier = active?.dataset.tier || 'all';
                const filtered = tier === 'all' ? _allDocs : _allDocs.filter(d => d.heat_tier === tier);
                renderDocList(filtered);
            }
            if (!_allDocs.some(d => !d.processed || d.processed < 2)) {
                clearInterval(_pollTimer);
                _pollTimer = null;
            }
        } catch (e) { /* ignore */ }
    }, 5000);
}

window.submitScribble = async function() {
    const input = $('#scribble-input');
    const text = input.value.trim();
    if (!text) return;

    try {
        const urlMatch = text.match(/^https?:\/\/\S+$/);
        if (urlMatch) {
            await api('/documents/urls', { method: 'POST', body: JSON.stringify({ url: text }) });
            notify('URL fetched', 'positive');
        } else {
            await api('/documents/scribbles', { method: 'POST', body: JSON.stringify({ text }) });
            notify('Scribble saved', 'positive');
        }
        input.value = '';
        input.style.height = 'auto';
        await renderStream();
    } catch (e) {
        notify(`Failed: ${e.message}`, 'negative');
    }
};

window.handleFileUpload = function(input) {
    const file = input.files[0];
    if (file) uploadFileObj(file);
    input.value = '';
};

async function uploadFileObj(file) {
    const form = new FormData();
    form.append('file', file);
    try {
        const resp = await fetch('/api/documents/files', { method: 'POST', body: form });
        if (!resp.ok) throw new Error(await resp.text());
        notify(`Uploaded: ${file.name}`, 'positive');
        await renderStream();
    } catch (e) {
        notify(`Upload failed: ${e.message}`, 'negative');
    }
}

// --- Search ---

async function renderSearch() {
    let currentMode = 'Documents';
    let searchTimer;

    page().innerHTML = `
        <div class="text-display-lg" style="margin-bottom:1rem">Search</div>
        <div style="position:relative;margin-bottom:0.75rem">
            <span class="material-icons" style="position:absolute;left:10px;top:50%;transform:translateY(-50%);font-size:18px;color:var(--fg-dim)">search</span>
            <input type="text" id="search-input" placeholder="Search documents and knowledge..." style="padding-left:36px;font-size:13px">
        </div>
        <div class="mode-toggle">
            <button class="active" data-mode="Documents">Documents</button>
            <button data-mode="Knowledge">Knowledge</button>
        </div>
        <div id="search-status" style="font-size:11px;color:var(--fg-muted);margin-bottom:0.5rem"></div>
        <div id="search-results"></div>`;

    // Mode toggle
    $$('.mode-toggle button').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.mode-toggle button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentMode = btn.dataset.mode;
            doSearch();
        });
    });

    async function doSearch() {
        const q = $('#search-input')?.value?.trim();
        if (!q) {
            $('#search-results').innerHTML = '';
            $('#search-status').textContent = '';
            return;
        }

        if (currentMode === 'Documents') {
            try {
                const results = await api(`/search/documents?q=${encodeURIComponent(q)}`);
                if (!results || results.length === 0) {
                    $('#search-results').innerHTML = '<div style="color:var(--fg-muted);font-size:11px;text-align:center;padding:2rem 0">No documents found.</div>';
                    $('#search-status').textContent = '';
                } else {
                    const docIds = results.slice(0, 10).map(d => d.id);
                    $('#search-results').innerHTML = results.map(d =>
                        documentCard(d, { showScore: true, score: d.score, matchType: d.match_type })
                    ).join('')
                    + `<button onclick="synthesizeResults('${escapeHTML(q)}', ${JSON.stringify(docIds)})" style="margin-top:1rem">${materialIcon('auto_awesome')} Synthesize results</button>`;
                    const types = [...new Set(results.map(r => r.match_type))];
                    const searchType = types.includes('hybrid') ? 'hybrid' : types[0] || '';
                    $('#search-status').textContent = `${results.length} result${results.length !== 1 ? 's' : ''} (${searchType})`;
                }
            } catch (e) {
                $('#search-results').innerHTML = `<div style="color:var(--fg-dim);font-size:11px">Search failed.</div>`;
            }
        } else {
            try {
                const results = await api(`/search/knowledge?q=${encodeURIComponent(q)}`);
                if (!results || results.length === 0) {
                    $('#search-results').innerHTML = '<div style="color:var(--fg-muted);font-size:11px;text-align:center;padding:2rem 0">No knowledge graph results found.</div>';
                    $('#search-status').textContent = '';
                } else {
                    // Group by engram, show edges
                    const grouped = {};
                    for (const r of results) {
                        if (!grouped[r.engram_id]) grouped[r.engram_id] = { name: r.engram_name, edges: [] };
                        grouped[r.engram_id].edges.push(r);
                    }
                    let html = '<div class="section-label">Engrams & Edges</div>';
                    for (const [eid, g] of Object.entries(grouped)) {
                        html += `<div class="card animate-fade-up" style="border-left:2px solid var(--accent);margin-bottom:0.5rem">
                            <a href="/engrams/${eid}" class="card-title" style="text-decoration:none;color:inherit;display:block">${escapeHTML(g.name)}</a>
                            ${g.edges.map(e => {
                                const confColor = e.confidence >= 0.7 ? '#56c9a0' : e.confidence >= 0.4 ? '#d4b06a' : '#e06c75';
                                return `<div style="font-size:11px;padding:0.2rem 0;display:flex;gap:0.4rem;align-items:center;flex-wrap:wrap">
                                    <span style="color:var(--fg)">${escapeHTML(e.source_name)}</span>
                                    <span class="source-badge" style="color:var(--accent);background:var(--accent-soft)">${escapeHTML(e.predicate)}</span>
                                    <span style="color:var(--fg)">${escapeHTML(e.target_name)}</span>
                                    <span style="color:${confColor};font-size:10px">${(e.confidence * 100).toFixed(0)}%</span>
                                </div>`;
                            }).join('')}
                        </div>`;
                    }
                    $('#search-results').innerHTML = html;
                    const engramCount = Object.keys(grouped).length;
                    const edgeCount = results.length;
                    $('#search-status').textContent = `${engramCount} engram${engramCount !== 1 ? 's' : ''}, ${edgeCount} edge${edgeCount !== 1 ? 's' : ''}`;
                }
            } catch (e) {
                $('#search-results').innerHTML = `<div style="color:var(--fg-dim);font-size:11px">Search failed.</div>`;
            }
        }
    }

    $('#search-input').addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(doSearch, 300);
    });
}

// --- Document detail ---

async function renderDocument(id) {
    page().innerHTML = `<span class="spinner"></span>`;
    try {
        const [docResp, related] = await Promise.all([
            api(`/documents/${id}`),
            api(`/documents/${id}/related`),
        ]);
        const doc = docResp.document;
        const engrams = docResp.engrams || [];
        const src = doc.source_type || 'scribble';
        const style = SOURCE_STYLES[src] || SOURCE_STYLES.scribble;
        const title = doc.tidy_title || doc.title || 'Untitled';
        const isScribble = src === 'scribble';
        const heatStyle = doc.heat_tier ? HEAT_STYLES[doc.heat_tier] : null;

        // Badge row
        let badgeRow = `<span class="source-badge" style="color:${style.color};background:${style.bg}">${style.label}</span>`;
        if (doc.processed >= 2) {
            badgeRow += ` <span class="material-icons" style="font-size:12px;color:#56c9a0">check_circle</span>`;
        } else {
            badgeRow += ` <span class="material-icons animate-pulse-dot" style="font-size:12px;color:#d4b06a">pending</span>`;
        }
        if (doc.mime_type) badgeRow += ` <span class="text-muted text-xs">${escapeHTML(doc.mime_type)}</span>`;

        // TL;DR block
        let contentHTML = '';
        const tidyText = doc.tidy_text || '';
        const rawText = doc.text || '';

        if (tidyText && tidyText.length < 600) {
            contentHTML += `<div class="tldr-block">
                <div class="tldr-label">TL;DR</div>
                <div class="tldr-text">${escapeHTML(tidyText)}</div>
            </div>`;
            contentHTML += `<div style="font-size:13px;line-height:1.7;white-space:pre-wrap;color:var(--fg)">${escapeHTML(rawText)}</div>`;
        } else if (tidyText) {
            contentHTML += `<div style="font-size:13px;line-height:1.7;white-space:pre-wrap;color:var(--fg)">${escapeHTML(tidyText)}</div>`;
        } else {
            contentHTML += `<div style="font-size:13px;line-height:1.7;white-space:pre-wrap;color:var(--fg)">${escapeHTML(rawText)}</div>`;
        }

        // Annotation block
        if (!isScribble && doc.annotation) {
            contentHTML += `<div class="annotation-block" style="margin-top:1rem">
                <div class="annotation-label">Your notes</div>
                <div style="margin-top:0.25rem;font-size:13px;line-height:1.6;white-space:pre-wrap;color:rgba(200,204,214,0.8)">${escapeHTML(doc.annotation)}</div>
            </div>`;
        }

        // Engrams
        let engramHTML = '';
        if (engrams.length) {
            engramHTML = `<div style="padding-top:1.5rem;border-top:1px solid var(--border)">
                <div class="section-label">Engrams</div>
                <div style="display:flex;flex-wrap:wrap;gap:0.5rem">
                    ${engrams.map(e => `<a href="/engrams/${e.id}" class="engram-link">${escapeHTML(e.canonical_name)}</a>`).join('')}
                </div>
            </div>`;
        }

        // Related docs
        let relatedHTML = '';
        if (related && related.length) {
            relatedHTML = `<div style="padding-top:1.5rem;margin-top:1.5rem;border-top:1px solid var(--border)">
                <div class="section-label">Related Documents</div>
                ${related.map(r => {
                    const rTitle = r.tidy_title || r.title || 'Untitled';
                    return `<a href="/documents/${r.id}" style="display:block;padding:0.5rem 0.75rem;border-radius:6px;text-decoration:none;color:var(--fg);font-family:var(--font-display);font-size:11px;transition:background 0.15s;margin-bottom:0.25rem" onmouseenter="this.style.background='var(--accent-soft)'" onmouseleave="this.style.background='transparent'">${escapeHTML(rTitle)}</a>`;
                }).join('')}
            </div>`;
        }

        // Edit button label
        let editLabel, editIcon;
        if (isScribble) { editLabel = 'Edit'; editIcon = 'edit'; }
        else if (doc.annotation) { editLabel = 'Edit notes'; editIcon = 'edit_note'; }
        else { editLabel = 'Annotate'; editIcon = 'note_add'; }

        page().innerHTML = `
            <div class="animate-fade-up">
                <button onclick="navigate('/')" style="margin-bottom:1rem">${materialIcon('arrow_back')} Stream</button>
                <article style="padding-left:1rem;border-left:2px solid ${style.color}">
                    <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem">${badgeRow}</div>
                    <div class="text-display-lg" style="margin-bottom:0.25rem">${escapeHTML(title)}</div>
                    <div style="font-size:10px;color:rgba(99,105,120,0.6);margin-bottom:1rem">${timeAgo(doc.created_at)}</div>
                    <div id="doc-content">${contentHTML}</div>
                    ${engramHTML}
                    ${relatedHTML}
                    <div style="display:flex;gap:0.5rem;margin-top:1.5rem">
                        <button id="edit-btn" onclick="enterEditMode('${id}', ${isScribble})">${materialIcon(editIcon)} ${editLabel}</button>
                        <button class="danger" onclick="deleteDocument('${id}')">${materialIcon('delete')} Delete</button>
                    </div>
                </article>
            </div>`;

        // Store doc data for edit mode
        window._currentDoc = doc;
    } catch (e) {
        page().innerHTML = `<div style="color:#e06c75;font-size:13px">Failed to load document: ${escapeHTML(e.message)}</div>`;
    }
}

window.enterEditMode = function(docId, isScribble) {
    const doc = window._currentDoc;
    if (!doc) return;
    const content = $('#doc-content');
    const editBtn = $('#edit-btn');
    editBtn.style.display = 'none';

    if (isScribble) {
        content.innerHTML = `
            <label class="input-label">Title</label>
            <input type="text" id="edit-title" value="${escapeHTML(doc.title || doc.tidy_title || '')}" style="margin-bottom:0.75rem">
            <label class="input-label">Text</label>
            <textarea id="edit-text" rows="8">${escapeHTML(doc.text || '')}</textarea>
            <div style="display:flex;gap:0.5rem;margin-top:0.75rem">
                <button style="color:#56c9a0" onclick="saveEdit('${docId}', true)">${materialIcon('save')} Save</button>
                <button onclick="renderDocument('${docId}')">${materialIcon('close')} Cancel</button>
            </div>`;
        bindAutogrowTextarea($('#edit-text'));
    } else {
        // Show original content read-only, then annotation textarea
        const tidyText = doc.tidy_text || '';
        const rawText = doc.text || '';
        let readOnly = '';
        if (tidyText) {
            readOnly = `<div style="font-size:13px;line-height:1.7;white-space:pre-wrap;color:var(--fg);margin-bottom:1rem">${escapeHTML(tidyText || rawText)}</div>`;
        } else {
            readOnly = `<div style="font-size:13px;line-height:1.7;white-space:pre-wrap;color:var(--fg);margin-bottom:1rem">${escapeHTML(rawText)}</div>`;
        }
        content.innerHTML = `
            ${readOnly}
            <div style="border-top:1px solid var(--border);padding-top:1rem;margin-top:1rem">
                <div class="section-label">Your notes</div>
                <textarea id="edit-annotation" rows="6" placeholder="Add your notes about this document...">${escapeHTML(doc.annotation || '')}</textarea>
                <div style="display:flex;gap:0.5rem;margin-top:0.75rem">
                    <button style="color:#56c9a0" onclick="saveEdit('${docId}', false)">${materialIcon('save')} Save</button>
                    <button onclick="renderDocument('${docId}')">${materialIcon('close')} Cancel</button>
                </div>
            </div>`;
        bindAutogrowTextarea($('#edit-annotation'));
    }
};

window.deleteDocument = async function(docId) {
    if (!confirm('Delete this document and its engram links?')) return;
    try {
        await api(`/documents/${docId}`, { method: 'DELETE' });
        notify('Document deleted', 'info');
        navigate('/');
    } catch (e) {
        notify(`Delete failed: ${e.message}`, 'negative');
    }
};

window.regenerateArticle = async function(engramId) {
    notify('Regenerating article...', 'info');
    try {
        await api(`/engrams/${engramId}/article/regenerate`, { method: 'POST' });
        notify('Article regenerated', 'positive');
        renderEngram(engramId);
    } catch (e) {
        notify(`Failed: ${e.message}`, 'negative');
    }
};

window.saveEdit = async function(docId, isScribble) {
    const body = {};
    if (isScribble) {
        body.text = $('#edit-text')?.value || '';
        body.title = $('#edit-title')?.value || '';
    } else {
        body.annotation = $('#edit-annotation')?.value || '';
    }

    try {
        await api(`/documents/${docId}`, { method: 'PATCH', body: JSON.stringify(body) });
        notify('Saved', 'positive');
        renderDocument(docId);
    } catch (e) {
        notify(`Save failed: ${e.message}`, 'negative');
    }
};

// --- Engram detail ---

async function renderEngram(id) {
    page().innerHTML = `<span class="spinner"></span>`;
    try {
        const { engram, edges, documents } = await api(`/engrams/${id}`);

        // Group edges
        const outgoing = (edges || []).filter(e => e.source_engram_id === id);
        const incoming = (edges || []).filter(e => e.target_engram_id === id);

        function edgeRow(edge, direction) {
            const linkedId = direction === 'outgoing' ? edge.target_engram_id : edge.source_engram_id;
            const linkedName = direction === 'outgoing' ? edge.target_name : edge.source_name;
            const conf = edge.confidence || 0;
            return `<div style="display:flex;align-items:center;gap:0.5rem;padding:0.25rem 0">
                <a href="/engrams/${linkedId}" class="engram-link">${escapeHTML(linkedName)}</a>
                <span style="color:var(--fg-muted);font-style:italic;font-size:11px">${escapeHTML(edge.predicate)}</span>
                <span style="color:rgba(99,105,120,0.5);font-size:10px">${Math.round(conf * 100)}%</span>
            </div>`;
        }

        let edgesHTML = '';
        if (outgoing.length || incoming.length) {
            if (outgoing.length) {
                edgesHTML += `<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.05em;color:rgba(99,105,120,0.5);margin-top:0.5rem;margin-bottom:0.25rem">Outgoing</div>`;
                edgesHTML += outgoing.map(e => edgeRow(e, 'outgoing')).join('');
            }
            if (incoming.length) {
                edgesHTML += `<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.05em;color:rgba(99,105,120,0.5);margin-top:1rem;margin-bottom:0.25rem">Incoming</div>`;
                edgesHTML += incoming.map(e => edgeRow(e, 'incoming')).join('');
            }
        } else {
            edgesHTML = '<div style="color:var(--fg-muted);font-size:11px">No edges.</div>';
        }

        let docsHTML = '';
        if (documents && documents.length) {
            docsHTML = documents.map(doc => {
                const src = doc.source_type || 'scribble';
                const s = SOURCE_STYLES[src] || SOURCE_STYLES.scribble;
                const title = doc.tidy_title || doc.title || 'Untitled';
                const preview = (doc.tidy_text || doc.text || '').slice(0, 200);
                return `<a href="/documents/${doc.id}" class="card doc-card" style="text-decoration:none;color:inherit;display:block;border-left:2px solid ${s.color}">
                    <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem">
                        <span class="source-badge" style="color:${s.color};background:${s.bg}">${s.label}</span>
                    </div>
                    <div class="card-title">${escapeHTML(title)}</div>
                    ${preview ? `<div class="card-text" style="-webkit-line-clamp:2">${escapeHTML(preview)}</div>` : ''}
                </a>`;
            }).join('');
        } else {
            docsHTML = '<div style="color:var(--fg-muted);font-size:11px">No source documents.</div>';
        }

        page().innerHTML = `
            <div class="animate-fade-up">
                <button onclick="navigate('/')" style="margin-bottom:1rem">${materialIcon('arrow_back')} Stream</button>
                <div class="text-display-lg" style="margin-bottom:0.25rem">${escapeHTML(engram.canonical_name)}</div>
                ${engram.description ? `<div style="color:var(--fg-muted);font-size:11px;line-height:1.5;margin-bottom:1rem">${escapeHTML(engram.description)}</div>` : ''}
                ${engram.article ? `
                <div style="padding-top:1rem;margin-bottom:1.5rem;border-top:1px solid var(--border)">
                    <div class="section-label">Article</div>
                    <div style="font-size:13px;line-height:1.7;white-space:pre-wrap;color:var(--fg)">${escapeHTML(engram.article)}</div>
                    <button style="margin-top:0.5rem" onclick="regenerateArticle('${id}')">${materialIcon('refresh')} Regenerate</button>
                </div>` : ''}
                <div style="padding-top:1rem;margin-bottom:1.5rem;border-top:1px solid var(--border)">
                    <div class="section-label">Edges</div>
                    ${edgesHTML}
                </div>
                <div style="padding-top:1.5rem;border-top:1px solid var(--border)">
                    <div class="section-label">Source Documents</div>
                    ${docsHTML}
                </div>
            </div>`;
    } catch (e) {
        page().innerHTML = `<div style="color:#e06c75;font-size:13px">Engram not found.</div>`;
    }
}

// --- Lint ---

const SEVERITY_STYLES = {
    error:   { color: '#e06c75', icon: 'error' },
    warning: { color: '#d4b06a', icon: 'warning' },
    info:    { color: '#5e9eff', icon: 'info' },
};

const TYPE_LABELS = {
    orphan: 'Orphan Engram',
    contradiction: 'Contradiction',
    missing_link: 'Missing Link',
    duplicate_candidate: 'Duplicate Candidate',
};

async function renderLint() {
    page().innerHTML = `
        <div class="text-display-lg" style="margin-bottom:0.5rem">Knowledge Health</div>
        <div style="font-size:11px;color:var(--fg-dim);margin-bottom:1.5rem">Automated quality checks on the knowledge graph</div>
        <button onclick="triggerLint()">${materialIcon('health_and_safety')} Run Checks</button>
        <div id="lint-list" style="margin-top:1rem"><span class="spinner"></span></div>`;

    try {
        const issues = await api('/lint/issues');
        const container = $('#lint-list');
        if (!issues || issues.length === 0) {
            container.innerHTML = '<div style="color:#56c9a0;font-size:11px;text-align:center;padding:2rem 0">No issues found. Knowledge graph is healthy.</div>';
            return;
        }

        // Group by type
        const grouped = {};
        for (const issue of issues) {
            const t = issue.issue_type || 'unknown';
            if (!grouped[t]) grouped[t] = [];
            grouped[t].push(issue);
        }

        let html = '';
        for (const [type, group] of Object.entries(grouped)) {
            const label = TYPE_LABELS[type] || type;
            html += `<div class="section-label" style="margin-top:1rem">${label} (${group.length})</div>`;
            for (const issue of group) {
                const sev = SEVERITY_STYLES[issue.severity] || SEVERITY_STYLES.warning;
                const ids = Array.isArray(issue.engram_ids) ? issue.engram_ids : JSON.parse(issue.engram_ids || '[]');
                // Tidy action buttons based on issue type
                let actions = `<button onclick="resolveLintIssue('${issue.id}')">Dismiss</button>`;
                if (issue.issue_type === 'orphan' && ids.length === 1) {
                    actions = `<button class="danger" onclick="deleteOrphanEngram('${ids[0]}','${issue.id}')">${materialIcon('delete')} Delete</button>` + actions;
                } else if (issue.issue_type === 'missing_link' && ids.length >= 2) {
                    actions = `<button onclick="createEdgeFromLint('${issue.id}')">${materialIcon('add_link')} Link</button>` + actions;
                } else if (issue.issue_type === 'duplicate_candidate' && ids.length >= 2) {
                    actions = `<button onclick="mergeFromLint('${issue.id}')">${materialIcon('merge')} Merge</button>` + actions;
                }

                html += `<div class="card" style="border-left:2px solid ${sev.color};margin-bottom:0.5rem">
                    <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem">
                        <span class="material-icons" style="font-size:14px;color:${sev.color}">${sev.icon}</span>
                        <span style="font-size:11px;color:var(--fg)">${escapeHTML(issue.description)}</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap">
                        ${ids.slice(0, 5).map(id => `<a href="/engrams/${id}" class="engram-link" style="font-size:9px">${id.slice(0, 8)}...</a>`).join('')}
                        <div style="margin-left:auto;display:flex;gap:0.25rem">${actions}</div>
                    </div>
                </div>`;
            }
        }
        html += `<div style="text-align:center;font-size:10px;color:var(--fg-muted);margin-top:1rem">${issues.length} unresolved issues</div>`;
        container.innerHTML = html;
    } catch (e) {
        $('#lint-list').innerHTML = `<div style="color:var(--fg-dim);font-size:11px">Failed to load issues.</div>`;
    }
}

window.synthesizeResults = async function(query, docIds) {
    notify('Synthesizing...', 'info');
    try {
        const result = await api('/search/synthesize', {
            method: 'POST',
            body: JSON.stringify({ query, document_ids: docIds }),
        });
        if (result.document_id) {
            notify('Synthesis created', 'positive');
            navigate(`/documents/${result.document_id}`);
        }
    } catch (e) {
        notify(`Synthesis failed: ${e.message}`, 'negative');
    }
};

window.setFontSize = async function(sizeId) {
    try {
        await api('/settings', {
            method: 'PUT',
            body: JSON.stringify({ ui_font_size: sizeId }),
        });
        const scales = {small: 0.9, normal: 1, large: 1.1, xlarge: 1.2};
        document.documentElement.style.setProperty('--font-size-scale', scales[sizeId] || 1);
        notify('Font size updated', 'positive');
        renderSettings();
    } catch (e) {
        notify(`Failed: ${e.message}`, 'negative');
    }
};

window.triggerLint = async function() {
    notify('Running lint checks...', 'info');
    try {
        const result = await api('/lint/run', { method: 'POST' });
        notify(result.new_issues > 0 ? `Found ${result.new_issues} new issues` : 'No new issues', result.new_issues > 0 ? 'warning' : 'positive');
        renderLint();
    } catch (e) {
        notify(`Lint failed: ${e.message}`, 'negative');
    }
};

window.resolveLintIssue = async function(issueId) {
    try {
        await api(`/lint/issues/${issueId}/resolve`, { method: 'POST' });
        notify('Issue dismissed', 'positive');
        renderLint();
    } catch (e) {
        notify(`Failed: ${e.message}`, 'negative');
    }
};

window.deleteOrphanEngram = async function(engramId, issueId) {
    try {
        await api(`/engrams/${engramId}`, { method: 'DELETE' });
        notify('Orphan engram deleted', 'positive');
        renderLint();
        import('/js/companion.js').then(m => m.loadCompanion()).catch(() => {});
    } catch (e) {
        notify(`Failed: ${e.message}`, 'negative');
    }
};

window.createEdgeFromLint = async function(issueId) {
    try {
        await api(`/lint/issues/${issueId}/create-edge`, {
            method: 'POST',
            body: JSON.stringify({ predicate: 'related_to', confidence: 0.8 }),
        });
        notify('Edge created', 'positive');
        renderLint();
        import('/js/companion.js').then(m => m.loadCompanion()).catch(() => {});
    } catch (e) {
        notify(`Failed: ${e.message}`, 'negative');
    }
};

window.mergeFromLint = async function(issueId) {
    try {
        const result = await api(`/lint/issues/${issueId}/merge`, {
            method: 'POST',
            body: JSON.stringify({}),
        });
        notify(`Merged ${result.merged_count} engrams`, 'positive');
        renderLint();
        import('/js/companion.js').then(m => m.loadCompanion()).catch(() => {});
    } catch (e) {
        notify(`Failed: ${e.message}`, 'negative');
    }
};

// --- Settings ---

async function renderSettings() {
    page().innerHTML = `
        <div class="text-display-lg" style="margin-bottom:1.5rem">Settings</div>
        <div id="settings-body"><span class="spinner"></span> Loading...</div>`;

    try {
        const [settings, providers] = await Promise.all([
            api('/settings'),
            api('/settings/providers'),
        ]);

        const llmProviders = providers.llm_providers || [];
        const embProviders = providers.embedding_providers || [];

        let html = '';

        // ── Font Size Section ──
        const fontSizes = {small: 'Small (90%)', normal: 'Normal (100%)', large: 'Large (110%)', xlarge: 'X-Large (120%)'};
        const currentSize = settings.ui_font_size || 'normal';
        html += `<div class="section-label" style="margin-top:0;margin-bottom:0.75rem">Font Size</div>
        <div class="card" style="cursor:default;margin-bottom:1.5rem">
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap">
                ${Object.entries(fontSizes).map(([id, label]) => {
                    const active = id === currentSize;
                    return `<button style="padding:0.4rem 0.75rem;border-radius:4px;border:1px solid ${active ? 'var(--accent)' : 'var(--border)'};background:${active ? 'var(--accent-soft)' : 'transparent'};color:var(--fg);cursor:pointer;font-size:11px" onclick="setFontSize('${id}')">${label}${active ? ' \u2713' : ''}</button>`;
                }).join('')}
            </div>
        </div>`;

        // ── LLM Provider Section ──
        html += `<div class="section-label" style="margin-top:0">LLM Provider</div>
        <div class="card" style="cursor:default;margin-bottom:1.5rem">
            <label class="input-label">Provider</label>
            <select id="settings-llm-provider" style="margin-bottom:0.75rem">
                ${Object.entries(LLM_PROVIDERS).map(([k, v]) =>
                    `<option value="${k}" ${k === settings.llm_provider ? 'selected' : ''}>${v}</option>`
                ).join('')}
            </select>
            <label class="input-label">Model</label>
            <select id="settings-llm-model" style="margin-bottom:0.75rem">
                ${(LLM_MODELS[settings.llm_provider] || ['(custom)']).map(m =>
                    `<option value="${m}" ${m === settings.llm_model ? 'selected' : ''}>${m}</option>`
                ).join('')}
            </select>
            <div id="settings-custom-model-row" style="display:${settings.llm_provider === 'ollama' ? 'block' : 'none'}">
                <label class="input-label">Custom model name</label>
                <input type="text" id="settings-custom-model" placeholder="e.g. llama3.1" value="${settings.llm_provider === 'ollama' ? escapeHTML(settings.llm_model || '') : ''}" style="margin-bottom:0.75rem">
            </div>
            <div id="settings-api-key-row" style="display:${settings.llm_provider in API_KEY_FIELD ? 'block' : 'none'}">
                <label class="input-label">API Key</label>
                <input type="password" id="settings-api-key" placeholder="Enter API key..." style="margin-bottom:0.75rem">
            </div>
            <div id="settings-ollama-url-row" style="display:${settings.llm_provider === 'ollama' ? 'block' : 'none'}">
                <label class="input-label">Ollama Base URL</label>
                <input type="text" id="settings-ollama-url" value="http://localhost:11434" style="margin-bottom:0.75rem">
            </div>
            <div id="settings-openai-url-row" style="display:${settings.llm_provider === 'openai' ? 'block' : 'none'}">
                <label class="input-label">OpenAI Base URL (optional)</label>
                <input type="text" id="settings-openai-url" placeholder="Leave empty for default" style="margin-bottom:0.75rem">
            </div>
            <div id="settings-llm-status" style="font-size:11px;margin-bottom:0.75rem"></div>
            <div style="display:flex;gap:0.5rem">
                <button id="settings-test-btn">Test Connection</button>
                <button id="settings-save-btn">Save</button>
            </div>
        </div>`;

        // ── Embedding Provider Section ──
        html += `<div class="section-label">Embedding Provider</div>
        <div class="card" style="cursor:default;margin-bottom:1.5rem">
            <div style="display:flex;gap:2rem;margin-bottom:0.5rem">
                <div><span style="font-size:11px;color:var(--fg-dim)">Provider:</span> <span style="font-size:11px;font-weight:500">${escapeHTML(settings.embedding_provider || 'not set')}</span></div>
                <div><span style="font-size:11px;color:var(--fg-dim)">Model:</span> <span style="font-size:11px;font-weight:500">${escapeHTML(settings.embedding_model || '-')}</span></div>
                <div><span style="font-size:11px;color:var(--fg-dim)">Dimension:</span> <span style="font-size:11px;font-weight:500">${escapeHTML(settings.embedding_dim || '-')}</span></div>
            </div>
            <div id="emb-change-status" style="font-size:11px;margin-top:0.5rem"></div>
            <button id="change-emb-btn" style="color:#d4b06a;margin-top:0.5rem">Change Embedding Provider</button>
        </div>`;

        // ── API Keys Status ──
        html += `<div class="section-label">API Keys</div>
        <div class="card" style="cursor:default;margin-bottom:1.5rem;font-size:11px;color:var(--fg-muted)">
            <div style="margin-bottom:0.25rem">Anthropic: ${settings.anthropic_api_key || 'not set'}</div>
            <div style="margin-bottom:0.25rem">Google: ${settings.google_api_key || 'not set'}</div>
            <div>OpenAI: ${settings.openai_api_key || 'not set'}</div>
        </div>`;

        // ── Feeds Section ──
        html += `<div class="section-label">Feeds</div>
        <div id="feeds-container"><span class="spinner"></span></div>
        <div class="section-label" style="margin-top:1rem">Add Feed</div>
        <div class="card" style="cursor:default;margin-bottom:1.5rem">
            <label class="input-label">Name</label>
            <input type="text" id="feed-name" placeholder="My RSS Feed" style="margin-bottom:0.5rem">
            <label class="input-label">Type</label>
            <select id="feed-type" style="margin-bottom:0.5rem">
                <option value="rss">rss</option>
                <option value="scrape">scrape</option>
                <option value="youtube">youtube</option>
            </select>
            <label class="input-label">URL</label>
            <input type="text" id="feed-url" placeholder="https://example.com/feed.xml" style="margin-bottom:0.5rem">
            <label class="input-label">Schedule (cron)</label>
            <input type="text" id="feed-schedule" value="0 */6 * * *" placeholder="0 */6 * * *" style="margin-bottom:0.75rem">
            <button id="add-feed-btn">Add Feed</button>
        </div>`;

        $('#settings-body').innerHTML = html;

        // Wire up LLM provider change
        $('#settings-llm-provider').addEventListener('change', () => {
            const p = $('#settings-llm-provider').value;
            const models = LLM_MODELS[p] || [];
            const modelSel = $('#settings-llm-model');
            modelSel.innerHTML = models.length
                ? models.map(m => `<option value="${m}">${m}</option>`).join('')
                : '<option value="(custom)">(custom)</option>';
            if (models.length) modelSel.value = DEFAULT_LLM_MODELS[p] || models[0];
            $('#settings-custom-model-row').style.display = p === 'ollama' ? 'block' : 'none';
            $('#settings-api-key-row').style.display = p in API_KEY_FIELD ? 'block' : 'none';
            $('#settings-ollama-url-row').style.display = p === 'ollama' ? 'block' : 'none';
            $('#settings-openai-url-row').style.display = p === 'openai' ? 'block' : 'none';
            $('#settings-llm-status').innerHTML = '';
        });

        // Test connection
        $('#settings-test-btn').addEventListener('click', async () => {
            const provider = $('#settings-llm-provider').value;
            const model = provider === 'ollama'
                ? ($('#settings-custom-model').value || DEFAULT_LLM_MODELS.ollama)
                : ($('#settings-llm-model').value || DEFAULT_LLM_MODELS[provider]);
            const apiKey = $('#settings-api-key').value || '';
            let baseURL = '';
            if (provider === 'ollama') baseURL = $('#settings-ollama-url').value;
            if (provider === 'openai') baseURL = $('#settings-openai-url').value;

            $('#settings-llm-status').innerHTML = `<span class="status-muted">Testing connection...</span>`;
            try {
                await api('/settings/check-connection', {
                    method: 'POST',
                    body: JSON.stringify({ kind: 'llm', provider, model, api_key: apiKey, base_url: baseURL }),
                });
                $('#settings-llm-status').innerHTML = `<span class="status-ok">Connected: ${escapeHTML(model)} is reachable.</span>`;
            } catch (e) {
                $('#settings-llm-status').innerHTML = `<span class="status-error">Connection failed: ${escapeHTML(e.message)}</span>`;
            }
        });

        // Save LLM settings
        $('#settings-save-btn').addEventListener('click', async () => {
            const provider = $('#settings-llm-provider').value;
            const model = provider === 'ollama'
                ? ($('#settings-custom-model').value || DEFAULT_LLM_MODELS.ollama)
                : ($('#settings-llm-model').value || DEFAULT_LLM_MODELS[provider]);
            const apiKey = $('#settings-api-key').value || '';

            const body = { llm_provider: provider, llm_model: model };
            const keyField = API_KEY_FIELD[provider];
            if (keyField && apiKey && !apiKey.startsWith('****')) body[keyField] = apiKey;
            if (provider === 'ollama') body.ollama_base_url = $('#settings-ollama-url').value;
            if (provider === 'openai' && $('#settings-openai-url').value) body.openai_base_url = $('#settings-openai-url').value;

            try {
                await api('/settings', { method: 'PUT', body: JSON.stringify(body) });
                notify('LLM settings saved', 'positive');
                $('#settings-llm-status').innerHTML = `<span class="status-ok">Saved: ${escapeHTML(provider)} / ${escapeHTML(model)}</span>`;
            } catch (e) {
                notify(`Save failed: ${e.message}`, 'negative');
            }
        });

        // Change embedding provider
        $('#change-emb-btn').addEventListener('click', () => showEmbeddingChangeDialog(settings));

        // Load feeds
        loadFeeds();

        // Add feed
        $('#add-feed-btn').addEventListener('click', async () => {
            const name = $('#feed-name').value.trim();
            const url = $('#feed-url').value.trim();
            const feedType = $('#feed-type').value;
            const schedule = $('#feed-schedule').value.trim() || '0 */6 * * *';

            if (!name) { notify('Feed name is required', 'warning'); return; }
            if (!url) { notify('Feed URL is required', 'warning'); return; }

            try {
                await api('/feeds', {
                    method: 'POST',
                    body: JSON.stringify({ name, feed_type: feedType, url, schedule }),
                });
                $('#feed-name').value = '';
                $('#feed-url').value = '';
                notify(`Feed '${name}' added`, 'positive');
                loadFeeds();
            } catch (e) {
                notify(`Failed: ${e.message}`, 'negative');
            }
        });

        // Poll embedding status
        pollEmbeddingStatus();

    } catch (e) {
        $('#settings-body').innerHTML = `<div style="color:#e06c75;font-size:13px">Failed to load settings.</div>`;
    }
}

async function loadFeeds() {
    const container = $('#feeds-container');
    if (!container) return;
    try {
        const feeds = await api('/feeds');
        if (!feeds || feeds.length === 0) {
            container.innerHTML = '<div style="color:var(--fg-muted);font-size:11px;padding:1rem 0">No feeds configured.</div>';
            return;
        }
        container.innerHTML = feeds.map(feed => {
            const isActive = feed.active === 1;
            const borderColor = isActive ? '#56c9a0' : '#e06c75';
            return `<div class="feed-card" style="border-left:2px solid ${borderColor}">
                <div style="flex:1;min-width:0">
                    <div style="font-size:11px;font-weight:500">${escapeHTML(feed.name)}</div>
                    <div style="display:flex;align-items:center;gap:0.5rem;margin-top:0.2rem">
                        <span class="source-badge" style="color:#56c9a0;background:rgba(86,201,160,0.07)">${escapeHTML(feed.feed_type)}</span>
                        <span style="font-size:11px;color:var(--fg-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:200px">${escapeHTML(feed.url)}</span>
                    </div>
                    <div style="font-size:11px;color:var(--fg-dim);margin-top:0.2rem">schedule: ${escapeHTML(feed.schedule)}</div>
                </div>
                <div style="display:flex;align-items:center;gap:0.5rem">
                    <label class="toggle">
                        <input type="checkbox" ${isActive ? 'checked' : ''} onchange="toggleFeed('${feed.id}', this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                    <button class="danger" onclick="deleteFeed('${feed.id}')">${materialIcon('delete')}</button>
                </div>
            </div>`;
        }).join('');
    } catch (e) {
        container.innerHTML = '<div style="color:var(--fg-dim);font-size:11px">Failed to load feeds.</div>';
    }
}

window.toggleFeed = async function(id, active) {
    try {
        await api(`/feeds/${id}`, { method: 'PATCH', body: JSON.stringify({ active: active ? 1 : 0 }) });
        loadFeeds();
    } catch (e) {
        notify(`Failed: ${e.message}`, 'negative');
    }
};

window.deleteFeed = async function(id) {
    try {
        await api(`/feeds/${id}`, { method: 'DELETE' });
        notify('Feed deleted', 'info');
        loadFeeds();
    } catch (e) {
        notify(`Failed: ${e.message}`, 'negative');
    }
};

function showEmbeddingChangeDialog(settings) {
    const backdrop = document.createElement('div');
    backdrop.className = 'dialog-backdrop';
    backdrop.innerHTML = `
        <div class="dialog">
            <div style="font-size:13px;font-weight:500;margin-bottom:0.5rem">Change Embedding Provider</div>
            <div style="font-size:11px;color:#d4b06a;margin-bottom:1rem">
                This will delete all engrams, edges, and projections, then reprocess every document. This can take a long time.
            </div>
            <label class="input-label">New Embedding Provider</label>
            <select id="dialog-emb-provider" style="margin-bottom:0.75rem">
                ${Object.entries(EMBEDDING_PROVIDERS).map(([k, v]) =>
                    `<option value="${k}" ${k === settings.embedding_provider ? 'selected' : ''}>${v}</option>`
                ).join('')}
            </select>
            <label class="input-label">API Key (for cloud providers)</label>
            <input type="password" id="dialog-emb-key" placeholder="Enter API key..." style="margin-bottom:0.75rem">
            <div style="display:flex;gap:0.5rem;justify-content:flex-end">
                <button id="dialog-cancel">Cancel</button>
                <button id="dialog-confirm" style="color:#d4b06a">Confirm Change</button>
            </div>
        </div>`;
    document.body.appendChild(backdrop);

    backdrop.querySelector('#dialog-cancel').addEventListener('click', () => backdrop.remove());
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) backdrop.remove(); });

    backdrop.querySelector('#dialog-confirm').addEventListener('click', async () => {
        const provider = backdrop.querySelector('#dialog-emb-provider').value;
        const apiKey = backdrop.querySelector('#dialog-emb-key').value;

        const body = { embedding_provider: provider };
        if (provider === 'google' && apiKey) body.google_api_key = apiKey;
        if (provider === 'openai' && apiKey) body.openai_api_key = apiKey;

        backdrop.remove();

        try {
            await api('/settings/change-embedding', { method: 'POST', body: JSON.stringify(body) });
            notify(`Embedding changed to ${provider}. Rebuild started.`, 'positive');
            renderSettings();
        } catch (e) {
            notify(`Failed: ${e.message}`, 'negative');
        }
    });
}

let _embPollTimer = null;
async function pollEmbeddingStatus() {
    if (_embPollTimer) clearInterval(_embPollTimer);
    const status = $('#emb-change-status');
    if (!status) return;

    async function check() {
        try {
            const s = await api('/settings/embedding-status');
            if (s.status === 'in_progress') {
                status.innerHTML = `<span class="spinner" style="width:10px;height:10px;border-width:1.5px"></span> <span class="status-warning">Rebuilding... ${s.processed}/${s.total}</span>`;
            } else if (s.status === 'failed') {
                status.innerHTML = `<span class="status-error">Rebuild failed: ${escapeHTML(s.error || 'unknown')}</span>`;
                clearInterval(_embPollTimer);
            } else if (s.status === 'complete' && s.total > 0) {
                status.innerHTML = `<span class="status-ok">Rebuild complete (${s.processed} documents)</span>`;
                clearInterval(_embPollTimer);
            } else {
                status.innerHTML = '';
                clearInterval(_embPollTimer);
            }
        } catch (e) { /* ignore */ }
    }

    await check();
    _embPollTimer = setInterval(check, 3000);
}

// --- Visualization ---

function renderViz() {
    // Break out of the max-width container for full-viewport graph
    const app = $('#app');
    app.style.maxWidth = 'none';
    app.style.padding = '0';

    page().innerHTML = `
        <div style="width:100%;height:100vh;position:relative">
            <div id="graph-container" style="width:100%;height:100%"></div>
            <div id="graph-hud" style="position:absolute;bottom:1rem;left:1rem;font-size:10px;color:var(--fg-dim)">Loading graph...</div>
        </div>`;

    loadVizGraph();
}

// Restore normal layout when leaving viz
function restoreLayout() {
    const app = $('#app');
    app.style.maxWidth = '';
    app.style.padding = '';
}

async function loadVizGraph() {
    try {
        let [projections, edges] = await Promise.all([
            api('/viz/projections'),
            api('/viz/edges'),
        ]);

        // Auto-recompute if no projections exist but engrams do
        if (!projections || projections.length === 0) {
            const engrams = await api('/engrams?limit=1');
            if (engrams.items && engrams.items.length > 0) {
                $('#graph-hud').textContent = 'Computing projections...';
                projections = await api('/viz/recompute', { method: 'POST' });
                edges = await api('/viz/edges');
            }
        }

        if (!projections || projections.length === 0) {
            $('#graph-hud').textContent = 'No projection data. Process some documents first.';
            return;
        }

        $('#graph-hud').textContent = `${projections.length} nodes, ${edges.length} edges`;

        const { initGraph } = await import('/js/viz.js');
        initGraph('#graph-container', projections, edges);

        // Refresh minimap now that projections exist
        loadMinimap();
    } catch (err) {
        $('#graph-hud').textContent = 'Graph error: ' + err.message;
    }
}

// ── Minimap ─────────────────────────────────────────────────

async function loadMinimap() {
    const container = $('#minimap');
    if (!container) return;

    try {
        const projections = await api('/viz/projections');
        if (!projections || projections.length === 0) return;

        const edges = await api('/viz/edges');

        // Compute bounds
        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
        for (const p of projections) {
            if (p.x < minX) minX = p.x;
            if (p.x > maxX) maxX = p.x;
            if (p.y < minY) minY = p.y;
            if (p.y > maxY) maxY = p.y;
        }
        const pad = 2;
        minX -= pad; maxX += pad; minY -= pad; maxY += pad;
        const rangeX = maxX - minX || 1;
        const rangeY = maxY - minY || 1;
        const w = 176, h = 110;

        const nodeMap = new Map();
        for (const p of projections) {
            nodeMap.set(p.engram_id, {
                x: ((p.x - minX) / rangeX) * w,
                y: ((p.y - minY) / rangeY) * h,
                cluster: p.cluster_id,
            });
        }

        let svg = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg" style="display:block">`;

        // Edges
        for (const e of (edges || []).slice(0, 200)) {
            const s = nodeMap.get(e.source_engram_id);
            const t = nodeMap.get(e.target_engram_id);
            if (s && t) {
                svg += `<line x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}" stroke="#1a1a1e" stroke-width="0.5"/>`;
            }
        }

        // Nodes
        for (const [, n] of nodeMap) {
            const hue = n.cluster != null && n.cluster >= 0
                ? (n.cluster * 137.508) % 360
                : 30;
            const sat = n.cluster != null && n.cluster >= 0 ? '55%' : '10%';
            const fill = `hsl(${hue}, ${sat}, 60%)`;
            svg += `<circle cx="${n.x}" cy="${n.y}" r="2" fill="${fill}" opacity="0.8"/>`;
        }

        svg += '</svg>';
        container.innerHTML = svg;
        container.addEventListener('click', () => navigate('/viz'));
    } catch (e) {
        // No projections yet — leave minimap empty
    }
}
