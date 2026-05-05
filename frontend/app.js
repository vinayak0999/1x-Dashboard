// ═══════════════════════════════════════════════════════
// 1x OPERATIONS DASHBOARD — APP LOGIC
// Talks to backend /api/1x-data
// ═══════════════════════════════════════════════════════

const API_BASE = window.location.origin;
let currentData = null;
let chartTPT   = null;
let chartRatio = null;

const LS_HASH = '1x_project_hash';
const LS_FROM = '1x_date_from';
const LS_TO   = '1x_date_to';
const LS_DAYS = '1x_preset_days';

// ── Init ─────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    const hashEl = document.getElementById('project-hash');
    // URL param overrides default hash
    const urlHash = new URLSearchParams(window.location.search).get('project');
    if (urlHash) hashEl.value = urlHash;
    // Always start with clean 90-day range
    setPreset(90, document.getElementById('preset-90'));
    hashEl.addEventListener('keydown', e => { if (e.key === 'Enter') loadData(); });
});


// ── Preset buttons ──
function setPreset(days, btn) {
    document.querySelectorAll('.preset').forEach(p => p.classList.remove('active'));
    if (btn) btn.classList.add('active');
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - days);
    document.getElementById('date-to').value   = fmtDate(to);
    document.getElementById('date-from').value = fmtDate(from);
}

// ── All Time preset — goes back to 2020-01-01 to cover full project history ──
function setPresetAllTime(btn) {
    document.querySelectorAll('.preset').forEach(p => p.classList.remove('active'));
    if (btn) btn.classList.add('active');
    document.getElementById('date-from').value = '2020-01-01';
    document.getElementById('date-to').value   = fmtDate(new Date());
}

// ── Load Data ──
async function loadData() {
    const ph       = document.getElementById('project-hash').value.trim();
    const dateFrom = document.getElementById('date-from').value;
    const dateTo   = document.getElementById('date-to').value;

    if (!ph) {
        alert('Please enter a Project Hash.');
        document.getElementById('project-hash').focus();
        return;
    }
    if (!dateFrom || !dateTo) {
        alert('Please select a date range.');
        return;
    }

    showLoading();
    setStatus('loading', 'Loading...');
    setBtnLoading(true);

    // Update URL for shareability
    const newUrl = `${window.location.pathname}?project=${ph}`;
    window.history.replaceState({}, '', newUrl);

    try {
        const url = `${API_BASE}/api/1x-data?project_hash=${encodeURIComponent(ph)}&start_date=${dateFrom}&end_date=${dateTo}`;
        const resp = await fetch(url);
        const data = await resp.json();

        if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);

        currentData = data;
        renderDashboard(data);
        renderCharts(data.weekly_data || []);
        setStatus('ok', `Updated ${new Date().toLocaleTimeString()}`);
        // ─ Persist state for auto-load on next visit ─
        localStorage.setItem(LS_HASH, ph);
        localStorage.setItem(LS_FROM, dateFrom);
        localStorage.setItem(LS_TO,   dateTo);
        const ap = document.querySelector('.preset.active');
        if (ap) localStorage.setItem(LS_DAYS, ap.id.replace('preset-', ''));
    } catch (err) {
        showError('Failed to Load', err.message);
        setStatus('error', 'Error');
    } finally {
        setBtnLoading(false);
    }
}

