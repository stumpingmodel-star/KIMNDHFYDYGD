const chartEl = document.getElementById('chart');
const chart = LightweightCharts.createChart(chartEl, {
    layout: {
        background: { color: '#111827' },
        textColor: '#e5e7eb',
    },
    grid: {
        vertLines: { color: '#1f2937' },
        horzLines: { color: '#1f2937' },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: '#374151' },
    timeScale: { borderColor: '#374151', timeVisible: true },
});

const candleSeries = chart.addCandlestickSeries({
    upColor: '#22c55e',
    downColor: '#ef4444',
    borderUpColor: '#22c55e',
    borderDownColor: '#ef4444',
    wickUpColor: '#22c55e',
    wickDownColor: '#ef4444',
});

function resizeChart() {
    chart.applyOptions({ width: chartEl.clientWidth, height: chartEl.clientHeight });
}
window.addEventListener('resize', resizeChart);
setTimeout(resizeChart, 0);

let chartInitialized = false;
let lastCandleTime = 0;

function updateChart(klines) {
    if (!klines || klines.length === 0) return;
    if (!chartInitialized) {
        candleSeries.setData(klines);
        chartInitialized = true;
    } else {
        klines.forEach(k => {
            if (k.time >= lastCandleTime) {
                candleSeries.update(k);
            }
        });
    }
    lastCandleTime = klines[klines.length - 1].time;
}

const fmtPrice = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
});

const fmtQty = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
});

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function setBadge(id, value, type) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value;
    el.className = 'badge ' + (type || 'neutral');
}

function renderOrderbook(bids, asks, imbalance) {
    const tbody = document.getElementById('orderbook-body');
    tbody.innerHTML = '';
    const rows = Math.max(bids.length, asks.length);
    for (let i = 0; i < rows; i++) {
        const bid = bids[i] || [];
        const ask = asks[i] || [];
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${bid[1] ? fmtQty.format(bid[1]) : ''}</td>
            <td>${bid[0] ? fmtPrice.format(bid[0]) : ''}</td>
            <td>${ask[0] ? fmtPrice.format(ask[0]) : ''}</td>
            <td>${ask[1] ? fmtQty.format(ask[1]) : ''}</td>
        `;
        tbody.appendChild(tr);
    }
    setText('ob-imbalance', (imbalance > 0 ? '+' : '') + imbalance.toFixed(1) + '%');
}

function renderTape(trades) {
    const tbody = document.getElementById('tape-body');
    tbody.innerHTML = '';
    trades.forEach(t => {
        const tr = document.createElement('tr');
        const sideClass = t.side === 'BUY' ? 'side-buy' : 'side-sell';
        tr.innerHTML = `
            <td>${t.time}</td>
            <td class="${sideClass}">${t.side}</td>
            <td>${fmtPrice.format(t.price)}</td>
            <td>${fmtQty.format(t.qty)}</td>
        `;
        tbody.appendChild(tr);
    });
}

function renderSignal(signal) {
    if (!signal) return;
    const sigType = signal.signal === 'LONG' ? 'long' : signal.signal === 'SHORT' ? 'short' : 'neutral';
    setBadge('scalp-signal', signal.signal, sigType);
    setText('scalp-entry', signal.entry ? fmtPrice.format(signal.entry) : '--');
    setText('scalp-ideal', signal.ideal_entry ? fmtPrice.format(signal.ideal_entry) : '--');
    setText('scalp-sl', signal.stop_loss ? fmtPrice.format(signal.stop_loss) : '--');
    setText('scalp-target', signal.target ? fmtPrice.format(signal.target) : '--');
    setText('scalp-rr', signal.rr_ratio ? signal.rr_ratio.toFixed(2) : '--');
    setText('scalp-reason', signal.reason || '--');
}

function updateMetrics(data) {
    setText('utc', data.utc);
    setText('latency', `Latency: ${data.latency_ms.toFixed(1)} ms`);
    setText('last-price', fmtPrice.format(data.last_price));
    setText('micro-price', fmtPrice.format(data.micro_price));
    setText('rsi', data.rsi.toFixed(1));
    setText('atr', fmtPrice.format(data.atr));
    setText('vwap', fmtPrice.format(data.vwap));
    setText('emas', `${fmtPrice.format(data.ema_9)} / ${fmtPrice.format(data.ema_21)}`);
    setText('cvd-5s', (data.recent_cvd_5s > 0 ? '+' : '') + data.recent_cvd_5s.toFixed(3) + ' XAU');
    setText('cvd-total', (data.cvd > 0 ? '+' : '') + data.cvd.toFixed(2) + ' XAU');
    setText('funding', (data.funding_rate * 100).toFixed(4) + '%');
    setText('oi', fmtQty.format(data.open_interest) + ' XAU');

    const dirType = data.direction === 'LONG' ? 'long' : data.direction === 'SHORT' ? 'short' : 'neutral';
    setBadge('direction', data.direction, dirType);

    const stateType = (data.liq_state || 'IDLE').toLowerCase();
    setBadge('liq-state', data.liq_state, stateType);
    setText('liq-side', data.liq_side || '--');
    setText('liq-long', fmtPrice.format(data.liq_long_10s));
    setText('liq-short', fmtPrice.format(data.liq_short_10s));
    setText('liq-velocity', fmtPrice.format(data.liq_velocity) + '/s');
    setText('liq-peak', fmtPrice.format(data.liq_peak_velocity) + '/s');
    setText('liq-wick', fmtPrice.format(data.liq_wick_extreme));

    renderSignal(data.scalp_signal);
    renderOrderbook(data.bids, data.asks, data.ob_imbalance);
    renderTape(data.tape);
    updateChart(data.klines);
}

const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);

const statusEl = document.getElementById('conn-status');

ws.onopen = () => {
    statusEl.textContent = 'Connected';
    statusEl.className = 'status connected';
};

ws.onclose = () => {
    statusEl.textContent = 'Disconnected';
    statusEl.className = 'status disconnected';
};

ws.onerror = () => {
    statusEl.textContent = 'Error';
    statusEl.className = 'status disconnected';
};

ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'snapshot' || msg.type === 'update') {
        updateMetrics(msg);
    } else if (msg.type === 'trade_result') {
        const resultEl = document.getElementById('trade-result');
        resultEl.textContent = JSON.stringify(msg.data, null, 2);
    } else if (msg.type === 'error') {
        const resultEl = document.getElementById('trade-result');
        resultEl.textContent = 'Error: ' + msg.message;
    }
};

function sendTrade(side) {
    if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'trade', side: side }));
    }
}

document.getElementById('btn-buy').addEventListener('click', () => sendTrade('BUY'));
document.getElementById('btn-sell').addEventListener('click', () => sendTrade('SELL'));
