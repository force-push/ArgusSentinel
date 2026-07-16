// main.js — bootstrap, hash router, WS + REST wiring, demo-mode fallback.
import store from './store.js';
import api, { getToken } from './api.js';
import { ReconnectingWS } from './ws.js';
import * as fmt from './format.js';

import { initKpis } from './components/kpis.js';
import { initHistory } from './components/history.js';
import { initPerformance } from './components/performance.js';
import { initSettings } from './components/settings.js';
import { initAnalysis } from './components/analysis.js';

let currentRange = '1D';
let ws = null;
let demoSim = null;

/* ------------------------------------------------------------------ */
/* Tab routing (hash router)                                          */
/* ------------------------------------------------------------------ */
function initRouter() {
  const tabs = Array.from(document.querySelectorAll('.tab'));
  const views = Array.from(document.querySelectorAll('.view'));

  function show(name) {
    const valid = views.some((v) => v.id === `view-${name}`);
    const target = valid ? name : 'monitoring';
    tabs.forEach((t) => {
      const on = t.dataset.view === target;
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    });
    views.forEach((v) => v.classList.toggle('active', v.id === `view-${target}`));
  }

  tabs.forEach((t) => {
    t.addEventListener('click', () => { location.hash = t.dataset.view; });
    t.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault();
        const i = tabs.indexOf(t);
        const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
        next.focus();
        location.hash = next.dataset.view;
      }
    });
  });

  window.addEventListener('hashchange', () => show(location.hash.replace('#', '')));
  show(location.hash.replace('#', '') || 'monitoring');
}

/* ------------------------------------------------------------------ */
/* Top-bar status chips                                               */
/* ------------------------------------------------------------------ */
function initChips() {
  const wsChip = document.getElementById('chip-ws');
  const balChip = document.getElementById('chip-balance');
  const modeChip = document.getElementById('chip-mode');
  const weeklyChip = document.getElementById('chip-weekly');
  const countdownChip = document.getElementById('chip-countdown');

  store.subscribe('ws', (status) => {
    if (!wsChip) return;
    const map = {
      connecting: ['connecting', 'WS Connecting…'],
      live: ['live', store.get('demo') ? 'Demo Mode' : 'WS Connected'],
      reconnecting: ['reconnecting', 'Reconnecting…'],
      closed: ['closed', 'WS Closed'],
    };
    const [cls, label] = map[status] || map.connecting;
    wsChip.className = `chip ws-${cls}`;
    wsChip.innerHTML = `<span class="live-dot"></span>${label}`;
  });

  store.subscribe('meta', (meta) => {
    if (balChip) balChip.querySelector('b').textContent = fmt.money(meta.balance, meta.currency === 'USD' ? '$' : '$');
    if (modeChip) {
      const live = meta.mode === 'LIVE';
      modeChip.className = `chip ${live ? 'badge-live' : 'badge-demo'}`;
      modeChip.textContent = `● ${meta.mode}${meta.dry_run ? ' · DRY' : ''}`;
    }
  });

  store.subscribe('kpis', (kpis) => {
    if (!weeklyChip) return;
    const proj = kpis.weekly_projection || 0;
    const sign = proj >= 0 ? '+' : '';
    weeklyChip.querySelector('b').textContent = `${sign}${fmt.pnl(proj)}`;
    const isPositive = proj > 0;
    weeklyChip.style.color = isPositive ? 'var(--up)' : proj < 0 ? 'var(--down)' : 'var(--accent)';
  });

  store.subscribe('skip_countdown', (countdown) => {
    if (!countdownChip) return;
    if (countdown && countdown.minutes_until !== undefined) {
      const mins = Math.max(0, countdown.minutes_until);
      // Human-readable countdown: prefer server-formatted, fall back to local format
      const h = Math.floor(mins / 60), m = mins % 60;
      const human = countdown.countdown || (h ? `${h}h ${m}m` : `${m}m`);
      // Next window opens in local time
      const next = new Date();
      next.setUTCHours(countdown.next_hour_utc, 0, 0, 0);
      if (next <= new Date()) next.setUTCDate(next.getUTCDate() + 1);
      const localTime = next.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
      const wr = countdown.win_rate_pct != null ? ` · WR ${countdown.win_rate_pct.toFixed(1)}%` : '';
      countdownChip.style.display = 'flex';
      countdownChip.querySelector('b').textContent = `${human} (${localTime}${wr})`;
      countdownChip.style.color = mins <= 5 ? 'var(--accent)' : 'inherit';
    } else {
      countdownChip.style.display = 'none';
    }
  });
}

