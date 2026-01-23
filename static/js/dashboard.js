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

    // Format balance change as token amount (not percentage)
    balanceChange(value) {
        if (value === null || value === undefined) return '--';
        const abs = Math.abs(value);
        const sign = value > 0 ? '+' : value < 0 ? '' : '';
        if (abs >= 1_000_000_000) {
            return `${sign}${(value / 1_000_000_000).toFixed(1)}B`;
        } else if (abs >= 1_000_000) {
            return `${sign}${(value / 1_000_000).toFixed(1)}M`;
        } else if (abs >= 1_000) {
            return `${sign}${(value / 1_000).toFixed(1)}K`;
        } else if (abs >= 1) {
            return `${sign}${value.toFixed(0)}`;
        }
        return `${sign}${value.toFixed(2)}`;
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
        $('#accumulating').textContent = fmt.number(data.summary?.tokens_accumulating);
        $('#distributing').textContent = fmt.number(data.summary?.tokens_distributing);
        $('#buy-vol').textContent = fmt.usd(data.trade_summary?.buy_volume_usd);
        $('#sell-vol').textContent = fmt.usd(data.trade_summary?.sell_volume_usd);

        // Enhanced Net Flow card with breakdown
        const breakdown = data.net_flow_breakdown;
        if (breakdown) {
            const netFlowEl = $('#net-flow');
            netFlowEl.textContent = fmt.usdSigned(breakdown.net);
            netFlowEl.className = `stat-value ${breakdown.net > 0 ? 'positive' : 'negative'}`;

            // Update net flow details if element exists
            const detailsEl = $('#net-flow-details');
            if (detailsEl) {
                const topInflows = breakdown.top_inflows?.slice(0, 3) || [];
                const topOutflows = breakdown.top_outflows?.slice(0, 3) || [];

                detailsEl.innerHTML = `
                    <div class="flow-breakdown">
                        <span class="positive">+${fmt.usd(breakdown.inflow)}</span>
                        <span class="neutral"> / </span>
                        <span class="negative">-${fmt.usd(breakdown.outflow)}</span>
                    </div>
                    <div class="flow-sentiment ${breakdown.sentiment}">${breakdown.sentiment.toUpperCase()}</div>
                    ${topInflows.length > 0 ? `
                    <div class="top-movers">
                        <span class="movers-label">Top inflows:</span>
                        ${topInflows.map(t => `<span class="mover positive">${t.token}</span>`).join(' ')}
                    </div>
                    ` : ''}
                `;
            }
        } else {
            // Fallback to old format
            $('#net-flow').textContent = fmt.usdSigned(data.summary?.net_flow_24h);
            $('#net-flow').className = `stat-value ${data.summary?.net_flow_24h > 0 ? 'positive' : 'negative'}`;
        }

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
    } else if (state.currentView === 'funds') {
        await loadFunds(chains);
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

// Store funds data for detail view
let currentFundsData = null;

async function loadFunds(chains) {
    const body = $('#funds-body');
    const tradesBody = $('#fund-trades-body');
    body.innerHTML = '<tr><td colspan="3" class="loading">Loading data...</td></tr>';
    tradesBody.innerHTML = '<tr><td colspan="7" class="loading">Loading data...</td></tr>';

    // Hide detail view
    const detailCard = document.getElementById('fund-detail-card');
    if (detailCard) detailCard.style.display = 'none';

    try {
        const data = await api.get(`/api/v1/funds?chains=${chains}`);
        currentFundsData = data;

        // Update stats
        $('#total-funds').textContent = fmt.number(data.summary?.total_funds || 0);
        $('#funds-total-value').textContent = fmt.usd(data.summary?.total_fund_value_usd);
        $('#funds-positions').textContent = fmt.number(data.summary?.total_positions || 0);
        $('#funds-buy-count').textContent = fmt.number(data.summary?.recent_buy_count || 0);
        $('#funds-sell-count').textContent = fmt.number(data.summary?.recent_sell_count || 0);

        // Render funds table
        if (!data.funds || data.funds.length === 0) {
            body.innerHTML = '<tr><td colspan="3">No fund holdings detected</td></tr>';
        } else {
            body.innerHTML = data.funds.map((fund, idx) => `
                <tr class="fund-row" data-fund-index="${idx}" style="cursor: pointer;">
                    <td><strong>${fund.name}</strong></td>
                    <td class="numeric">${fmt.usd(fund.total_value_usd)}</td>
                    <td class="numeric">${fund.total_tokens_held}</td>
                </tr>
            `).join('');

            // Add click handlers for fund detail
            body.querySelectorAll('.fund-row').forEach(row => {
                row.addEventListener('click', () => {
                    const idx = parseInt(row.dataset.fundIndex);
                    showFundDetail(data.funds[idx]);
                });
            });
        }

        // Render fund trades table
        if (!data.recent_trades || data.recent_trades.length === 0) {
            tradesBody.innerHTML = '<tr><td colspan="7">No recent fund trades</td></tr>';
        } else {
            tradesBody.innerHTML = data.recent_trades.map(trade => `
                <tr>
                    <td>${fmt.time(trade.timestamp)}</td>
                    <td title="${trade.fund}">${trade.fund}</td>
                    <td>
                        <span class="signal signal-${trade.action === 'BUY' ? 'accumulating' : 'distributing'}">
                            ${trade.action}
                        </span>
                    </td>
                    <td>${trade.token_bought}</td>
                    <td>${trade.token_sold}</td>
                    <td class="numeric">${fmt.usd(trade.value_usd)}</td>
                    <td>${trade.chain}</td>
                </tr>
            `).join('');
        }

    } catch (error) {
        console.error('Error loading funds:', error);
        body.innerHTML = `<tr><td colspan="3">Error loading data: ${error.message}</td></tr>`;
    }
}

function showFundDetail(fund) {
    const detailCard = document.getElementById('fund-detail-card');
    const fundsCard = document.querySelector('#funds-view .card:first-of-type');

    if (!detailCard || !fund) return;

    // Update header
    document.getElementById('fund-detail-name').textContent = `${fund.name} Positions`;

    // Render positions table
    const positionsBody = document.getElementById('fund-positions-body');
    if (fund.positions && fund.positions.length > 0) {
        positionsBody.innerHTML = fund.positions.map(pos => `
            <tr>
                <td><strong>${pos.token_symbol}</strong></td>
                <td>${pos.chain}</td>
                <td class="numeric">${fmt.usd(pos.value_usd)}</td>
                <td class="numeric">${fmt.number(Math.round(pos.token_amount || 0))}</td>
                <td class="numeric ${pos.balance_change_24h > 0 ? 'positive' : pos.balance_change_24h < 0 ? 'negative' : ''}">
                    ${fmt.balanceChange(pos.balance_change_24h)}
                </td>
                <td class="numeric ${pos.balance_change_30d > 0 ? 'positive' : pos.balance_change_30d < 0 ? 'negative' : ''}">
                    ${fmt.balanceChange(pos.balance_change_30d)}
                </td>
                <td class="numeric">${fmt.number(Math.round(pos.total_inflow || 0))}</td>
                <td class="numeric">${fmt.number(Math.round(pos.total_outflow || 0))}</td>
            </tr>
        `).join('');
    } else {
        positionsBody.innerHTML = '<tr><td colspan="8">No positions found</td></tr>';
    }

    // Show detail card
    detailCard.style.display = 'block';

    // Add back button handler
    document.getElementById('fund-back-btn').onclick = () => {
        detailCard.style.display = 'none';
    };

    // Scroll to detail
    detailCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function loadDrilldown(chain, tokenAddress) {
    state.currentToken = { chain, address: tokenAddress };
    showView('drilldown');

    // Restore chart canvases (in case they were replaced with no-data message)
    const drilldownView = document.getElementById('drilldown-view');
    const chartContainers = drilldownView?.querySelectorAll('.chart-container');
    if (chartContainers) {
        chartContainers.forEach((container, idx) => {
            const canvasId = idx === 0 ? 'history-chart' : 'transfer-chart';
            if (!container.querySelector('canvas')) {
                container.innerHTML = `<canvas id="${canvasId}"></canvas>`;
            }
        });
    }

    // Destroy existing charts
    if (historyChart) {
        historyChart.destroy();
        historyChart = null;
    }
    if (transferChart) {
        transferChart.destroy();
        transferChart = null;
    }

    // Show loading state
    $('#drilldown-title').textContent = 'Loading...';
    $('#drilldown-narrative').textContent = 'Loading analysis...';
    $('#flow-intelligence').innerHTML = '<div class="loading">Loading...</div>';
    $('#holders-body').innerHTML = '<tr><td colspan="5" class="loading">Loading...</td></tr>';
    $('#fund-holdings-body').innerHTML = '<tr><td colspan="9" class="loading">Loading...</td></tr>';
    $('#most-active-body').innerHTML = '<tr><td colspan="4" class="loading">Loading...</td></tr>';

    try {
        // Load drilldown data (now includes netflow_trend, buyer_seller_summary, fund_holdings, most_active)
        const data = await api.get(`/api/v1/token/${chain}/${tokenAddress}`);

        // Update title
        $('#drilldown-title').textContent = `${data.token_symbol} Analysis`;

        // Update stats
        $('#total-holders').textContent = fmt.number(data.holder_breakdown?.total || 0);
        const fundHoldersEl = $('#fund-holders');
        if (fundHoldersEl) {
            fundHoldersEl.textContent = fmt.number(data.holder_summary?.total_funds || 0);
        }
        $('#sm-holders').textContent = fmt.number(data.holder_breakdown?.smart_money || 0);
        $('#whale-holders').textContent = fmt.number(data.holder_breakdown?.whale || 0);
        $('#exchange-holders').textContent = fmt.number(data.holder_breakdown?.exchange || 0);

        // Update narrative with flow context
        let narrative = data.narrative?.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') || 'No analysis available.';
        if (data.netflow_trend) {
            const momentum = data.netflow_trend.momentum;
            const flow30d = data.netflow_trend.values[3];
            narrative += `<br><br><strong>30-Day Flow:</strong> ${fmt.usdSigned(flow30d)} (${momentum})`;
        }
        if (data.buyer_seller_summary) {
            const sentiment = data.buyer_seller_summary.sentiment;
            narrative += `<br><strong>Recent Activity:</strong> ${sentiment} (${data.buyer_seller_summary.buyer_count} buyers, ${data.buyer_seller_summary.seller_count} sellers)`;
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
            `;
        }

        // Render fund holdings table
        renderFundHoldingsTable(data.fund_holdings || []);

        // Render most active holders table
        renderActivityTable(data.most_active || []);

        // Render top holders
        if (data.top_holders && data.top_holders.length > 0) {
            $('#holders-body').innerHTML = data.top_holders.map(h => `
                <tr>
                    <td title="${h.label || h.address}">${h.label || fmt.address(h.address)}</td>
                    <td><span class="holder-type-badge holder-type-${h.type || 'other'}">${h.type || 'other'}</span></td>
                    <td class="numeric">${fmt.usd(h.value_usd)}</td>
                    <td class="numeric ${h.balance_change_24h > 0 ? 'positive' : h.balance_change_24h < 0 ? 'negative' : ''}">
                        ${fmt.balanceChange(h.balance_change_24h)}
                    </td>
                    <td class="numeric ${h.balance_change_7d > 0 ? 'positive' : h.balance_change_7d < 0 ? 'negative' : ''}">
                        ${fmt.balanceChange(h.balance_change_7d)}
                    </td>
                </tr>
            `).join('');
        } else {
            $('#holders-body').innerHTML = '<tr><td colspan="5">No holder data</td></tr>';
        }

        // Render historical chart using netflow trend
        if (data.netflow_trend?.values) {
            const hasData = data.netflow_trend.values.some(v => v !== 0);
            if (hasData) {
                renderHistoricalChart(data.netflow_trend);
            } else {
                renderNoDataChart('history-chart', 'No netflow data available for this token');
            }
        } else {
            renderNoDataChart('history-chart', 'No netflow data available');
        }

        // Render buyer/seller activity chart
        if (data.buyer_seller_summary) {
            const hasActivity = data.buyer_seller_summary.buyer_volume > 0 || data.buyer_seller_summary.seller_volume > 0;
            if (hasActivity) {
                renderTransferChart(data.buyer_seller_summary);
            } else {
                renderNoDataChart('transfer-chart', 'No recent buyer/seller activity');
            }
        } else {
            renderNoDataChart('transfer-chart', 'No activity data available');
        }

    } catch (error) {
        console.error('Error loading drilldown:', error);
        $('#drilldown-narrative').textContent = `Error loading data: ${error.message}`;
    }
}

// === Fund Holdings & Activity Tables ===

function renderFundHoldingsTable(fundHoldings) {
    const body = $('#fund-holdings-body');
    if (!body) return;

    if (!fundHoldings || fundHoldings.length === 0) {
        body.innerHTML = '<tr><td colspan="9" class="no-data">No institutional/fund holdings detected</td></tr>';
        // Hide the card if no data
        const card = document.getElementById('fund-holdings-card');
        if (card) card.style.display = 'none';
        return;
    }

    // Show the card
    const card = document.getElementById('fund-holdings-card');
    if (card) card.style.display = 'block';

    body.innerHTML = fundHoldings.map(h => `
        <tr>
            <td title="${h.label || h.address}">${h.label || fmt.address(h.address)}</td>
            <td><span class="holder-type-badge holder-type-${h.type || 'fund'}">${h.type || 'fund'}</span></td>
            <td class="numeric">${fmt.usd(h.value_usd)}</td>
            <td class="numeric">${fmt.number(Math.round(h.token_amount || 0))}</td>
            <td class="numeric ${h.balance_change_24h > 0 ? 'positive' : h.balance_change_24h < 0 ? 'negative' : ''}">
                ${fmt.balanceChange(h.balance_change_24h)}
            </td>
            <td class="numeric ${h.balance_change_7d > 0 ? 'positive' : h.balance_change_7d < 0 ? 'negative' : ''}">
                ${fmt.balanceChange(h.balance_change_7d)}
            </td>
            <td class="numeric ${h.balance_change_30d > 0 ? 'positive' : h.balance_change_30d < 0 ? 'negative' : ''}">
                ${fmt.balanceChange(h.balance_change_30d)}
            </td>
            <td class="numeric">${fmt.number(Math.round(h.total_inflow || 0))}</td>
            <td class="numeric">${fmt.number(Math.round(h.total_outflow || 0))}</td>
        </tr>
    `).join('');
}

function renderActivityTable(mostActive) {
    const body = $('#most-active-body');
    if (!body) return;

    if (!mostActive || mostActive.length === 0) {
        body.innerHTML = '<tr><td colspan="4" class="no-data">No activity data available</td></tr>';
        return;
    }

    body.innerHTML = mostActive.map(h => `
        <tr>
            <td title="${h.label || h.address}">${h.label || fmt.address(h.address)}</td>
            <td><span class="holder-type-badge holder-type-${h.type || 'other'}">${h.type || 'other'}</span></td>
            <td class="numeric">${fmt.usd(h.value_usd)}</td>
            <td class="numeric ${h.balance_change_30d > 0 ? 'positive' : h.balance_change_30d < 0 ? 'negative' : ''}">
                ${fmt.balanceChange(h.balance_change_30d)}
            </td>
        </tr>
    `).join('');
}

// === Historical Charts ===

function renderNoDataChart(canvasId, message) {
    const container = document.getElementById(canvasId);
    if (!container) return;

    // Get the parent container and replace canvas with message
    const parent = container.parentElement;
    if (parent) {
        parent.innerHTML = `
            <div class="no-data-message">
                <span>${message}</span>
            </div>
        `;
    }
}

function renderHistoricalChart(netflowTrend) {
    const container = document.getElementById('history-chart');
    if (!container) return;

    if (historyChart) {
        historyChart.destroy();
    }

    // Use netflow trend data: [1h, 24h, 7d, 30d]
    const labels = netflowTrend.periods || ['1h', '24h', '7d', '30d'];
    const values = netflowTrend.values || [0, 0, 0, 0];
    const momentum = netflowTrend.momentum || 'steady';

    // Color based on momentum
    const lineColor = momentum === 'accelerating' ? CHART_COLORS.positive :
                      momentum === 'decelerating' ? CHART_COLORS.negative :
                      CHART_COLORS.neutral;

    historyChart = new Chart(container, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Net Flow',
                data: values,
                borderColor: lineColor,
                backgroundColor: lineColor + '20',
                fill: true,
                tension: 0.3,
                pointRadius: 4,
                pointHoverRadius: 6,
                pointBackgroundColor: lineColor,
            }]
        },
        options: {
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

function renderTransferChart(buyerSellerSummary) {
    const container = document.getElementById('transfer-chart');
    if (!container) return;

    if (transferChart) {
        transferChart.destroy();
    }

    // Use buyer/seller data from drilldown
    const labels = ['Buyers', 'Sellers'];
    const values = [
        buyerSellerSummary.buyer_volume || 0,
        buyerSellerSummary.seller_volume || 0,
    ];
    const colors = [
        CHART_COLORS.positive,  // Buyers = bullish
        CHART_COLORS.negative,  // Sellers = bearish
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
                        label: (context) => `${fmt.usd(context.raw)} (${context.label === 'Buyers' ? buyerSellerSummary.buyer_count : buyerSellerSummary.seller_count} wallets)`
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
