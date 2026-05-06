/* ZAN Dashboard — Socket.IO + Chart.js + Canvas Gauges */
'use strict';

const ZAN = (() => {

  // ── Socket.IO connection ──────────────────────────────────────────────────
  const socket = io({ transports: ['websocket', 'polling'] });

  // ── Shared state ──────────────────────────────────────────────────────────
  const linkHistory = {};   // linkKey → [{t, lat, rssi, loss}]
  const MAX_HISTORY = 60;

  let packetCount    = 0;
  let packetCountMin = 0;
  let lastMinuteTs   = Date.now();
  let activeLink     = null;

  // ── Gauge registry ────────────────────────────────────────────────────────
  const gauges = {};   // id → gauge instance

  function initGauges() {
    document.querySelectorAll('canvas[data-type="radial-gauge"]').forEach(el => {
      const id = el.dataset.id;
      if (!id) return;
      const g = new RadialGauge({
        renderTo: el,
        width:  parseInt(el.dataset.width  || 180),
        height: parseInt(el.dataset.height || 180),
      }).draw();
      gauges[id] = g;
    });
    document.querySelectorAll('canvas[data-type="linear-gauge"]').forEach(el => {
      const id = el.dataset.id;
      if (!id) return;
      const g = new LinearGauge({
        renderTo: el,
        width:  parseInt(el.dataset.width  || 120),
        height: parseInt(el.dataset.height || 200),
      }).draw();
      gauges[id] = g;
    });
  }

  function setGauge(id, value) {
    if (gauges[id]) gauges[id].value = value;
  }

  // ── Charts ────────────────────────────────────────────────────────────────
  let latencyChart = null;
  let rssiChart    = null;

  const CHART_OPTS = {
    responsive: true,
    maintainAspectRatio: true,
    animation: { duration: 200 },
    plugins: { legend: { display: false } },
    scales: {
      x: {
        ticks: { color: '#888', font: { size: 10 }, maxTicksLimit: 8 },
        grid:  { color: '#2e2e2e' },
      },
      y: {
        ticks: { color: '#888', font: { size: 10 } },
        grid:  { color: '#2e2e2e' },
      },
    },
  };

  function makeDataset(label, color) {
    return {
      label,
      data: [],
      borderColor: color,
      backgroundColor: color.replace('1)', '0.08)'),
      borderWidth: 2,
      pointRadius: 2,
      tension: 0.3,
      fill: true,
    };
  }

  function initCharts() {
    const latCtx = document.getElementById('chart-latency');
    const rsiCtx = document.getElementById('chart-rssi');
    if (!latCtx || !rsiCtx) return;

    latencyChart = new Chart(latCtx, {
      type: 'line',
      data: { labels: [], datasets: [makeDataset('Latency (ms)', 'rgba(245,197,24,1)')] },
      options: { ...CHART_OPTS, scales: { ...CHART_OPTS.scales, y: { ...CHART_OPTS.scales.y, title: { display: true, text: 'ms', color: '#888' } } } },
    });

    rssiChart = new Chart(rsiCtx, {
      type: 'line',
      data: { labels: [], datasets: [makeDataset('RSSI (dBm)', 'rgba(33,150,243,1)')] },
      options: { ...CHART_OPTS, scales: { ...CHART_OPTS.scales, y: { ...CHART_OPTS.scales.y, title: { display: true, text: 'dBm', color: '#888' } } } },
    });
  }

  function updateCharts(linkKey) {
    if (!latencyChart || !rssiChart) return;
    const hist = linkHistory[linkKey] || [];

    const labels = hist.map(h => {
      const t = h.t ? h.t.split('T')[1] : '';
      return t.substring(0, 8);
    });

    latencyChart.data.labels = labels;
    latencyChart.data.datasets[0].data = hist.map(h => h.lat);
    latencyChart.update('none');

    rssiChart.data.labels = labels;
    rssiChart.data.datasets[0].data = hist.map(h => h.rssi);
    rssiChart.update('none');
  }

  // ── Link selector ─────────────────────────────────────────────────────────
  function ensureLinkOption(linkKey) {
    const sel = document.getElementById('link-select');
    if (!sel) return;
    if (sel.querySelector(`option[value="${linkKey}"]`)) return;
    const opt = document.createElement('option');
    opt.value = linkKey;
    opt.textContent = linkKey;
    sel.appendChild(opt);
  }

  // ── Telemetry update ──────────────────────────────────────────────────────
  function applyTelemetry(d) {
    const node   = d.node_id;
    const target = d.target_node;
    const lk     = `${node}→${target}`;

    // History
    if (!linkHistory[lk]) linkHistory[lk] = [];
    linkHistory[lk].push({ t: d.received_at || new Date().toISOString(), lat: d.latency_ms, rssi: d.rssi_dbm, loss: d.packet_loss_pct });
    if (linkHistory[lk].length > MAX_HISTORY) linkHistory[lk].shift();

    ensureLinkOption(lk);
    if (!activeLink) {
      activeLink = lk;
      const sel = document.getElementById('link-select');
      if (sel) sel.value = lk;
    }
    if (activeLink === lk) updateCharts(lk);

    // Node card values
    const ids = ['lat', 'rssi', 'loss', 'uptime'];
    const vals = [
      `${d.latency_ms.toFixed(1)} ms`,
      `${d.rssi_dbm} dBm`,
      `${(d.packet_loss_pct * 100).toFixed(1)}%`,
      `${d.uptime_s}s`,
    ];
    ids.forEach((id, i) => {
      const el = document.getElementById(`${node}-${id}`);
      if (el) el.textContent = vals[i];
    });

    // Node badge
    const badge = document.getElementById(`badge-${node}`);
    if (badge) {
      badge.textContent = 'Live';
      badge.className = 'zan-node-badge zan-badge-online';
    }

    // Node card border
    const card = document.getElementById(`node-card-${node}`);
    if (card) {
      card.classList.remove('zan-node-alert');
      card.classList.add('zan-node-live');
    }

    // Aggregate gauges from all recent readings
    updateAggregateGauges();

    // Counters
    packetCount++;
    document.getElementById('last-update') && (document.getElementById('last-update').textContent = new Date().toLocaleTimeString());
    const statPkt = document.getElementById('stat-packets');
    if (statPkt) {
      const now = Date.now();
      if (now - lastMinuteTs >= 60000) {
        statPkt.textContent = packetCountMin;
        packetCountMin = 0;
        lastMinuteTs = now;
      }
      packetCountMin++;
    }

    updateStatCounts();
  }

  function updateAggregateGauges() {
    const allLinks = Object.values(linkHistory);
    if (!allLinks.length) return;
    const recent = allLinks.map(arr => arr[arr.length - 1]).filter(Boolean);
    if (!recent.length) return;

    const avgLat  = recent.reduce((s, r) => s + r.lat,  0) / recent.length;
    const avgRssi = recent.reduce((s, r) => s + r.rssi, 0) / recent.length;
    const avgLoss = recent.reduce((s, r) => s + r.loss, 0) / recent.length;

    setGauge('gauge-latency', Math.round(avgLat));
    setGauge('gauge-rssi',    Math.round(avgRssi));
    setGauge('gauge-loss',    Math.round(avgLoss * 100));
  }

  function updateStatCounts() {
    const nodes = new Set(Object.keys(linkHistory).map(k => k.split('→')[0]));
    const nEl = document.getElementById('stat-nodes');
    const lEl = document.getElementById('stat-links');
    if (nEl) nEl.textContent = nodes.size;
    if (lEl) lEl.textContent = Object.keys(linkHistory).length;
  }

  // ── SDN Topology ──────────────────────────────────────────────────────────
  function updateSdnPanel(data) {
    const connected = new Set(data.connected_switches || []);
    const degraded  = data.degraded_links || [];
    const macTable  = data.mac_table || {};

    const degradedSw = new Set();
    degraded.forEach(pair => { degradedSw.add(pair[0]); degradedSw.add(pair[1]); });

    for (let i = 1; i <= 5; i++) {
      const el      = document.getElementById(`sw-${i}`);
      const hostsEl = document.getElementById(`sw-${i}-hosts`);
      if (!el) continue;

      if (!connected.has(i)) {
        el.className = 'zan-switch-badge zan-sw-offline';
        if (hostsEl) hostsEl.textContent = '';
      } else if (degradedSw.has(i)) {
        el.className = 'zan-switch-badge zan-sw-degraded';
      } else {
        el.className = 'zan-switch-badge zan-sw-online';
      }

      const macs = macTable[String(i)] || [];
      if (hostsEl) hostsEl.textContent = macs.length ? ` (${macs.length}h)` : '';
    }

    const deg = document.getElementById('sdn-degraded');
    if (deg) {
      if (!degraded.length) {
        deg.innerHTML = '<span class="zan-topo-none"><i class="bi bi-shield-check me-1"></i>None</span>';
      } else {
        deg.innerHTML = degraded.map(p =>
          `<span class="zan-degraded-link"><i class="bi bi-exclamation-triangle-fill me-1"></i>s${p[0]} ↔ s${p[1]}</span>`
        ).join('');
      }
    }

    const ts = document.getElementById('sdn-last-poll');
    if (ts) ts.textContent = new Date().toLocaleTimeString();
  }

  function pollSdnStatus() {
    fetch('/api/sdn-status')
      .then(r => r.json())
      .then(data => updateSdnPanel(data))
      .catch(() => {
        const ts = document.getElementById('sdn-last-poll');
        if (ts) ts.textContent = 'unreachable';
      });
  }

  const btnClear = document.getElementById('btn-clear-degraded');
  if (btnClear) {
    btnClear.addEventListener('click', () => {
      btnClear.disabled = true;
      fetch('/api/clear-degraded', { method: 'POST' })
        .then(r => r.json())
        .then(() => pollSdnStatus())
        .catch(() => {})
        .finally(() => { btnClear.disabled = false; });
    });
  }

  // ── Insight (AI alert) ────────────────────────────────────────────────────
  function flashAffectedSwitches(degradedLinks) {
    const affected = new Set();
    degradedLinks.forEach(pair => { affected.add(pair[0]); affected.add(pair[1]); });
    affected.forEach(dpid => {
      const el = document.getElementById(`sw-${dpid}`);
      if (!el) return;
      el.classList.add('zan-sw-rerouting');
      setTimeout(() => el.classList.remove('zan-sw-rerouting'), 2000);
    });
  }

  function applyInsight(ins) {
    const container = document.getElementById('alerts-container');
    if (!container) return;

    // Remove placeholder
    const ph = container.querySelector('.zan-no-alerts');
    if (ph) ph.remove();

    const typeClass = (ins.type || 'unknown').toLowerCase().replace(/_/g, '-');
    const hasNodes  = (ins.nodes || []).length === 2;
    const rerouteBadge = hasNodes
      ? `<span class="zan-reroute-badge"><i class="bi bi-arrow-repeat me-1"></i>Rerouting…</span>`
      : '';

    const row = document.createElement('div');
    row.className = 'zan-alert-row';
    row.innerHTML = `
      <span class="zan-alert-type zan-type-${typeClass}">${ins.type || '?'}</span>
      <span class="zan-alert-nodes"><i class="bi bi-link-45deg"></i> ${(ins.nodes || []).join(' ↔ ')}</span>
      <span class="zan-alert-conf">conf ${(ins.confidence || 0).toFixed(2)}</span>
      ${rerouteBadge}
      <span class="zan-alert-time">${new Date().toLocaleTimeString()}</span>
    `;
    container.prepend(row);

    // Upgrade badge after 1.5 s — gives controller time to log all rapid-fire insights
    if (hasNodes) {
      const badge = row.querySelector('.zan-reroute-badge');
      const nodes = ins.nodes || [];
      setTimeout(() => {
        fetch('/api/sdn-status')
          .then(r => r.json())
          .then(data => {
            const recent = data.recent_insights || [];
            const match  = recent.find(r =>
              Array.isArray(r.nodes) && r.nodes.length === 2 &&
              r.nodes.some(n => n === nodes[0]) &&
              r.nodes.some(n => n === nodes[1])
            );
            const confirmed = !!(match && match.rerouted === true);
            if (badge) {
              badge.innerHTML = confirmed
                ? '<i class="bi bi-check-circle-fill me-1"></i>Rerouted'
                : '<i class="bi bi-exclamation-circle me-1"></i>Reroute attempted';
              badge.className = confirmed
                ? 'zan-reroute-badge zan-reroute-ok'
                : 'zan-reroute-badge zan-reroute-warn';
            }
          })
          .catch(() => {
            if (badge) {
              badge.textContent = 'Status unknown';
              badge.className = 'zan-reroute-badge zan-reroute-warn';
            }
          });
      }, 1500);
    }

    // Cap at 20
    const rows = container.querySelectorAll('.zan-alert-row');
    if (rows.length > 20) rows[rows.length - 1].remove();

    // Update stat counter
    const el = document.getElementById('stat-alerts');
    if (el) el.textContent = container.querySelectorAll('.zan-alert-row').length;

    // Health banner
    setHealthBanner(false);

    // Node card alert highlight
    (ins.nodes || []).forEach(node => {
      const card = document.getElementById(`node-card-${node}`);
      if (card) { card.classList.add('zan-node-alert'); card.classList.remove('zan-node-live'); }
    });
  }

  function setHealthBanner(healthy) {
    const banner = document.getElementById('health-banner');
    const icon   = document.getElementById('health-icon');
    const text   = document.getElementById('health-text');
    if (!banner) return;
    if (healthy) {
      banner.className = 'zan-health-banner zan-healthy';
      icon.innerHTML   = '<i class="bi bi-shield-check"></i>';
      text.textContent = 'Network Healthy';
    } else {
      banner.className = 'zan-health-banner zan-degraded';
      icon.innerHTML   = '<i class="bi bi-exclamation-triangle-fill"></i>';
      text.textContent = 'Anomaly Detected';
    }
  }

  // ── MQTT badge ────────────────────────────────────────────────────────────
  function setMqttBadge(connected) {
    const b = document.getElementById('mqtt-badge');
    if (!b) return;
    if (connected) {
      b.className = 'zan-badge-online';
      b.innerHTML = '<i class="bi bi-wifi me-1"></i>Connected';
    } else {
      b.className = 'zan-badge-offline';
      b.innerHTML = '<i class="bi bi-wifi-off me-1"></i>Offline';
    }
  }

  // ── Socket events (always active) ────────────────────────────────────────
  socket.on('connect',      () => setMqttBadge(true));
  socket.on('disconnect',   () => setMqttBadge(false));
  socket.on('mqtt_status',  d  => setMqttBadge(d.connected));
  socket.on('telemetry',    d  => applyTelemetry(d));
  socket.on('insight',      d  => applyInsight(d));
  socket.on('sdn_update',   d  => { updateSdnPanel(d); flashAffectedSwitches(d.degraded_links || []); });

  // ── Log page ──────────────────────────────────────────────────────────────
  let logCount   = 0;
  let logFilter  = '';
  let autoScroll = true;

  function addLogRow(d) {
    if (logFilter && d.node_id !== logFilter) return;

    const placeholder = document.getElementById('log-placeholder');
    if (placeholder) placeholder.remove();

    const tbody = document.getElementById('log-body');
    if (!tbody) return;

    logCount++;
    const tr = document.createElement('tr');
    const lossColor = d.packet_loss_pct > 0.2 ? '#ef9a9a' : d.packet_loss_pct > 0 ? '#F5C518' : '#81c784';
    const latColor  = d.latency_ms > 80 ? '#ef9a9a' : d.latency_ms > 30 ? '#F5C518' : '#81c784';
    tr.innerHTML = `
      <td style="color:#888">${d.received_at || '—'}</td>
      <td style="color:#F5C518;font-weight:600">${d.node_id || '—'}</td>
      <td>${d.target_node || '—'}</td>
      <td style="color:${latColor}">${d.latency_ms != null ? d.latency_ms.toFixed(1)+' ms' : '—'}</td>
      <td>${d.rssi_dbm != null ? d.rssi_dbm+' dBm' : '—'}</td>
      <td style="color:${lossColor}">${d.packet_loss_pct != null ? (d.packet_loss_pct*100).toFixed(1)+'%' : '—'}</td>
      <td style="color:#888">${d.uptime_s != null ? d.uptime_s+'s' : '—'}</td>
      <td class="zan-log-raw">${JSON.stringify(d)}</td>
    `;
    tbody.appendChild(tr);

    // Cap rows
    while (tbody.rows.length > 500) tbody.deleteRow(0);

    const countEl = document.getElementById('log-count');
    if (countEl) countEl.textContent = logCount;

    const tsEl = document.getElementById('log-last-ts');
    if (tsEl) tsEl.textContent = `Last: ${d.received_at || new Date().toLocaleTimeString()}`;

    if (autoScroll) {
      const c = document.getElementById('log-container');
      if (c) c.scrollTop = c.scrollHeight;
    }
  }

  // ── Public API ────────────────────────────────────────────────────────────
  return {
    initDashboard() {
      initGauges();
      initCharts();

      // Poll SDN topology every 5 s
      pollSdnStatus();
      setInterval(pollSdnStatus, 5000);

      // Pre-populate links and load chart history from server state
      fetch('/api/state')
        .then(r => r.json())
        .then(state => {
          const links = Object.keys(state.links || {});
          links.forEach(lk => ensureLinkOption(lk));
          if (links.length && !activeLink) {
            activeLink = links[0];
            const sel = document.getElementById('link-select');
            if (sel) sel.value = activeLink;
            fetch('/api/history/' + encodeURIComponent(activeLink))
              .then(r => r.json())
              .then(hist => { linkHistory[activeLink] = hist; updateCharts(activeLink); });
          }
        })
        .catch(() => {});

      const sel = document.getElementById('link-select');
      if (sel) {
        sel.addEventListener('change', () => {
          activeLink = sel.value;
          if (!activeLink) return;
          if (linkHistory[activeLink] && linkHistory[activeLink].length) {
            updateCharts(activeLink);
          } else {
            fetch('/api/history/' + encodeURIComponent(activeLink))
              .then(r => r.json())
              .then(hist => { linkHistory[activeLink] = hist; updateCharts(activeLink); })
              .catch(() => {});
          }
        });
      }
    },

    initLogs() {
      // Wire filter
      const filterEl = document.getElementById('log-filter-node');
      if (filterEl) {
        filterEl.addEventListener('change', () => { logFilter = filterEl.value; });
      }

      // Wire autoscroll toggle
      const asEl = document.getElementById('log-autoscroll');
      if (asEl) {
        asEl.addEventListener('change', () => { autoScroll = asEl.checked; });
      }

      // Listen for live messages
      socket.on('telemetry', d => addLogRow(d));
    },

    clearLogDisplay() {
      const tbody = document.getElementById('log-body');
      if (tbody) {
        tbody.innerHTML = '';
        logCount = 0;
        const el = document.getElementById('log-count');
        if (el) el.textContent = '0';
      }
    },
  };

})();
