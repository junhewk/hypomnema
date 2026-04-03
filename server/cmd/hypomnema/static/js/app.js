// Hypomnema — Client-side SPA router and page rendering
// Vanilla JS, no framework, no build step.

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const page = () => $('#page-content');

// --- Router ---

const routes = {
    '/':         renderStream,
    '/search':   renderSearch,
    '/settings': renderSettings,
    '/viz':      renderViz,
};

function navigate(path) {
    history.pushState(null, '', path);
    route();
}

function route() {
    const path = location.pathname;

    // Update active nav
    $$('.nav-item').forEach(el => {
        el.classList.toggle('active', el.dataset.route === path);
    });

    // Document detail: /documents/:id
    if (path.startsWith('/documents/')) {
        const id = path.split('/')[2];
        renderDocument(id);
        return;
    }

    // Engram detail: /engrams/:id
    if (path.startsWith('/engrams/')) {
        const id = path.split('/')[2];
        renderEngram(id);
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

// --- API helpers ---

async function api(path, opts = {}) {
    const resp = await fetch('/api' + path, {
        headers: { 'Content-Type': 'application/json', ...opts.headers },
        ...opts,
    });
    if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
    return resp.json();
}

function timeAgo(iso) {
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    return new Date(iso).toLocaleDateString();
}

function escapeHTML(s) {
    const div = document.createElement('div');
    div.textContent = s || '';
    return div.innerHTML;
}

// --- Document card component ---

function documentCard(doc) {
    const title = doc.tidy_title || doc.title || 'Untitled';
    const preview = (doc.tidy_text || doc.text || '').slice(0, 280);
    const heatClass = doc.heat_tier ? `heat-${doc.heat_tier}` : '';
    const heatIcon = { active: '\u{1F525}', reference: '\u{1F4D6}', dormant: '\u{1F319}' }[doc.heat_tier] || '';

    return `
        <a href="/documents/${doc.id}" class="card" style="text-decoration:none;color:inherit">
            <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem">
                <span class="badge badge-${doc.source_type}">${doc.source_type}</span>
                ${doc.processed >= 2 ? '' : '<span class="spinner"></span>'}
                ${heatIcon ? `<span class="${heatClass}" title="${doc.heat_tier}">${heatIcon}</span>` : ''}
            </div>
            <div class="card-title">${escapeHTML(title)}</div>
            <div class="card-text">${escapeHTML(preview)}</div>
            <div class="card-meta">
                <span>${timeAgo(doc.created_at)}</span>
            </div>
        </a>`;
}

// --- Pages ---

async function renderStream() {
    page().innerHTML = `
        <div class="section-label">Stream</div>
        <div class="input-area">
            <textarea id="scribble-input" rows="3" placeholder="Write something, paste a URL, or drop a file..."></textarea>
            <div style="display:flex;gap:0.5rem;margin-top:0.5rem">
                <button onclick="submitScribble()">Submit</button>
                <label class="secondary" style="display:inline-flex;align-items:center;gap:0.3rem;padding:0.5rem 1rem;background:var(--bg-raised);border:1px solid var(--border);border-radius:6px;font-size:0.82rem;color:var(--fg-muted);cursor:pointer">
                    Upload <input type="file" id="file-input" style="display:none" accept=".pdf,.docx,.md,.txt" onchange="uploadFile(this)">
                </label>
            </div>
        </div>
        <div class="filter-tabs">
            <span class="filter-tab active" onclick="filterStream('all')">All</span>
            <span class="filter-tab" onclick="filterStream('active')">Active</span>
            <span class="filter-tab" onclick="filterStream('reference')">Reference</span>
            <span class="filter-tab" onclick="filterStream('dormant')">Dormant</span>
        </div>
        <div id="doc-list"><span class="spinner"></span> Loading...</div>`;

    const docs = await api('/documents?days=100');
    window._allDocs = docs;
    renderDocList(docs);
}

function renderDocList(docs) {
    const list = $('#doc-list');
    if (!docs || docs.length === 0) {
        list.innerHTML = '<div style="color:var(--fg-dim);font-size:0.85rem">No documents yet.</div>';
        return;
    }
    list.innerHTML = docs.map(documentCard).join('');
}

window.filterStream = function(tier) {
    $$('.filter-tab').forEach(t => t.classList.toggle('active', t.textContent.toLowerCase() === tier));
    const docs = tier === 'all' ? window._allDocs : window._allDocs.filter(d => d.heat_tier === tier);
    renderDocList(docs);
};

window.submitScribble = async function() {
    const input = $('#scribble-input');
    const text = input.value.trim();
    if (!text) return;

    // URL detection
    const urlMatch = text.match(/^https?:\/\/\S+$/);
    if (urlMatch) {
        await api('/documents/urls', { method: 'POST', body: JSON.stringify({ url: text }) });
    } else {
        await api('/documents/scribbles', { method: 'POST', body: JSON.stringify({ text }) });
    }

    input.value = '';
    renderStream();
};

window.uploadFile = async function(input) {
    const file = input.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    await fetch('/api/documents/files', { method: 'POST', body: form });
    renderStream();
};

async function renderSearch() {
    page().innerHTML = `
        <div class="section-label">Search</div>
        <input type="text" id="search-input" placeholder="Search documents and knowledge..." oninput="debounceSearch()">
        <div id="search-results" style="margin-top:1rem"></div>`;
}

let _searchTimer;
window.debounceSearch = function() {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(async () => {
        const q = $('#search-input').value.trim();
        if (!q) { $('#search-results').innerHTML = ''; return; }
        const results = await api(`/search/documents?q=${encodeURIComponent(q)}`);
        $('#search-results').innerHTML = results.map(documentCard).join('') || '<div style="color:var(--fg-dim)">No results</div>';
    }, 300);
};

async function renderDocument(id) {
    const { document: doc, engrams } = await api(`/documents/${id}`);
    const related = await api(`/documents/${id}/related`);
    const title = doc.tidy_title || doc.title || 'Untitled';
    const text = doc.tidy_text || doc.text || '';

    page().innerHTML = `
        <div style="margin-bottom:1rem">
            <a href="/" style="color:var(--fg-dim);text-decoration:none;font-size:0.8rem">&larr; Stream</a>
        </div>
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem">
            <span class="badge badge-${doc.source_type}">${doc.source_type}</span>
            ${doc.heat_tier ? `<span class="heat-${doc.heat_tier}">${doc.heat_tier}</span>` : ''}
        </div>
        <h1 style="font-family:'Cormorant Garamond',serif;font-size:1.6rem;margin-bottom:1rem">${escapeHTML(title)}</h1>
        <div style="font-size:0.85rem;line-height:1.7;color:var(--fg-muted);white-space:pre-wrap;margin-bottom:1.5rem">${escapeHTML(text)}</div>
        ${engrams && engrams.length ? `
            <div class="section-label">Engrams</div>
            <div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-bottom:1.5rem">
                ${engrams.map(e => `<a href="/engrams/${e.id}" class="engram-link badge badge-url">${escapeHTML(e.canonical_name)}</a>`).join('')}
            </div>
        ` : ''}
        ${related && related.length ? `
            <div class="section-label">Related Documents</div>
            ${related.map(r => `<a href="/documents/${r.id}" class="card" style="text-decoration:none;color:inherit;display:block"><div class="card-title">${escapeHTML(r.title)}</div></a>`).join('')}
        ` : ''}`;
}

async function renderEngram(id) {
    const { engram, edges, documents } = await api(`/engrams/${id}`);

    page().innerHTML = `
        <div style="margin-bottom:1rem">
            <a href="/" style="color:var(--fg-dim);text-decoration:none;font-size:0.8rem">&larr; Stream</a>
        </div>
        <h1 style="font-family:'Cormorant Garamond',serif;font-size:1.6rem;margin-bottom:0.5rem">${escapeHTML(engram.canonical_name)}</h1>
        ${engram.description ? `<p style="color:var(--fg-muted);font-size:0.85rem;margin-bottom:1.5rem">${escapeHTML(engram.description)}</p>` : ''}
        ${edges && edges.length ? `
            <div class="section-label">Edges</div>
            <div style="margin-bottom:1.5rem">
                ${edges.map(e => `
                    <div style="font-size:0.82rem;padding:0.3rem 0;display:flex;gap:0.5rem;align-items:center">
                        <a href="/engrams/${e.source_engram_id}" class="engram-link">${escapeHTML(e.source_name)}</a>
                        <span style="color:var(--fg-dim)">&rarr; ${e.predicate} &rarr;</span>
                        <a href="/engrams/${e.target_engram_id}" class="engram-link">${escapeHTML(e.target_name)}</a>
                        <span style="color:var(--fg-dim);font-size:0.72rem">${Math.round(e.confidence * 100)}%</span>
                    </div>
                `).join('')}
            </div>
        ` : ''}
        ${documents && documents.length ? `
            <div class="section-label">Source Documents</div>
            ${documents.map(documentCard).join('')}
        ` : ''}`;
}

async function renderSettings() {
    page().innerHTML = `
        <div class="section-label">Settings</div>
        <div id="settings-content"><span class="spinner"></span> Loading...</div>`;

    const settings = await api('/settings');
    $('#settings-content').innerHTML = `
        <div class="card" style="cursor:default">
            <div style="font-size:0.78rem;color:var(--fg-dim);margin-bottom:0.3rem">LLM Provider</div>
            <div style="font-size:0.9rem">${settings.llm_provider || 'Not configured'} / ${settings.llm_model || '-'}</div>
        </div>
        <div class="card" style="cursor:default">
            <div style="font-size:0.78rem;color:var(--fg-dim);margin-bottom:0.3rem">Embedding Provider</div>
            <div style="font-size:0.9rem">${settings.embedding_provider || 'Not configured'} / ${settings.embedding_model || '-'} (dim: ${settings.embedding_dim || '-'})</div>
        </div>
        <div class="card" style="cursor:default">
            <div style="font-size:0.78rem;color:var(--fg-dim);margin-bottom:0.3rem">API Keys</div>
            <div style="font-size:0.82rem;color:var(--fg-muted)">
                Anthropic: ${settings.anthropic_api_key || 'not set'}<br>
                Google: ${settings.google_api_key || 'not set'}<br>
                OpenAI: ${settings.openai_api_key || 'not set'}
            </div>
        </div>`;
}

function renderViz() {
    page().innerHTML = `
        <div style="width:100%;height:calc(100vh - 4rem);position:relative">
            <div id="graph-container" style="width:100%;height:100%"></div>
            <div id="graph-hud" style="position:absolute;bottom:1rem;left:1rem;font-size:0.72rem;color:var(--fg-dim)">Loading graph...</div>
        </div>`;

    // Load Three.js graph - separate script
    loadVizGraph();
}

async function loadVizGraph() {
    try {
        const [projections, edges] = await Promise.all([
            api('/viz/projections'),
            api('/viz/edges'),
        ]);

        if (!projections || projections.length === 0) {
            $('#graph-hud').textContent = 'No projection data. Process some documents first.';
            return;
        }

        $('#graph-hud').textContent = `${projections.length} nodes, ${edges.length} edges`;

        // Dynamic import of the viz module
        const { initGraph } = await import('/js/viz.js');
        initGraph('#graph-container', projections, edges);
    } catch (err) {
        $('#graph-hud').textContent = 'Graph error: ' + err.message;
    }
}

// --- Init ---
document.addEventListener('DOMContentLoaded', route);
