/**
 * Smart Money Dashboard
 *
 * WSJ-inspired dashboard for tracking smart money activity.
 */

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

async function loadData() {
    const chains = state.selectedChains.join(',');

    if (state.currentView === 'purchases') {
        await loadPurchases(chains);
    } else if (state.currentView === 'trades') {
        await loadTrades(chains);
    }

    updateLastUpdated();
}

async function loadPurchases(chains) {
    const body = $('#purchases-body');
    body.innerHTML = '<tr><td colspan="6" class="loading">Loading data...</td></tr>';

    try {
        const data = await api.get(`/api/v1/purchases?chains=${chains}&limit=50`);

        // Update stats
        $('#total-tokens').textContent = fmt.number(data.total_tokens);
        $('#accumulating-count').textContent = fmt.number(data.accumulating_count);
        $('#distributing-count').textContent = fmt.number(data.distributing_count);

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
                </td>
                <td class="numeric">${fmt.usd(token.total_value_usd)}</td>
                <td>
                    <span class="signal signal-${token.signal}">${token.signal}</span>
                    <span class="signal-strength">${token.signal_strength}</span>
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
        $('#buy-volume').textContent = fmt.usd(data.buy_volume_usd);
        $('#sell-volume').textContent = fmt.usd(data.sell_volume_usd);

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

async function loadDrilldown(chain, tokenAddress) {
    state.currentToken = { chain, address: tokenAddress };
    showView('drilldown');

    // Show loading state
    $('#drilldown-title').textContent = 'Loading...';
    $('#drilldown-narrative').textContent = 'Loading analysis...';
    $('#flow-intelligence').innerHTML = '<div class="loading">Loading...</div>';
    $('#holders-body').innerHTML = '<tr><td colspan="3" class="loading">Loading...</td></tr>';
    $('#buyers-list').innerHTML = '<div class="loading">Loading...</div>';
    $('#sellers-list').innerHTML = '<div class="loading">Loading...</div>';

    try {
        const data = await api.get(`/api/v1/token/${chain}/${tokenAddress}`);

        // Update title
        $('#drilldown-title').textContent = `${data.token_symbol} Analysis`;

        // Update stats
        $('#total-holders').textContent = fmt.number(data.holder_breakdown?.total || 0);
        $('#sm-holders').textContent = fmt.number(data.holder_breakdown?.smart_money || 0);
        $('#whale-holders').textContent = fmt.number(data.holder_breakdown?.whale || 0);
        $('#exchange-holders').textContent = fmt.number(data.holder_breakdown?.exchange || 0);

        // Update narrative
        $('#drilldown-narrative').innerHTML = data.narrative?.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') || 'No analysis available.';

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

        // Render buyers/sellers
        renderBuyersSellers(data.recent_buyers, data.recent_sellers);

    } catch (error) {
        console.error('Error loading drilldown:', error);
        $('#drilldown-narrative').textContent = `Error loading data: ${error.message}`;
    }
}

function renderBuyersSellers(buyers, sellers) {
    if (buyers && buyers.length > 0) {
        $('#buyers-list').innerHTML = buyers.slice(0, 5).map(b => `
            <div class="flow-segment">
                <span class="flow-label">${b.trader_label || fmt.address(b.trader_address)}</span>
                <span class="flow-value positive">${fmt.usd(b.volume_usd)}</span>
            </div>
        `).join('');
    } else {
        $('#buyers-list').innerHTML = '<p>No recent buyers</p>';
    }

    if (sellers && sellers.length > 0) {
        $('#sellers-list').innerHTML = sellers.slice(0, 5).map(s => `
            <div class="flow-segment">
                <span class="flow-label">${s.trader_label || fmt.address(s.trader_address)}</span>
                <span class="flow-value negative">${fmt.usd(s.volume_usd)}</span>
            </div>
        `).join('');
    } else {
        $('#sellers-list').innerHTML = '<p>No recent sellers</p>';
    }
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
    loadData();
}, 5 * 60 * 1000);