// ── Render Dashboard ──
function renderDashboard(data) {
    hideAll();
    document.getElementById('dashboard').classList.remove('hidden');

    const m    = data.metrics  || {};
    const anns = data.annotators || [];
    const revs = data.reviewers  || [];

    // Header subtitle
    document.getElementById('header-subtitle').textContent =
        `${data.project_title || '1x Client'} · ${data.date_filter || ''}`;

    // Date range label
    document.getElementById('date-range-label').textContent =
        `Showing data for: ${data.date_filter || ''}`;

    // ── Overview: Annotation Metrics ──
    document.getElementById('annotation-metrics').innerHTML = `
        ${metricCard('blue',   '👤', 'Number of Annotators',    m.num_annotators ?? '—',  'Active in period')}
        ${metricCard('indigo', '✅', 'Tasks Annotated',          m.num_tasks_submitted ?? '—', 'Total tasks submitted')}
        ${metricCard('purple', '⏱️', 'Total Annotation Time',   m.total_annotation_time_raw || '—', `${m.total_annotation_time_hours ?? 0}h total`)}
        ${metricCard('teal',   '🎬', 'Video Duration Annotated', m.video_duration_raw || (m.video_duration_seconds > 0 ? fmtSecs(m.video_duration_seconds) : '—'), `${m.videos_counted ?? 0} videos · ${m.video_duration_hours ?? 0}h`)}
        ${metricCard('orange', '⚡', 'Time per Task (Avg TPT)',  m.time_per_task_raw || '—', `÷ ${m.tpt_denominator ?? m.num_tasks_submitted ?? 0} submitted tasks`)}
    `;

    // ── Overview: Review Metrics ──
    document.getElementById('review-metrics').innerHTML = `
        ${metricCard('green',  '🔍', 'Number of Reviewers',    m.num_reviewers ?? '—',      'Active in period')}
        ${metricCard('amber',  '📋', 'Tasks Reviewed',          m.num_tasks_reviewed ?? '—', 'Unique tasks reviewed')}
        ${metricCard('pink',   '⏰', 'Hours Reviewed',          m.hours_reviewed_raw || '—', `${m.hours_reviewed_hours ?? 0}h total`)}
    `;

    // ── Hero Ratio Card ──
    const ratio    = m.ratio_display || '—';
    const annHours = m.total_annotation_time_hours ?? 0;
    const vidHours = m.video_duration_hours ?? 0;
    document.getElementById('hero-ratio-value').innerHTML =
        ratio !== '—' ? `${parseFloat(m.ratio).toFixed(2)}<span>x</span>` : '—';
    document.getElementById('hero-ann-time').textContent = m.total_annotation_time_raw || '—';
    document.getElementById('hero-vid-dur').textContent  = m.video_duration_raw || '—';
    document.getElementById('hero-vid-sub').textContent  = `${m.videos_counted ?? 0} videos · ${vidHours}h`;
    document.getElementById('hero-ratio-desc').textContent = ratio !== '—'
        ? `For every 1h of video, annotators spent ${parseFloat(m.ratio).toFixed(2)}× more time. ${m.videos_counted ?? 0} videos covered.`
        : 'Video duration not available — check that SUBMIT_TASK label logs are present.';

    // ── Annotators table ──

    document.getElementById('annotators-tbody').innerHTML = anns.map(a => {
        const avatarClass = a.status === 'crit' ? 'avatar-red' : (a.status === 'warn' ? 'avatar-orange' : 'avatar-green');
        const flags = (a.flags || []).map(f => {
            const cls = f.label.includes('rejection') ? 'high-rejection'
                      : f.label.includes('fast')      ? 'too-fast'
                      : f.label.includes('slow')      ? 'too-slow'
                      : 'low-throughput';
            return `<span class="flag-badge ${cls}">${f.label}</span>`;
        }).join('') || '<span style="color:#94a3b8">—</span>';

        const approved = (a.tasks_submitted || 0) - (a.tasks_rejected || 0);

        return `<tr>
            <td><div class="annotator-cell">
                <div class="annotator-avatar ${avatarClass}">${a.id || '??'}</div>
                <div class="annotator-info">
                    <span class="annotator-name">${a.name}</span>
                    <span class="annotator-email">${a.email}</span>
                </div>
            </div></td>
            <td><strong>${a.tasks || 0}</strong></td>
            <td>${a.tasks_submitted || 0}</td>
            <td>${approved}</td>
            <td>${a.tasks_rejected || 0}</td>
            <td><span class="rej-rate ${getRejClass(a.rejection)}">${a.rejection || 0}%</span></td>
            <td>${a.tput || 0}/day</td>
            <td>${a.avg_tpt_raw || '—'}</td>
            <td>${a.annotation_time_raw || '—'}</td>
            <td>${a.days || 1}</td>
            <td>${flags}</td>
        </tr>`;
    }).join('') || '<tr><td colspan="11" style="text-align:center;color:#94a3b8;padding:32px">No annotators in this period</td></tr>';

    // ── Reviewers table ──

    document.getElementById('reviewers-tbody').innerHTML = revs.map(r => {
        const avatarClass = r.rev_rejection_rate > 20 ? 'avatar-orange' : 'avatar-green';
        return `<tr>
            <td><div class="annotator-cell">
                <div class="annotator-avatar ${avatarClass}">${r.id || '??'}</div>
                <div class="annotator-info">
                    <span class="annotator-name">${r.name}</span>
                    <span class="annotator-email">${r.email}</span>
                </div>
            </div></td>
            <td><strong>${r.tasks_reviewed || 0}</strong></td>
            <td>${r.review_time_raw || '—'}</td>
            <td>${r.rev_approved || 0}</td>
            <td>${r.rev_rejected || 0}</td>
        </tr>`;
    }).join('') || '<tr><td colspan="5" style="text-align:center;color:#94a3b8;padding:32px">No reviewers in this period</td></tr>';
}

