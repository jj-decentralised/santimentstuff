/**
 * Smart Money Dashboard
 *
 * WSJ-inspired dashboard for tracking smart money activity.
 */

// Chart instances
let netflowChart = null;
let holdingsChart = null;
let trendsChart = null;
let sectorChart = null;
let historyChart = null;
let transferChart = null;

// WSJ-inspired chart colors
const CHART_COLORS = {
    positive: '#00A86B',
    negative: '#C41E3A',
    neutral: '#666666',
    text: '#1A1A1A',
    textMuted: '#999999',
    border: '#E5E5E5',
    sectors: ['#1A1A1A', '#333333', '#4D4D4D', '#666666', '#808080', '#999999', '#B3B3B3', '#CCCCCC'],
};

// Chart.js defaults
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.color = CHART_COLORS.textMuted;

// State
const state = {
    selectedChains: ['ethereum'],
    currentView: 'purchases',
    currentToken: null,
};

// API helpers
const api = {
    async get(endpoint) {
        const response = await fetch(endpoint);
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    },
};

// Formatting helpers
const fmt = {
    usd(value) {
        if (value === null || value === undefined) return '--';
        const abs = Math.abs(value);
        const sign = value < 0 ? '-' : '';
        if (abs >= 1_000_000_000) {
            return `${sign}$${(abs / 1_000_000_000).toFixed(1)}B`;
        } else if (abs >= 1_000_000) {
            return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
        } else if (abs >= 1_000) {
            return `${sign}$${(abs / 1_000).toFixed(0)}K`;
        }
        return `${sign}$${abs.toFixed(0)}`;
    },

    usdSigned(value) {
        if (value === null || value === undefined) return '--';
        const prefix = value > 0 ? '+' : '';
        return prefix + this.usd(value);
    },

    number(value) {
        if (value === null || value === undefined) return '--';
        return value.toLocaleString();
    },

    percent(value) {
        if (value === null || value === undefined) return '--';
        const prefix = value > 0 ? '+' : '';
        return `${prefix}${value.toFixed(2)}%`;
    },

    time(isoString) {
        if (!isoString) return '--';
        const date = new Date(isoString);
        return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    },

    address(addr) {
        if (!addr) return '--';
        return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
    },
};

// DOM helpers
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => document.querySelectorAll(selector);

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initChainSelector();
    initTabs();
    initBackButton();
    loadOverview();
    loadData();
});

function initChainSelector() {
    const container = $('#chain-selector');
    const chains = [
        { id: 'ethereum', name: 'ETH' },
        { id: 'solana', name: 'SOL' },
        { id: 'base', name: 'BASE' },
        { id: 'arbitrum', name: 'ARB' },
    ];

    container.innerHTML = chains.map(chain => `
        <button class="chain-btn ${state.selectedChains.includes(chain.id) ? 'active' : ''}"
                data-chain="${chain.id}">
            ${chain.name}
        </button>
    `).join('');

    container.addEventListener('click', (e) => {
        const btn = e.target.closest('.chain-btn');
        if (!btn) return;

        const chain = btn.dataset.chain;

        // Toggle chain selection
        if (state.selectedChains.includes(chain)) {
            if (state.selectedChains.length > 1) {
                state.selectedChains = state.selectedChains.filter(c => c !== chain);
            }
        } else {
            state.selectedChains.push(chain);
        }

        // Update UI
        container.querySelectorAll('.chain-btn').forEach(b => {
            b.classList.toggle('active', state.selectedChains.includes(b.dataset.chain));
        });

        loadOverview();
        loadData();
    });
}

function initTabs() {
    const tabs = $('#main-tabs');

    tabs.addEventListener('click', (e) => {
        const tab = e.target.closest('.tab');
        if (!tab) return;

        const view = tab.dataset.view;

        // Update tabs
        tabs.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');

        // Update views
        state.currentView = view;
        showView(view);
        loadData();
    });
}

function initBackButton() {
    $('#back-btn').addEventListener('click', () => {
        state.currentToken = null;
        showView('purchases');

        // Reset tab state
        $$('.tab').forEach(t => t.classList.remove('active'));
        $('[data-view="purchases"]').classList.add('active');
    });
}

function showView(viewId) {
    $$('.view').forEach(v => v.classList.remove('active'));
    $(`#${viewId}-view`).classList.add('active');
}

// === Market Overview ===

