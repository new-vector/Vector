// ── Brinks Box Dashboard — Client-side logic ────────────────
// Connects to the FastAPI WebSocket and updates the DOM in real-time.

(function () {
  "use strict";

  // ── DOM refs ────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);

  const els = {
    equity:       $("equity"),
    posPnl:       $("pos-pnl"),
    realPnl:      $("real-pnl"),
    tradesToday:  $("trades-today"),
    winRate:      $("win-rate"),
    boxHigh:      $("box-high"),
    boxMid:       $("box-mid"),
    boxLow:       $("box-low"),
    boxStatus:    $("box-status"),
    asianHigh:    $("asian-high"),
    asianLow:     $("asian-low"),
    brinksActive: $("brinks-active"),
    tradeWindow:  $("trade-window"),
    vectorList:   $("vector-list"),
    signalLog:    $("signal-log"),
    tradeTbody:   $("trade-tbody"),
    wsStatus:     $("ws-status"),
    clock:        $("clock"),
  };

  // ── Clock ──────────────────────────────────────────────────
  function updateClock() {
    const now = new Date();
    els.clock.textContent = now.toLocaleTimeString("en-US", {
      hour12: false,
      timeZone: "America/New_York",
    }) + " ET";
  }
  setInterval(updateClock, 1000);
  updateClock();

  // ── Formatting ─────────────────────────────────────────────
  function fmtMoney(n) {
    if (n == null || isNaN(n)) return "—";
    const sign = n >= 0 ? "" : "-";
    return sign + "$" + Math.abs(n).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function fmtPrice(n) {
    if (n == null || isNaN(n) || n === 0) return "—";
    return n.toFixed(2);
  }

  function pnlClass(n) {
    if (n > 0) return "positive";
    if (n < 0) return "negative";
    return "";
  }

  // ── WebSocket ──────────────────────────────────────────────
  let ws = null;
  let reconnectTimer = null;
  const MAX_SIGNALS = 50;
  const signalHistory = [];

  function connect() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${location.host}/ws`);

    ws.onopen = () => {
      els.wsStatus.innerHTML =
        '<span class="dot dot-connected"></span><span>Connected</span>';
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    ws.onclose = () => {
      els.wsStatus.innerHTML =
        '<span class="dot dot-disconnected"></span><span>Disconnected</span>';
      reconnectTimer = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        render(data);
      } catch (e) {
        console.error("Parse error:", e);
      }
    };
  }

  // ── Render ─────────────────────────────────────────────────
  function render(data) {
    // Metrics
    els.equity.textContent = fmtMoney(data.equity);
    els.equity.className = "metric-value " + pnlClass(data.equity - 10000);

    els.posPnl.textContent = fmtMoney(data.position_pnl);
    els.posPnl.className = "metric-value " + pnlClass(data.position_pnl);

    if (data.realised_pnl != null) {
      els.realPnl.textContent = fmtMoney(data.realised_pnl);
      els.realPnl.className = "metric-value " + pnlClass(data.realised_pnl);
    }

    if (data.trades_today != null) {
      els.tradesToday.textContent = data.trades_today;
    }

    if (data.win_rate != null) {
      els.winRate.textContent = (data.win_rate * 100).toFixed(0) + "%";
    }

    // Box levels
    els.boxHigh.textContent = fmtPrice(data.box_high);
    els.boxMid.textContent = fmtPrice(data.box_mid);
    els.boxLow.textContent = fmtPrice(data.box_low);

    if (data.box_ready) {
      els.boxStatus.textContent = "Box ready — trading active";
      els.boxStatus.style.color = "var(--green)";
    } else if (data.brinks_active) {
      els.boxStatus.textContent = "Brinks session active…";
      els.boxStatus.style.color = "var(--blue)";
    } else {
      els.boxStatus.textContent = "Waiting for session…";
      els.boxStatus.style.color = "var(--text-muted)";
    }

    // Session levels
    els.asianHigh.textContent = fmtPrice(data.asian_high);
    els.asianLow.textContent = fmtPrice(data.asian_low);
    els.brinksActive.textContent = data.brinks_active ? "Yes" : "No";
    els.brinksActive.style.color = data.brinks_active ? "var(--blue)" : "var(--text-muted)";
    els.tradeWindow.textContent = data.trade_window_active ? "Yes" : "No";
    els.tradeWindow.style.color = data.trade_window_active ? "var(--cyan)" : "var(--text-muted)";

    // Vectors
    if (data.vectors && data.vectors.length > 0) {
      els.vectorList.innerHTML = data.vectors
        .map((v) => {
          const cls = v.direction === "bull" ? "bull" : "bear";
          const arrow = v.direction === "bull" ? "▲" : "▼";
          return `
            <div class="vector-chip ${cls}">
              <span class="vector-dir">${arrow}</span>
              <span>${fmtPrice(v.low)} — ${fmtPrice(v.high)}</span>
              <span class="vector-tf">${v.timeframe}</span>
            </div>`;
        })
        .join("");
    }

    // Signal
    if (data.signal) {
      const s = data.signal;
      signalHistory.unshift(s);
      if (signalHistory.length > MAX_SIGNALS) signalHistory.pop();
      renderSignals();
    }

    // Trade result
    if (data.trade_result) {
      addTradeRow(data.trade_result);
    }
  }

  function renderSignals() {
    if (signalHistory.length === 0) return;
    els.signalLog.innerHTML = signalHistory
      .map((s) => {
        const side = s.signal_type?.includes("LONG") ? "long" : "short";
        return `
          <div class="signal-entry ${side}">
            <span class="signal-time">${s.timestamp || "—"}</span>
            <span class="signal-type">${s.signal_type || ""}</span>
            <span class="signal-reason">${s.reason || ""}</span>
          </div>`;
      })
      .join("");
  }

  function addTradeRow(t) {
    const cls = t.net_pnl >= 0 ? "pnl-positive" : "pnl-negative";
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${t.exit_time || "—"}</td>
      <td>${t.signal_type || "—"}</td>
      <td>${t.side || "—"}</td>
      <td>${fmtPrice(t.entry_price)}</td>
      <td>${fmtPrice(t.exit_price)}</td>
      <td class="${cls}">${fmtMoney(t.net_pnl)}</td>
      <td>${t.exit_reason || "—"}</td>`;
    els.tradeTbody.prepend(row);
  }

  // ── Init ───────────────────────────────────────────────────
  connect();
})();