// ── Metric Card Builder ──
function metricCard(color, icon, label, value, sub) {
    return `
        <div class="metric-card ${color}">
            <div class="metric-icon ${color}">${icon}</div>
            <div class="metric-label">${label}</div>
            <div class="metric-value ${color}">${value}</div>
            <div class="metric-sub">${sub}</div>
        </div>
    `;
}

// ── Tab Switching ──
function switchTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(`tab-${name}`).classList.add('active');
    document.getElementById(`tab-content-${name}`).classList.add('active');
}

// ── Helpers ──
function fmtDate(d) { return d.toISOString().split('T')[0]; }

function fmtDisplayDate(d) {
    if (!d) return '';
    const [y, m, day] = d.split('-');
    return `${day}/${m}/${y}`;
}

function fmtSecs(secs) {
    secs = Math.round(secs);
    if (secs < 60) return `${secs}s`;
    const m = Math.floor(secs / 60), s = secs % 60;
    if (m < 60) return `${m}m ${s}s`;
    const h = Math.floor(m / 60), mins = m % 60;
    return `${h}h ${mins}m ${s}s`;
}

function getRejClass(rate) {
    if (rate >= 20) return 'high';
    if (rate >= 10) return 'medium';
    return 'low';
}

function setStatus(type, text) {
    const dot = document.getElementById('status-dot');
    const txt = document.getElementById('status-text');
    dot.className = 'status-dot' + (type === 'loading' ? ' loading' : type === 'error' ? ' error' : '');
    txt.textContent = text;
}

function setBtnLoading(on) {
    const btn   = document.getElementById('load-btn');
    const label = document.getElementById('btn-label');
    const icon  = document.getElementById('btn-icon');
    if (!btn) return;
    btn.disabled = on;
    if (label) label.textContent = on ? 'Loading...' : 'Load Data';
    if (icon)  icon.textContent  = on ? '' : '⚡';
}

function hideAll() {
    ['empty-state', 'loading-state', 'error-state', 'dashboard'].forEach(id => {
        document.getElementById(id).classList.add('hidden');
    });
}

function showLoading() {
    hideAll();
    document.getElementById('loading-state').classList.remove('hidden');
}

function showError(title, msg) {
    hideAll();
    document.getElementById('error-state').classList.remove('hidden');
    document.getElementById('error-title').textContent = title;
    document.getElementById('error-msg').textContent   = msg;
    setStatus('error', 'Error');
}

// ── Chart Rendering ───────────────────────────────────────
function renderCharts(weekly) {
    renderTPTChart(weekly);
    renderRatioChart(weekly);
}