/* ------------------------------------------------------------------ */
/* Apply a /api/state (or ws state) snapshot to the store            */
/* ------------------------------------------------------------------ */
// Once range-scoped KPIs (from /api/performance) take over the strip, state
// heartbeats must not clobber them with the legacy "today" snapshot.
let rangeKpisActive = false;

function applyState(s) {
  if (!s) return;
  store.setMeta({
    mode: s.mode, dry_run: s.dry_run, connected: s.connected,
    balance: s.balance, currency: s.currency,
  });
  if (s.kpis && !rangeKpisActive) store.setKpis(s.kpis);
  if (s.skip_countdown) store.setSkipCountdown(s.skip_countdown);
}

/* ------------------------------------------------------------------ */
/* WebSocket message dispatch                                        */
/* ------------------------------------------------------------------ */
function onWsMessage(type, data) {
  switch (type) {
    case 'hello':
      if (data && data.mode) store.setMeta({ mode: data.mode });
      break;
    case 'state':
      applyState(data);
      break;
    case 'trade_opened':
      break;
    case 'trade_resolved':
      store.prependHistory(data);
      if (typeof data.balance_after === 'number') store.setMeta({ balance: data.balance_after });
      refreshPerformance();
      break;
    case 'history':
      store.prependHistory(data);
      break;
    case 'settings_changed':
      // backend pushed a settings change; refresh the form payload
      loadSettings();
      break;
    default:
      break;
  }
}

/* ------------------------------------------------------------------ */
/* REST loaders                                                      */
/* ------------------------------------------------------------------ */
async function loadHistory() {
  try {
    const h = await api.history({ limit: 100 });
    store.setHistory(h.rows || h || []);
  } catch (e) { /* demo fallback handled by caller */ throw e; }
}

async function refreshPerformance() {
  try {
    const p = store.get('demo') ? await loadSample('performance.json') : await api.performance(currentRange);
    p.range = currentRange;
    store.setPerformance(p);
    // KPI strip follows the chart's range toggle
    if (p.kpis) {
      rangeKpisActive = true;
      store.setKpis({ ...p.kpis, range: currentRange });
    }
  } catch (e) { console.warn('[perf] failed', e); }
}

async function loadSettings() {
  try {
    const s = store.get('demo') ? await loadSample('settings.json') : await api.settings();
    store.setSettings(s);
  } catch (e) { console.warn('[settings] load failed', e); }
}

/* ------------------------------------------------------------------ */
/* Demo mode — bundled samples + a simulated tick                    */
/* ------------------------------------------------------------------ */
async function loadSample(name) {
  const res = await fetch(new URL(`../sample/${name}`, import.meta.url));
  if (!res.ok) throw new Error(`sample ${name} ${res.status}`);
  return res.json();
}

async function enterDemoMode() {
  console.info('[dashboard] backend unreachable — entering demo mode (bundled samples).');
  store.setDemo(true);
  store.setWsStatus('live'); // chip shows "Demo Mode"

  const [state, history, perf, settings] = await Promise.all([
    loadSample('state.json'),
    loadSample('history.json'),
    loadSample('performance.json'),
    loadSample('settings.json'),
  ]);

  applyState(state);
  store.setHistory(history.rows || []);
  perf.range = currentRange;
  store.setPerformance(perf);
  store.setSettings(settings);

  startDemoSim();
}