async function loadOverview() {
    const chains = state.selectedChains.join(',');

    try {
        const data = await api.get(`/api/v1/overview?chains=${chains}`);

        // Update stat cards
        $('#total-value').textContent = fmt.usd(data.summary?.total_value_usd);
        $('#net-flow').textContent = fmt.usdSigned(data.summary?.net_flow_24h);
        $('#net-flow').className = `stat-value ${data.summary?.net_flow_24h > 0 ? 'positive' : 'negative'}`;
        $('#accumulating').textContent = fmt.number(data.summary?.tokens_accumulating);
        $('#distributing').textContent = fmt.number(data.summary?.tokens_distributing);
        $('#buy-vol').textContent = fmt.usd(data.trade_summary?.buy_volume_usd);
        $('#sell-vol').textContent = fmt.usd(data.trade_summary?.sell_volume_usd);

        // Render charts
        renderNetflowChart(data.charts?.top_by_inflow || []);
        renderHoldingsChart(data.charts?.top_by_value || []);
        renderTrendsChart(data.charts?.netflow_by_token || []);
        renderSectorChart(data.charts?.sectors || []);

    } catch (error) {
        console.error('Error loading overview:', error);
    }
}

function renderNetflowChart(data) {
    const ctx = document.getElementById('netflow-chart');
    if (!ctx) return;

    // Destroy existing chart
    if (netflowChart) {
        netflowChart.destroy();
    }

    const labels = data.slice(0, 10).map(d => d.token);
    const values = data.slice(0, 10).map(d => d.inflow);
    const colors = values.map(v => v >= 0 ? CHART_COLORS.positive : CHART_COLORS.negative);

    netflowChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderWidth: 0,
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (context) => fmt.usdSigned(context.raw)
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: CHART_COLORS.border },
                    ticks: {
                        callback: (value) => fmt.usd(value)
                    }
                },
                y: {
                    grid: { display: false },
                }
            }
        }
    });
}

function renderHoldingsChart(data) {
    const ctx = document.getElementById('holdings-chart');
    if (!ctx) return;

    if (holdingsChart) {
        holdingsChart.destroy();
    }

    const labels = data.slice(0, 10).map(d => d.token);
    const values = data.slice(0, 10).map(d => d.value);

    holdingsChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: CHART_COLORS.neutral,
                borderWidth: 0,
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (context) => fmt.usd(context.raw)
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: CHART_COLORS.border },
                    ticks: {
                        callback: (value) => fmt.usd(value)
                    }
                },
                y: {
                    grid: { display: false },
                }
            }
        }
    });
}

function renderTrendsChart(data) {
    const ctx = document.getElementById('trends-chart');
    if (!ctx) return;

    if (trendsChart) {
        trendsChart.destroy();
    }

    // Take top 8 tokens for readability
    const topData = data.slice(0, 8);
    const labels = topData.map(d => d.token);

    trendsChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '1h',
                    data: topData.map(d => d['1h'] || 0),
                    backgroundColor: '#B3B3B3',
                },
                {
                    label: '24h',
                    data: topData.map(d => d['24h'] || 0),
                    backgroundColor: '#666666',
                },
                {
                    label: '7d',
                    data: topData.map(d => d['7d'] || 0),
                    backgroundColor: '#1A1A1A',
                },
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        boxWidth: 12,
                        padding: 8,
                    }
                },
                tooltip: {
                    callbacks: {
                        label: (context) => `${context.dataset.label}: ${fmt.usdSigned(context.raw)}`
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                },
                y: {
                    grid: { color: CHART_COLORS.border },
                    ticks: {
                        callback: (value) => fmt.usd(value)
                    }
                }
            }
        }
    });
}

function renderSectorChart(data) {
    const ctx = document.getElementById('sector-chart');
    if (!ctx) return;

    if (sectorChart) {
        sectorChart.destroy();
    }

    const labels = data.map(d => d.name);
    const values = data.map(d => d.count);

    sectorChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: CHART_COLORS.sectors.slice(0, labels.length),
                borderWidth: 0,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        boxWidth: 12,
                        padding: 6,
                        font: { size: 10 }
                    }
                },
            },
        }
    });
}

// === Sparkline Rendering ===