const CHART_DEFAULTS = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: { display: false },
        tooltip: {
            backgroundColor: '#1e1b4b',
            titleColor: '#c7d2fe',
            bodyColor: '#e0e7ff',
            borderColor: '#4f46e5',
            borderWidth: 1,
            padding: 12,
            cornerRadius: 10,
            titleFont: { size: 12, weight: '700' },
            bodyFont:  { size: 13 },
        }
    },
    scales: {
        x: {
            grid:  { color: '#e4e8f0', drawBorder: false },
            ticks: { color: '#94a3b8', font: { size: 11, weight: '600' } }
        },
        y: {
            grid:  { color: '#e4e8f0', drawBorder: false },
            ticks: { color: '#94a3b8', font: { size: 11 } },
            beginAtZero: true,
        }
    },
    elements: {
        point:  { radius: 5, hoverRadius: 7, borderWidth: 2 },
        line:   { tension: 0.35, borderWidth: 2.5 }
    }
};

function renderTPTChart(weekly) {
    const canvas = document.getElementById('chart-tpt');
    if (!canvas) return;
    const wrap = canvas.parentElement;
    if (!wrap) return;

    if (!weekly || weekly.length === 0) {
        wrap.innerHTML = `<div class="chart-empty"><div class="chart-empty-icon">📅</div>Not enough data for this period</div>`;
        return;
    }
    // Restore canvas if previously replaced
    if (!document.getElementById('chart-tpt')) {
        wrap.innerHTML = '<canvas id="chart-tpt"></canvas>';
    }
    const labels = weekly.map(w => w.label);
    const vals   = weekly.map(w => w.tpt_minutes);
    if (chartTPT) chartTPT.destroy();
    chartTPT = new Chart(document.getElementById('chart-tpt'), {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label:           'Avg TPT (min)',
                data:            vals,
                borderColor:     '#4f46e5',
                backgroundColor: 'rgba(79,70,229,0.08)',
                pointBackgroundColor: '#4f46e5',
                pointBorderColor:    '#ffffff',
                fill:            true,
            }]
        },
        options: {
            ...CHART_DEFAULTS,
            plugins: {
                ...CHART_DEFAULTS.plugins,
                tooltip: {
                    ...CHART_DEFAULTS.plugins.tooltip,
                    callbacks: {
                        label: ctx => {
                            const v = ctx.parsed.y;
                            const m = Math.floor(v), s = Math.round((v - m) * 60);
                            return ` ${m}m ${s}s per task`;
                        }
                    }
                }
            },
            scales: {
                ...CHART_DEFAULTS.scales,
                y: { ...CHART_DEFAULTS.scales.y, title: { display: true, text: 'Minutes', color: '#94a3b8', font: { size: 11 } } }
            }
        }
    });
}

function renderRatioChart(weekly) {
    const canvas = document.getElementById('chart-ratio');
    if (!canvas) return;
    const wrap = canvas.parentElement;
    if (!wrap) return;
    const ratioWeeks = weekly.filter(w => w.ratio !== null && w.ratio !== undefined);
    if (!ratioWeeks.length) {
        wrap.innerHTML = `<div class="chart-empty"><div class="chart-empty-icon">🎦</div>Video duration needed for Ratio chart</div>`;
        return;
    }
    if (!document.getElementById('chart-ratio')) {
        wrap.innerHTML = '<canvas id="chart-ratio"></canvas>';
    }
    const labels = ratioWeeks.map(w => w.label);
    const vals   = ratioWeeks.map(w => w.ratio);

    if (chartRatio) chartRatio.destroy();
    chartRatio = new Chart(document.getElementById('chart-ratio'), {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label:           'Ratio',
                data:            vals,
                borderColor:     '#7c3aed',
                backgroundColor: 'rgba(124,58,237,0.08)',
                pointBackgroundColor: '#7c3aed',
                pointBorderColor:    '#ffffff',
                fill:            true,
            }]
        },
        options: {
            ...CHART_DEFAULTS,
            plugins: {
                ...CHART_DEFAULTS.plugins,
                tooltip: {
                    ...CHART_DEFAULTS.plugins.tooltip,
                    callbacks: {
                        label: ctx => ` ${ctx.parsed.y.toFixed(2)}x (Ann Time ÷ Video Duration)`
                    }
                }
            },
            scales: {
                ...CHART_DEFAULTS.scales,
                y: { ...CHART_DEFAULTS.scales.y, title: { display: true, text: 'Ratio (x)', color: '#94a3b8', font: { size: 11 } } }
            }
        }
    });
}