// Demo simulator: periodically resolves a simulated trade and prepends a history row.
function startDemoSim() {
  if (demoSim) clearInterval(demoSim);
  const pairs = [
    { raw: 'EUR/USD OTC', api: 'EURUSD_otc', entry: 1.07432 },
    { raw: 'GBP/JPY OTC', api: 'GBPJPY_otc', entry: 188.214 },
    { raw: 'USD/CHF', api: 'USDCHF', entry: 0.89744 },
    { raw: 'AUD/CAD OTC', api: 'AUDCAD_otc', entry: 0.90112 },
  ];
  let counter = 1000;

  demoSim = setInterval(() => {
    const now = Date.now();
    if (Math.random() < 0.15) {
      const p = pairs[Math.floor(Math.random() * pairs.length)];
      const dir = Math.random() < 0.5 ? 'CALL' : 'PUT';
      const win = Math.random() < 0.6;
      const draw = Math.random() < 0.05;
      const result = draw ? 'draw' : win ? 'win' : 'loss';
      const stake = 1.5;
      const pnl = result === 'win' ? +(stake * 0.92).toFixed(2) : result === 'loss' ? -stake : 0;
      const meta = store.get('meta');
      const balance_after = +((meta.balance || 0) + pnl).toFixed(2);
      counter += 1;
      const row = {
        ts: new Date(now).toISOString(), time: fmt.time(new Date(now).toISOString()),
        pair_raw: p.raw, pair_api: p.api, otc: /otc/i.test(p.raw),
        dir, decision: 'TRADE', result, pnl, stake,
        expiry_seconds: 30, our_confluence: +(0.75 + Math.random() * 0.18).toFixed(2),
        bot_win_rate: 0.84, entry: p.entry, skip_reason: null, trade_id: `sim-${counter}`,
        balance_after,
      };
      onWsMessage('trade_resolved', row);
      bumpKpis(result, pnl, balance_after);
    }
  }, 1000);
}

function bumpKpis(result, pnl, balance) {
  const k = store.get('kpis');
  if (!k) return;
  const next = { ...k };
  if (result === 'win') next.wins += 1;
  else if (result === 'loss') next.losses += 1;
  else next.draws += 1;
  next.trades_today += 1;
  next.traded += 1;
  next.today_pnl = +(next.today_pnl + pnl).toFixed(2);
  const total = next.wins + next.losses + next.draws;
  next.win_rate = total ? next.wins / total : 0;
  store.setKpis(next);
  store.setMeta({ balance });
}

/* ------------------------------------------------------------------ */
/* Boot                                                              */
/* ------------------------------------------------------------------ */
async function boot() {
  initRouter();
  initChips();
  initKpis('#kpi-strip');
  initHistory('#history-rows', '#history-count');
  initPerformance({
    chartSel: '#chart-wrap',
    segSel: '#perf-seg',
    winlossSel: '#winloss',
    onRange: (r) => { currentRange = r; refreshPerformance(); },
  });
  initSettings({ rootSel: '#settings-wrap' });
  initAnalysis('#analysis-wrap');

  store.setWsStatus('connecting');

  // Try the live backend first; on any failure fall back to demo mode.
  let live = false;
  try {
    const state = await api.state();
    applyState(state);
    live = true;
  } catch (e) {
    live = false;
  }

  if (!live) {
    await enterDemoMode();
    return;
  }

  // backend reachable — load the rest and open the websocket
  await Promise.allSettled([loadHistory(), refreshPerformance(), loadSettings()]);

  const tok = getToken();
  ws = new ReconnectingWS(tok ? `/ws?token=${encodeURIComponent(tok)}` : '/ws', {
    onStatus: (s) => store.setWsStatus(s),
    onMessage: onWsMessage,
  });
  ws.connect();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