function renderSparkline(data, momentum) {
    if (!data || data.length < 2) return '';

    // Normalize data to fit in a small SVG
    const width = 60;
    const height = 16;
    const padding = 2;

    const values = data.filter(v => v !== null && v !== undefined);
    if (values.length < 2) return '';

    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;

    // Generate path points
    const points = values.map((v, i) => {
        const x = padding + (i / (values.length - 1)) * (width - padding * 2);
        const y = height - padding - ((v - min) / range) * (height - padding * 2);
        return `${x},${y}`;
    });

    const color = momentum === 'accelerating' ? CHART_COLORS.positive :
                  momentum === 'decelerating' ? CHART_COLORS.negative :
                  CHART_COLORS.neutral;

    return `
        <svg class="sparkline" width="${width}" height="${height}" style="vertical-align: middle; margin-left: 4px;">
            <polyline
                fill="none"
                stroke="${color}"
                stroke-width="1.5"
                points="${points.join(' ')}"
            />
        </svg>
    `;
}

// === Data Loading ===

async function loadData() {
    const chains = state.selectedChains.join(',');

    if (state.currentView === 'purchases') {
        await loadPurchases(chains);
    } else if (state.currentView === 'trades') {
        await loadTrades(chains);
    } else if (state.currentView === 'perps') {
        await loadPerps();
    }

    updateLastUpdated();
}

async function loadPurchases(chains) {
    const body = $('#purchases-body');
    body.innerHTML = '<tr><td colspan="6" class="loading">Loading data...</td></tr>';

    try {
        const data = await api.get(`/api/v1/purchases?chains=${chains}&limit=50`);

        // Render table
        if (!data.tokens || data.tokens.length === 0) {
            body.innerHTML = '<tr><td colspan="6">No data available</td></tr>';
            return;
        }

        body.innerHTML = data.tokens.map(token => `
            <tr class="token-row" data-chain="${token.chain}" data-address="${token.token_address}">
                <td>
                    <strong>${token.token_symbol}</strong>
                    ${token.sectors && token.sectors.length ? `<br><small style="color: var(--color-text-muted)">${token.sectors[0]}</small>` : ''}
                </td>
                <td>${token.chain}</td>
                <td class="numeric">${fmt.number(token.smart_money_holders)}</td>
                <td class="numeric ${token.net_flow_24h_usd > 0 ? 'positive' : 'negative'}">
                    ${fmt.usdSigned(token.net_flow_24h_usd)}
                    ${renderSparkline(token.netflow_trend, token.momentum)}
                </td>
                <td class="numeric">${fmt.usd(token.total_value_usd)}</td>
                <td>
                    <span class="signal signal-${token.signal}">${token.signal}</span>
                    <span class="signal-strength">${token.signal_strength}</span>
                    ${token.momentum !== 'steady' ? `<span class="momentum momentum-${token.momentum}">${token.momentum === 'accelerating' ? '↑' : '↓'}</span>` : ''}
                </td>
            </tr>
        `).join('');

        // Add click handlers for drilldown
        body.querySelectorAll('.token-row').forEach(row => {
            row.addEventListener('click', () => {
                const chain = row.dataset.chain;
                const address = row.dataset.address;
                loadDrilldown(chain, address);
            });
        });

    } catch (error) {
        console.error('Error loading purchases:', error);
        body.innerHTML = `<tr><td colspan="6">Error loading data: ${error.message}</td></tr>`;
    }
}

async function loadTrades(chains) {
    const body = $('#trades-body');
    body.innerHTML = '<tr><td colspan="7" class="loading">Loading data...</td></tr>';

    try {
        const data = await api.get(`/api/v1/trades?chains=${chains}&limit=50`);

        // Update stats
        $('#total-trades').textContent = fmt.number(data.total_trades);
        $('#buy-count').textContent = fmt.number(data.buy_count);
        $('#sell-count').textContent = fmt.number(data.sell_count);

        // Update narrative
        $('#trades-narrative').textContent = data.narrative || 'No narrative available.';

        // Render table
        if (!data.trades || data.trades.length === 0) {
            body.innerHTML = '<tr><td colspan="7">No trades available</td></tr>';
            return;
        }

        body.innerHTML = data.trades.map(trade => `
            <tr>
                <td>${fmt.time(trade.timestamp)}</td>
                <td title="${trade.wallet_label}">${trade.wallet_label}</td>
                <td>
                    <span class="signal signal-${trade.action === 'BUY' ? 'accumulating' : 'distributing'}">
                        ${trade.action}
                    </span>
                </td>
                <td>${trade.token_bought}</td>
                <td>${trade.token_sold}</td>
                <td class="numeric">${fmt.usd(trade.amount_usd)}</td>
                <td>${trade.chain}</td>
            </tr>
        `).join('');

    } catch (error) {
        console.error('Error loading trades:', error);
        body.innerHTML = `<tr><td colspan="7">Error loading data: ${error.message}</td></tr>`;
    }
}

