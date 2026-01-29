/**
 * On-Chain Analytics Dashboard
 */

// ============================================================
// STATE
// ============================================================
const state = {
  currentView: 'market',
  currentSlug: null,
  marketData: null,
  profileData: null,
  charts: {},
  priceRange: 365,
};

// ============================================================
// FORMATTING
// ============================================================
const fmt = {
  usd(n) {
    if (n == null) return '\u2014';
    const abs = Math.abs(n);
    if (abs >= 1e12) return '$' + (n / 1e12).toFixed(2) + 'T';
    if (abs >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
    if (abs >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
    if (abs >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'K';
    if (abs >= 1) return '$' + n.toFixed(2);
    if (abs >= 0.01) return '$' + n.toFixed(4);
    return '$' + n.toFixed(6);
  },
  num(n) {
    if (n == null) return '\u2014';
    const abs = Math.abs(n);
    if (abs >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (abs >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    if (abs >= 100) return n.toFixed(0);
    if (abs >= 1) return n.toFixed(2);
    return n.toFixed(4);
  },
  pct(n) {
    if (n == null) return '\u2014';
    const sign = n > 0 ? '+' : '';
    return sign + n.toFixed(2) + '%';
  },
  pctClass(n) {
    if (n == null) return 'num-neutral';
    if (n > 0) return 'num-positive';
    if (n < 0) return 'num-negative';
    return 'num-neutral';
  },
  metricName(key) {
    const names = {
      price_usd: 'Price',
      marketcap_usd: 'Market Cap',
      volume_usd: 'Volume',
      daily_active_addresses: 'Active Addresses',
      transaction_volume: 'Tx Volume',
      mvrv_usd: 'MVRV',
      nvt: 'NVT',
      exchange_balance: 'Exchange Balance',
      dev_activity: 'Dev Activity',
      network_growth: 'Network Growth',
      exchange_inflow: 'Exchange Inflow',
      exchange_outflow: 'Exchange Outflow',
      circulation: 'Circulation',
      velocity: 'Velocity',
      mean_age: 'Mean Coin Age',
      realized_value_usd: 'Realized Value',
      mean_realized_price_usd: 'Mean Realized Price',
      age_consumed: 'Age Consumed',
      whale_transaction_count_100k_usd_to_inf: 'Whale Txs (>100K)',
      supply_on_exchanges: 'Supply on Exchanges',
      supply_outside_exchanges: 'Supply off Exchanges',
      percent_of_total_supply_on_exchanges: '% Supply on Exchanges',
      sentiment_balance_total: 'Sentiment Balance',
      weighted_sentiment_total: 'Weighted Sentiment',
      social_volume_total: 'Social Volume',
      social_dominance_total: 'Social Dominance',
      dev_activity_contributors_count: 'Dev Contributors',
      active_addresses_24h: 'Active Addr 24h',
    };
    return names[key] || key.replace(/_/g, ' ');
  },
  metricVal(key, val) {
    if (val == null) return '\u2014';
    if (key.includes('usd') && !key.includes('mvrv') && !key.includes('nvt'))
      return fmt.usd(val);
    return fmt.num(val);
  },
};

// ============================================================
// API
// ============================================================
async function api(path) {
  const res = await fetch('/api/v1' + path);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

// ============================================================
// NAVIGATION
// ============================================================
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const el = document.getElementById('view' + name.charAt(0).toUpperCase() + name.slice(1));
  if (el) el.classList.add('active');

  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
  const navLink = document.querySelector(`.nav-link[data-view="${name}"]`);
  if (navLink) navLink.classList.add('active');

  state.currentView = name;
}

function openProfile(slug) {
  state.currentSlug = slug;
  showView('profile');
  loadProfile(slug);
}

// ============================================================
// MARKET VIEW
// ============================================================
async function loadMarket() {
  try {
    const data = await api('/market');
    state.marketData = data;

    // Update status
    const dot = document.getElementById('statusDot');
    const status = data.pull_status;
    dot.className = 'status-indicator';
    if (status === 'ready' || status === 'partial' || status === 'phase1_complete' || status === 'phase2_pulling') {
      dot.classList.add('live');
    } else if (status === 'phase1_pulling' || status === 'phase1_discovery') {
      dot.classList.add('loading');
    } else {
      dot.classList.add('error');
    }

    if (data.last_pull) {
      const d = new Date(data.last_pull);
      document.getElementById('lastUpdate').textContent = d.toLocaleTimeString();
    }

    document.getElementById('tokenCount').textContent =
      data.count + ' tokens tracked';

    // Summary stats
    const tokens = data.tokens;
    const totalMcap = tokens.reduce((s, t) => s + (t.marketcap_usd || 0), 0);
    const totalVol = tokens.reduce((s, t) => s + (t.volume_usd || 0), 0);
    const mvrValues = tokens.filter(t => t.mvrv_usd != null).map(t => t.mvrv_usd);
    const nvtValues = tokens.filter(t => t.nvt != null).map(t => t.nvt);
    const avgMvrv = mvrValues.length ? mvrValues.reduce((s, v) => s + v, 0) / mvrValues.length : null;
    const avgNvt = nvtValues.length ? nvtValues.reduce((s, v) => s + v, 0) / nvtValues.length : null;

    document.getElementById('statMcap').textContent = fmt.usd(totalMcap);
    document.getElementById('statVolume').textContent = fmt.usd(totalVol);
    document.getElementById('statMvrv').textContent = avgMvrv != null ? avgMvrv.toFixed(2) : '\u2014';
    document.getElementById('statNvt').textContent = avgNvt != null ? avgNvt.toFixed(1) : '\u2014';

    // Render table
    const tbody = document.getElementById('marketBody');
    if (!tokens.length) {
      tbody.innerHTML = '<tr><td colspan="10" class="empty-cell">No data yet. Data is being pulled in the background...</td></tr>';
      return;
    }

    tbody.innerHTML = tokens.map((t, i) => `
      <tr data-slug="${t.slug}">
        <td class="col-rank">${i + 1}</td>
        <td class="col-name">
          <div class="token-name">
            <strong>${t.name}</strong>
            <span class="ticker">${t.ticker}</span>
          </div>
        </td>
        <td class="col-num num-bold">${fmt.usd(t.price_usd)}</td>
        <td class="col-num ${fmt.pctClass(t.price_usd_change)}">${fmt.pct(t.price_usd_change)}</td>
        <td class="col-num">${fmt.usd(t.marketcap_usd)}</td>
        <td class="col-num">${fmt.usd(t.volume_usd)}</td>
        <td class="col-num">${t.mvrv_usd != null ? t.mvrv_usd.toFixed(2) : '\u2014'}</td>
        <td class="col-num">${t.nvt != null ? t.nvt.toFixed(1) : '\u2014'}</td>
        <td class="col-num hide-mobile">${fmt.num(t.daily_active_addresses)}</td>
        <td class="col-num hide-mobile">${t.dev_activity != null ? t.dev_activity.toFixed(0) : '\u2014'}</td>
      </tr>
    `).join('');

    // Click handlers
    tbody.querySelectorAll('tr[data-slug]').forEach(row => {
      row.addEventListener('click', () => openProfile(row.dataset.slug));
    });
  } catch (e) {
    console.error('Market load error:', e);
    document.getElementById('marketBody').innerHTML =
      '<tr><td colspan="10" class="empty-cell">Error loading data. Retrying...</td></tr>';
  }
}

// ============================================================
// VALUATION VIEW
// ============================================================
async function loadValuation() {
  try {
    const data = state.marketData || await api('/market');
    const tokens = data.tokens.filter(t => t.mvrv_usd != null);

    const tbody = document.getElementById('valuationBody');
    if (!tokens.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">No valuation data yet</td></tr>';
      return;
    }

    // Fetch valuation details for each token with MVRV
    const rows = [];
    for (const t of tokens) {
      let val = {};
      try {
        const resp = await api('/valuation/' + t.slug);
        val = resp.valuation || {};
      } catch (e) { /* skip */ }

      const mvrv = t.mvrv_usd;
      let zone = 'fair', zoneLabel = 'Fair', zoneClass = 'zone-fair';
      if (mvrv > 3.5) { zone = 'extreme'; zoneLabel = 'Extremely High'; zoneClass = 'zone-extreme'; }
      else if (mvrv > 2.5) { zone = 'overvalued'; zoneLabel = 'Overvalued'; zoneClass = 'zone-overvalued'; }
      else if (mvrv > 1.5) { zone = 'fair'; zoneLabel = 'Fair-High'; zoneClass = 'zone-fair'; }
      else if (mvrv > 1.0) { zone = 'fair'; zoneLabel = 'Fair'; zoneClass = 'zone-fair'; }
      else if (mvrv > 0.5) { zone = 'undervalued'; zoneLabel = 'Undervalued'; zoneClass = 'zone-undervalued'; }
      else { zone = 'extreme'; zoneLabel = 'Extremely Low'; zoneClass = 'zone-extreme'; }

      const mvrv90 = val.mvrv_usd?.avg_90d;
      const mvrv365 = val.mvrv_usd?.avg_365d;

      rows.push(`
        <tr data-slug="${t.slug}">
          <td class="col-name">
            <div class="token-name"><strong>${t.name}</strong><span class="ticker">${t.ticker}</span></div>
          </td>
          <td class="col-num num-bold">${fmt.usd(t.price_usd)}</td>
          <td class="col-num num-bold">${mvrv.toFixed(2)}</td>
          <td class="col-tag"><span class="zone-tag ${zoneClass}">${zoneLabel}</span></td>
          <td class="col-num">${t.nvt != null ? t.nvt.toFixed(1) : '\u2014'}</td>
          <td class="col-num hide-mobile">${mvrv90 != null ? mvrv90.toFixed(2) : '\u2014'}</td>
          <td class="col-num hide-mobile">${mvrv365 != null ? mvrv365.toFixed(2) : '\u2014'}</td>
        </tr>
      `);
    }

    tbody.innerHTML = rows.join('');
    tbody.querySelectorAll('tr[data-slug]').forEach(row => {
      row.addEventListener('click', () => openProfile(row.dataset.slug));
    });
  } catch (e) {
    console.error('Valuation load error:', e);
  }
}

// ============================================================
// PROFILE VIEW
// ============================================================
async function loadProfile(slug) {
  try {
    const data = await api('/profile/' + slug);
    state.profileData = data;
    const project = data.project;
    const metrics = data.metrics;

    // Header
    document.getElementById('profileName').textContent = project.name || slug;
    document.getElementById('profileTicker').textContent = project.ticker || '';
    document.getElementById('profileInfra').textContent = project.infrastructure ? `(${project.infrastructure})` : '';

    const priceData = metrics.price_usd;
    if (priceData) {
      document.getElementById('profilePrice').textContent = fmt.usd(priceData.latest);
      const change = metrics.price_usd?.data;
      if (change && change.length >= 2) {
        const prev = change[change.length - 2].value;
        const curr = change[change.length - 1].value;
        const pct = prev ? ((curr - prev) / prev * 100) : 0;
        const el = document.getElementById('profileChange');
        el.textContent = fmt.pct(pct);
        el.className = 'profile-change ' + fmt.pctClass(pct);
      }
    }

    // Key Metrics Grid
    const keyMetrics = [
      'marketcap_usd', 'volume_usd', 'mvrv_usd', 'nvt',
      'daily_active_addresses', 'transaction_volume',
      'exchange_balance', 'dev_activity', 'network_growth',
      'social_volume_total', 'sentiment_balance_total', 'whale_transaction_count_100k_usd_to_inf',
    ];

    const grid = document.getElementById('profileMetrics');
    grid.innerHTML = keyMetrics.map(key => {
      const m = metrics[key];
      if (!m) return '';
      return `
        <div class="metric-card">
          <div class="metric-card-label">${fmt.metricName(key)}</div>
          <div class="metric-card-value">${fmt.metricVal(key, m.latest)}</div>
        </div>
      `;
    }).join('');

    // Valuation Bars
    renderValuationBars(metrics);

    // Charts
    renderPriceChart(metrics.price_usd?.data, state.priceRange);
    renderMetricChart('daaChart', metrics.daily_active_addresses?.data, 'Active Addresses');
    renderMetricChart('exchangeChart', metrics.exchange_balance?.data, 'Exchange Balance');
    renderMetricChart('devChart', metrics.dev_activity?.data, 'Dev Activity');
    renderMetricChart('networkChart', metrics.network_growth?.data, 'Network Growth');

    // All Metrics Table
    const allBody = document.getElementById('allMetricsBody');
    const metricKeys = Object.keys(metrics).sort();
    allBody.innerHTML = metricKeys.map(key => {
      const m = metrics[key];
      return `
        <tr>
          <td class="col-name">${fmt.metricName(key)}</td>
          <td class="col-num num-bold">${fmt.metricVal(key, m.latest)}</td>
          <td class="col-num">${fmt.metricVal(key, m.avg_30d)}</td>
          <td class="col-num hide-mobile">${fmt.metricVal(key, m.min_365d)}</td>
          <td class="col-num hide-mobile">${fmt.metricVal(key, m.max_365d)}</td>
          <td class="col-num hide-mobile">${m.count}</td>
        </tr>
      `;
    }).join('');

  } catch (e) {
    console.error('Profile load error:', e);
    document.getElementById('profileName').textContent = 'Error loading profile';
  }
}

// ============================================================
// VALUATION BARS
// ============================================================
function renderValuationBars(metrics) {
  const container = document.getElementById('valuationBars');
  const items = [
    { key: 'mvrv_usd', label: 'MVRV' },
    { key: 'nvt', label: 'NVT' },
  ];

  container.innerHTML = items.map(item => {
    const m = metrics[item.key];
    if (!m || m.min_365d == null || m.max_365d == null || m.latest == null) return '';

    const min = m.min_365d;
    const max = m.max_365d;
    const range = max - min;
    const pct = range > 0 ? Math.max(0, Math.min(100, ((m.latest - min) / range) * 100)) : 50;

    return `
      <div class="val-bar-row">
        <span class="val-bar-label">${item.label}</span>
        <div class="val-bar-track">
          <div class="val-bar-fill" style="width:${pct}%"></div>
          <div class="val-bar-marker" style="left:${pct}%"></div>
        </div>
        <span class="val-bar-value">${fmt.num(m.latest)}</span>
      </div>
    `;
  }).join('');
}

// ============================================================
// CHART HELPERS
// ============================================================
const chartDefaults = {
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 300 },
  interaction: { intersect: false, mode: 'index' },
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: '#000',
      titleColor: '#fff',
      bodyColor: '#fff',
      cornerRadius: 4,
      padding: 10,
      titleFont: { weight: 700, size: 12 },
      bodyFont: { size: 12 },
    },
  },
  scales: {
    x: {
      type: 'time',
      grid: { display: false },
      ticks: { font: { size: 11, weight: 500 }, color: '#737373', maxTicksLimit: 8 },
      border: { display: false },
    },
    y: {
      grid: { color: '#F5F5F5' },
      ticks: { font: { size: 11, weight: 500 }, color: '#737373', maxTicksLimit: 6 },
      border: { display: false },
    },
  },
};

function destroyChart(id) {
  if (state.charts[id]) {
    state.charts[id].destroy();
    delete state.charts[id];
  }
}

function filterByDays(data, days) {
  if (!data || !days) return data;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  return data.filter(d => new Date(d.datetime) >= cutoff);
}

function renderPriceChart(data, days) {
  if (!data) return;
  const filtered = filterByDays(data, days);
  destroyChart('priceChart');

  const ctx = document.getElementById('priceChart').getContext('2d');
  state.charts.priceChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: filtered.map(d => d.datetime),
      datasets: [{
        data: filtered.map(d => d.value),
        borderColor: '#000',
        backgroundColor: 'rgba(0,0,0,0.04)',
        borderWidth: 1.5,
        fill: true,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: '#000',
        tension: 0.1,
      }],
    },
    options: {
      ...chartDefaults,
      scales: {
        ...chartDefaults.scales,
        y: {
          ...chartDefaults.scales.y,
          ticks: {
            ...chartDefaults.scales.y.ticks,
            callback: v => fmt.usd(v),
          },
        },
      },
    },
  });
}

