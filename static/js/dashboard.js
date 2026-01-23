/**
 * Fund Portfolio Tracker - Dashboard JavaScript
 */

// API helper
const API = {
    async get(endpoint) {
        const response = await fetch(`/api/v1${endpoint}`);
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        return response.json();
    }
};

// Formatting utilities
const fmt = {
    usd(value) {
        if (value === null || value === undefined) return '-';
        if (Math.abs(value) >= 1e9) {
            return '$' + (value / 1e9).toFixed(2) + 'B';
        }
        if (Math.abs(value) >= 1e6) {
            return '$' + (value / 1e6).toFixed(2) + 'M';
        }
        if (Math.abs(value) >= 1e3) {
            return '$' + (value / 1e3).toFixed(2) + 'K';
        }
        return '$' + value.toFixed(2);
    },

    number(value) {
        if (value === null || value === undefined) return '-';
        if (Math.abs(value) >= 1e9) {
            return (value / 1e9).toFixed(2) + 'B';
        }
        if (Math.abs(value) >= 1e6) {
            return (value / 1e6).toFixed(2) + 'M';
        }
        if (Math.abs(value) >= 1e3) {
            return (value / 1e3).toFixed(2) + 'K';
        }
        if (Math.abs(value) < 0.01 && value !== 0) {
            return value.toExponential(2);
        }
        return value.toFixed(2);
    },

    percent(value) {
        if (value === null || value === undefined) return '-';
        const sign = value >= 0 ? '+' : '';
        return sign + value.toFixed(2) + '%';
    },

    date(isoString) {
        const d = new Date(isoString);
        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
};

// Chart instances
let allocationChart = null;
let flowChart = null;

// Chart colors
const COLORS = [
    '#2563eb', '#7c3aed', '#db2777', '#dc2626', '#ea580c',
    '#ca8a04', '#16a34a', '#0d9488', '#0891b2', '#6366f1'
];

// State
let currentFund = null;

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    await loadFunds();
    setupEventListeners();
});

async function loadFunds() {
    try {
        const data = await API.get('/funds');
        const selector = document.getElementById('fundSelector');

        data.funds.forEach(fund => {
            const option = document.createElement('option');
            option.value = fund.id;
            option.textContent = fund.name;
            selector.appendChild(option);
        });
    } catch (error) {
        console.error('Failed to load funds:', error);
    }
}

function setupEventListeners() {
    document.getElementById('fundSelector').addEventListener('change', async (e) => {
        const fundId = e.target.value;
        if (fundId) {
            currentFund = fundId;
            await loadFundData(fundId);
        }
    });

    document.getElementById('compareBtn').addEventListener('click', loadComparison);
}

async function loadFundData(fundId) {
    document.body.classList.add('loading');

    try {
        const [portfolio, transfers, flows] = await Promise.all([
            API.get(`/fund/${fundId}/portfolio`),
            API.get(`/fund/${fundId}/transfers?limit=20`),
            API.get(`/fund/${fundId}/flows`)
        ]);

        updateSummaryCards(portfolio);
        updateHoldingsTable(portfolio);
        updateActivityTable(transfers);
        updateAllocationChart(portfolio);
        updateFlowChart(flows);
        updateLastUpdated();
    } catch (error) {
        console.error('Failed to load fund data:', error);
    } finally {
        document.body.classList.remove('loading');
    }
}

function updateSummaryCards(portfolio) {
    document.getElementById('totalValue').textContent = fmt.usd(portfolio.total_value_usd);

    const costBasisEl = document.getElementById('costBasis');
    costBasisEl.textContent = fmt.usd(portfolio.total_cost_basis);

    const pnlEl = document.getElementById('unrealizedPnl');
    pnlEl.textContent = fmt.usd(portfolio.total_unrealized_pnl);
    pnlEl.className = 'card-value ' + (portfolio.total_unrealized_pnl >= 0 ? 'positive' : 'negative');

    const pctEl = document.getElementById('pnlPercent');
    pctEl.textContent = fmt.percent(portfolio.total_pnl_pct);
    pctEl.className = 'card-value ' + (portfolio.total_pnl_pct >= 0 ? 'positive' : 'negative');
}

function updateHoldingsTable(portfolio) {
    const tbody = document.getElementById('holdingsBody');

    if (!portfolio.holdings || portfolio.holdings.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="no-data">No holdings found</td></tr>';
        return;
    }

    // Create a map of P/L data by symbol
    const pnlMap = {};
    portfolio.pnl_summary.forEach(p => {
        pnlMap[p.symbol] = p;
    });

    tbody.innerHTML = portfolio.holdings.map(h => {
        const pnl = pnlMap[h.symbol] || {};
        const pnlClass = (pnl.unrealized_pnl || 0) >= 0 ? 'positive' : 'negative';

        return `
            <tr>
                <td><strong>${h.symbol}</strong><br><small style="color: #6c757d">${h.name}</small></td>
                <td>${h.chain}</td>
                <td>${fmt.number(h.balance)}</td>
                <td>${fmt.usd(h.price)}</td>
                <td>${fmt.usd(h.value_usd)}</td>
                <td>${fmt.usd(pnl.cost_basis || 0)}</td>
                <td class="${pnlClass}">${fmt.usd(pnl.unrealized_pnl || 0)}</td>
                <td class="${pnlClass}">${fmt.percent(pnl.unrealized_pnl_pct || 0)}</td>
            </tr>
        `;
    }).join('');
}