async function loadPerps() {
    const body = $('#perps-body');
    body.innerHTML = '<tr><td colspan="7" class="loading">Loading data...</td></tr>';

    try {
        const data = await api.get('/api/v1/perps?limit=50');

        // Update stats
        $('#perp-total').textContent = fmt.number(data.total_trades);
        $('#long-count').textContent = fmt.number(data.long_count);
        $('#short-count').textContent = fmt.number(data.short_count);

        const sentiment = data.sentiment || 'neutral';
        const sentimentEl = $('#perp-sentiment');
        sentimentEl.textContent = sentiment.toUpperCase();
        sentimentEl.className = `stat-value ${sentiment === 'bullish' ? 'positive' : sentiment === 'bearish' ? 'negative' : ''}`;

        // Render table
        if (!data.trades || data.trades.length === 0) {
            body.innerHTML = '<tr><td colspan="7">No perp trades available</td></tr>';
            return;
        }

        body.innerHTML = data.trades.map(trade => `
            <tr>
                <td>${fmt.time(trade.timestamp)}</td>
                <td title="${trade.trader}">${trade.trader}</td>
                <td>${trade.token}</td>
                <td>
                    <span class="signal signal-${trade.side === 'LONG' ? 'accumulating' : 'distributing'}">
                        ${trade.side}
                    </span>
                </td>
                <td>${trade.action}</td>
                <td class="numeric">${fmt.usd(trade.value_usd)}</td>
                <td class="numeric">${trade.price ? '$' + trade.price.toLocaleString() : '--'}</td>
            </tr>
        `).join('');

    } catch (error) {
        console.error('Error loading perps:', error);
        body.innerHTML = `<tr><td colspan="7">Error loading data: ${error.message}</td></tr>`;
    }
}

async function loadDrilldown(chain, tokenAddress) {
    state.currentToken = { chain, address: tokenAddress };
    showView('drilldown');

    // Show loading state
    $('#drilldown-title').textContent = 'Loading...';
    $('#drilldown-narrative').textContent = 'Loading analysis...';
    $('#flow-intelligence').innerHTML = '<div class="loading">Loading...</div>';
    $('#holders-body').innerHTML = '<tr><td colspan="3" class="loading">Loading...</td></tr>';

    try {
        // Load main drilldown data, historical data, and transfer data in parallel
        const [data, historyData, transferData] = await Promise.all([
            api.get(`/api/v1/token/${chain}/${tokenAddress}`),
            api.get(`/api/v1/history/${chain}/${tokenAddress}?days=30`).catch(() => null),
            api.get(`/api/v1/transfers/${chain}/${tokenAddress}?days=7`).catch(() => null),
        ]);

        // Update title
        $('#drilldown-title').textContent = `${data.token_symbol} Analysis`;

        // Update stats
        $('#total-holders').textContent = fmt.number(data.holder_breakdown?.total || 0);
        $('#sm-holders').textContent = fmt.number(data.holder_breakdown?.smart_money || 0);
        $('#whale-holders').textContent = fmt.number(data.holder_breakdown?.whale || 0);
        $('#exchange-holders').textContent = fmt.number(data.holder_breakdown?.exchange || 0);

        // Update narrative with historical context
        let narrative = data.narrative?.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') || 'No analysis available.';
        if (historyData?.metrics) {
            const trend = historyData.metrics.trend;
            const changePct = historyData.metrics.period_change_pct;
            narrative += `<br><br><strong>30-Day Trend:</strong> ${trend} (${changePct > 0 ? '+' : ''}${changePct.toFixed(1)}% position change)`;
        }
        if (transferData?.summary) {
            narrative += `<br><strong>CEX Flow Signal:</strong> ${transferData.summary.flow_signal}`;
        }
        $('#drilldown-narrative').innerHTML = narrative;

        // Render flow intelligence
        const flows = data.flow_intelligence;
        if (flows) {
            $('#flow-intelligence').innerHTML = `
                <div class="flow-segment">
                    <span class="flow-label">Smart Money</span>
                    <span class="flow-value ${flows.smart_money?.net_flow_usd > 0 ? 'positive' : 'negative'}">
                        ${fmt.usdSigned(flows.smart_money?.net_flow_usd)}
                    </span>
                </div>
                <div class="flow-segment">
                    <span class="flow-label">Whales</span>
                    <span class="flow-value ${flows.whale?.net_flow_usd > 0 ? 'positive' : 'negative'}">
                        ${fmt.usdSigned(flows.whale?.net_flow_usd)}
                    </span>
                </div>
                <div class="flow-segment">
                    <span class="flow-label">Exchanges</span>
                    <span class="flow-value ${flows.exchange?.net_flow_usd > 0 ? 'positive' : 'negative'}">
                        ${fmt.usdSigned(flows.exchange?.net_flow_usd)}
                    </span>
                </div>
                <div class="flow-segment">
                    <span class="flow-label">Fresh Wallets</span>
                    <span class="flow-value ${flows.fresh_wallets?.net_flow_usd > 0 ? 'positive' : 'negative'}">
                        ${fmt.usdSigned(flows.fresh_wallets?.net_flow_usd)}
                    </span>
                </div>
                <div class="flow-segment">
                    <span class="flow-label">Top PnL Traders</span>
                    <span class="flow-value ${flows.top_pnl?.net_flow_usd > 0 ? 'positive' : 'negative'}">
                        ${fmt.usdSigned(flows.top_pnl?.net_flow_usd)}
                    </span>
                </div>
                ${transferData?.summary ? `
                <div class="flow-segment" style="margin-top: 12px; border-top: 1px solid var(--color-border); padding-top: 8px;">
                    <span class="flow-label">CEX Net Flow (7d)</span>
                    <span class="flow-value ${transferData.summary.net_cex_flow < 0 ? 'positive' : 'negative'}">
                        ${fmt.usdSigned(-transferData.summary.net_cex_flow)}
                    </span>
                </div>
                ` : ''}
            `;
        }

        // Render top holders
        if (data.top_holders && data.top_holders.length > 0) {
            $('#holders-body').innerHTML = data.top_holders.map(h => `
                <tr>
                    <td title="${h.label || h.address}">${h.label || fmt.address(h.address)}</td>
                    <td class="numeric">${fmt.usd(h.value_usd)}</td>
                    <td class="numeric ${h.balance_change_24h > 0 ? 'positive' : h.balance_change_24h < 0 ? 'negative' : ''}">
                        ${fmt.percent(h.balance_change_24h)}
                    </td>
                </tr>
            `).join('');
        } else {
            $('#holders-body').innerHTML = '<tr><td colspan="3">No holder data</td></tr>';
        }

        // Render historical chart if data available
        if (historyData?.chart_data?.length > 0) {
            renderHistoricalChart(historyData.chart_data);
        }

        // Render transfer flow chart if data available
        if (transferData?.summary) {
            renderTransferChart(transferData.summary);
        }

    } catch (error) {
        console.error('Error loading drilldown:', error);
        $('#drilldown-narrative').textContent = `Error loading data: ${error.message}`;
    }
}