function renderMetricChart(canvasId, data, label) {
  if (!data) return;
  const filtered = filterByDays(data, 365);
  destroyChart(canvasId);

  const ctx = document.getElementById(canvasId).getContext('2d');
  state.charts[canvasId] = new Chart(ctx, {
    type: 'line',
    data: {
      labels: filtered.map(d => d.datetime),
      datasets: [{
        data: filtered.map(d => d.value),
        borderColor: '#000',
        backgroundColor: 'rgba(0,0,0,0.03)',
        borderWidth: 1.2,
        fill: true,
        pointRadius: 0,
        tension: 0.2,
      }],
    },
    options: {
      ...chartDefaults,
      scales: {
        ...chartDefaults.scales,
        y: {
          ...chartDefaults.scales.y,
          ticks: {
            ...chartDefaults.scales.y.ticks,
            callback: v => fmt.num(v),
          },
        },
      },
    },
  });
}

// ============================================================
// INIT
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  // Nav links
  document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', e => {
      e.preventDefault();
      const view = link.dataset.view;
      showView(view);
      if (view === 'market') loadMarket();
      if (view === 'valuation') loadValuation();
    });
  });

  // Logo goes to market
  document.getElementById('logoLink').addEventListener('click', e => {
    e.preventDefault();
    showView('market');
    loadMarket();
  });

  // Back button
  document.getElementById('backBtn').addEventListener('click', () => {
    showView('market');
  });

  // Chart range buttons
  document.querySelectorAll('.range-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.priceRange = parseInt(btn.dataset.days);
      if (state.profileData?.metrics?.price_usd?.data) {
        renderPriceChart(state.profileData.metrics.price_usd.data, state.priceRange);
      }
    });
  });

  // Initial load
  loadMarket();

  // Auto refresh every 5 minutes
  setInterval(() => {
    if (state.currentView === 'market') loadMarket();
    else if (state.currentView === 'valuation') loadValuation();
  }, 5 * 60 * 1000);
});