function updateActivityTable(transfers) {
    const tbody = document.getElementById('activityBody');

    if (!transfers.transfers || transfers.transfers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="no-data">No recent activity</td></tr>';
        return;
    }

    tbody.innerHTML = transfers.transfers.map(t => {
        const typeClass = t.type === 'Received' ? 'positive' : 'negative';
        return `
            <tr>
                <td>${fmt.date(t.timestamp)}</td>
                <td class="${typeClass}">${t.type}</td>
                <td>${t.token}</td>
                <td>${fmt.number(t.amount)}</td>
                <td>${fmt.usd(t.value_usd)}</td>
                <td>${t.counterparty}</td>
                <td>${t.chain}</td>
            </tr>
        `;
    }).join('');
}

function updateAllocationChart(portfolio) {
    const ctx = document.getElementById('allocationChart').getContext('2d');

    if (allocationChart) {
        allocationChart.destroy();
    }

    // Get top 10 holdings
    const top = portfolio.holdings.slice(0, 10);
    const otherValue = portfolio.holdings.slice(10).reduce((sum, h) => sum + h.value_usd, 0);

    const labels = top.map(h => h.symbol);
    const values = top.map(h => h.value_usd);

    if (otherValue > 0) {
        labels.push('Other');
        values.push(otherValue);
    }

    allocationChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: COLORS,
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        font: { size: 11 },
                        boxWidth: 12
                    }
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const value = ctx.raw;
                            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = ((value / total) * 100).toFixed(1);
                            return `${ctx.label}: ${fmt.usd(value)} (${pct}%)`;
                        }
                    }
                }
            }
        }
    });
}

function updateFlowChart(flowData) {
    const ctx = document.getElementById('flowChart').getContext('2d');

    if (flowChart) {
        flowChart.destroy();
    }

    // Aggregate flows across chains
    const allPoints = [];
    Object.values(flowData.flows).forEach(chainFlow => {
        if (chainFlow.data_points) {
            chainFlow.data_points.forEach(dp => {
                allPoints.push(dp);
            });
        }
    });

    if (allPoints.length === 0) {
        return;
    }

    // Sort by timestamp and take last 90 points
    allPoints.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    const recent = allPoints.slice(-90);

    const labels = recent.map(p => {
        const d = new Date(p.timestamp);
        return d.toLocaleDateString();
    });

    // Dedupe labels (keep every 7th for readability)
    const sparseLabels = labels.map((l, i) => i % 7 === 0 ? l : '');

    flowChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: sparseLabels,
            datasets: [
                {
                    label: 'Cumulative Inflow',
                    data: recent.map(p => p.cumulative_inflow),
                    borderColor: '#16a34a',
                    backgroundColor: 'rgba(22, 163, 74, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0
                },
                {
                    label: 'Cumulative Outflow',
                    data: recent.map(p => p.cumulative_outflow),
                    borderColor: '#dc2626',
                    backgroundColor: 'rgba(220, 38, 38, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                intersect: false,
                mode: 'index'
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { font: { size: 11 } }
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label}: ${fmt.usd(ctx.raw)}`
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { font: { size: 10 } }
                },
                y: {
                    grid: { color: '#e9ecef' },
                    ticks: {
                        font: { size: 10 },
                        callback: (v) => fmt.usd(v)
                    }
                }
            }
        }
    });
}

async function loadComparison() {
    const grid = document.getElementById('comparisonGrid');
    grid.innerHTML = '<p class="no-data">Loading...</p>';

    try {
        const fundsData = await API.get('/funds');
        const fundIds = fundsData.funds.map(f => f.id).join(',');
        const comparison = await API.get(`/compare?funds=${fundIds}`);

        if (!comparison.comparison || comparison.comparison.length === 0) {
            grid.innerHTML = '<p class="no-data">No funds to compare</p>';
            return;
        }

        grid.innerHTML = comparison.comparison.map(fund => {
            const pnlClass = fund.total_pnl >= 0 ? 'positive' : 'negative';
            const holdings = fund.top_holdings.map(h =>
                `<li>${h.symbol}: ${fmt.usd(h.value)} (${h.pct_of_portfolio.toFixed(1)}%)</li>`
            ).join('');

            return `
                <div class="fund-card">
                    <div class="fund-card-header">
                        <span class="fund-card-name">${fund.fund_name}</span>
                        <span class="fund-card-value">${fmt.usd(fund.total_value)}</span>
                    </div>
                    <div class="fund-card-pnl ${pnlClass}">
                        P/L: ${fmt.usd(fund.total_pnl)} (${fmt.percent(fund.total_pnl_pct)})
                    </div>
                    <div class="fund-card-holdings">
                        <strong>Top Holdings (${fund.position_count} total):</strong>
                        <ul>${holdings}</ul>
                    </div>
                </div>
            `;
        }).join('');
    } catch (error) {
        console.error('Failed to load comparison:', error);
        grid.innerHTML = '<p class="no-data">Failed to load comparison</p>';
    }
}

function updateLastUpdated() {
    const el = document.getElementById('lastUpdated');
    el.textContent = 'Updated: ' + new Date().toLocaleTimeString();
}