// === Historical Charts ===

function renderHistoricalChart(data) {
    const container = document.getElementById('history-chart');
    if (!container) return;

    if (historyChart) {
        historyChart.destroy();
    }

    const labels = data.map(d => {
        const date = new Date(d.date);
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    });
    const values = data.map(d => d.value_usd);

    historyChart = new Chart(container, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Smart Money Position',
                data: values,
                borderColor: CHART_COLORS.neutral,
                backgroundColor: 'rgba(102, 102, 102, 0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                pointHoverRadius: 4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (context) => fmt.usd(context.raw)
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { maxTicksLimit: 6 }
                },
                y: {
                    grid: { color: CHART_COLORS.border },
                    ticks: {
                        callback: (value) => fmt.usd(value)
                    }
                }
            }
        }
    });
}

function renderTransferChart(summary) {
    const container = document.getElementById('transfer-chart');
    if (!container) return;

    if (transferChart) {
        transferChart.destroy();
    }

    const labels = ['CEX Deposits', 'CEX Withdrawals', 'DEX Activity'];
    const values = [
        summary.cex_deposit_volume || 0,
        summary.cex_withdrawal_volume || 0,
        summary.dex_volume || 0,
    ];
    const colors = [
        CHART_COLORS.negative,  // CEX deposits = bearish
        CHART_COLORS.positive,  // CEX withdrawals = bullish
        CHART_COLORS.neutral,   // DEX = neutral
    ];

    transferChart = new Chart(container, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderWidth: 0,
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (context) => fmt.usd(context.raw)
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: CHART_COLORS.border },
                    ticks: {
                        callback: (value) => fmt.usd(value)
                    }
                },
                y: {
                    grid: { display: false },
                }
            }
        }
    });
}

function updateLastUpdated() {
    const now = new Date();
    $('#last-updated').textContent = `Updated: ${now.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit'
    })}`;
}

// Auto-refresh every 5 minutes
setInterval(() => {
    loadOverview();
    loadData();
}, 5 * 60 * 1000);
