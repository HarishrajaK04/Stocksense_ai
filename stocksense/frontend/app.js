/* StockSense AI dashboard */
"use strict";

const DEFAULTS = { symbol: "RELIANCE", range: "1Y", refresh: 30, news: "", apiBase: "" };
const RANGES = { "1D": ["1d", "5m"], "5D": ["5d", "15m"], "1M": ["1mo", "1d"], "6M": ["6mo", "1d"], "1Y": ["1y", "1d"], "5Y": ["5y", "1wk"], "MAX": ["max", "1mo"] };
const COLORS = ["#5b5bf0", "#0fa968", "#f5a623", "#e5484d", "#ec4899", "#06b6d4"];

let S = loadSettings();
let watch = loadWatch();
let current = "overview";
let exSymbol = null, exRange = S.range;
let chatHistory = [];
const charts = {};

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n, d = 2) => n == null || isNaN(n) ? "-" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (n, d = 2) => n == null || isNaN(n) ? "-" : (n > 0 ? "+" : "") + num(n, d) + "%";
const cls = n => n > 0 ? "up" : n < 0 ? "down" : "";
const frac = (n, d = 1) => n == null ? "-" : num(n * 100, d) + "%";

function loadSettings() { try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem("ss_settings") || "{}") }; } catch { return { ...DEFAULTS }; } }
function loadWatch() { try { const w = JSON.parse(localStorage.getItem("ss_watch")); return Array.isArray(w) ? w : ["RELIANCE", "TCS", "HDFCBANK"]; } catch { return ["RELIANCE", "TCS", "HDFCBANK"]; } }
function saveWatch() { try { localStorage.setItem("ss_watch", JSON.stringify(watch)); } catch { } }

const base = () => (S.apiBase || window.STOCKSENSE_API || "").replace(/\/$/, "");
async function api(path, opts) {
  let r;
  try { r = await fetch(base() + path, opts); } catch (e) { throw new Error("Cannot reach the API. Is the backend running?"); }
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch { } throw new Error(typeof m === "string" ? m : JSON.stringify(m)); }
  return r.json();
}
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function showError(msg) { const b = $("#errorBanner"); if (!msg) { b.classList.add("hidden"); return; } b.textContent = msg; b.classList.remove("hidden"); }
async function guarded(btn, fn) {
  if (btn) btn.disabled = true; showError("");
  try { await fn(); } catch (e) { showError(e.message); } finally { if (btn) btn.disabled = false; }
}

Chart.defaults.color = "#6b7694";
Chart.defaults.borderColor = "#e4e9f5";
Chart.defaults.font.family = "Inter, sans-serif";
function draw(id, config) {
  if (charts[id]) charts[id].destroy();
  config.options = Object.assign({ responsive: true, maintainAspectRatio: false, animation: false }, config.options || {});
  charts[id] = new Chart($("#" + id), config);
  return charts[id];
}
const lineOpts = (extra = {}) => ({ interaction: { mode: "index", intersect: false }, plugins: { legend: { display: false } }, scales: { x: { ticks: { maxTicksLimit: 8, maxRotation: 0 }, grid: { display: false } }, y: { grid: { color: "#edf0f9" } } }, ...extra });

/* ------------------------------------------------------------ navigation */
function show(view) {
  current = view;
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + view));
  $$("#nav button").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  $("#sidebar").classList.remove("open");
  if (location.hash !== "#" + view) history.replaceState(null, "", "#" + view);
  (loaders[view] || (() => { }))();
}
$("#nav").addEventListener("click", e => { const b = e.target.closest("button"); if (b) show(b.dataset.view); });
$("#menuBtn").addEventListener("click", () => $("#sidebar").classList.toggle("open"));

function openSymbol(sym) { exSymbol = sym; $("#exSymbol").value = sym; show("explorer"); }

function setMeta(m, source) {
  if (m) { const p = $("#marketPill"); p.textContent = (m.open ? "Market open" : "Market closed") + " | " + m.text; p.classList.toggle("open", m.open); }
  if (source) {
    const b = $("#sourceBadge"); b.textContent = source === "demo" ? "demo data" : "source: " + source; b.classList.toggle("live", source !== "demo");
    $("#demoBanner").classList.toggle("hidden", source !== "demo");
  }
  $("#updated").textContent = "updated " + new Date().toLocaleTimeString("en-IN");
}

/* ------------------------------------------------------------ overview */
function qCard(q, big) {
  if (q.error) return `<div class="card"><div class="k">${esc(q.symbol)}</div><div class="s down">${esc(q.error)}</div></div>`;
  return `<div class="card"><div class="k">${esc(q.name)}</div><div class="v">${num(q.price)}</div><div class="s ${cls(q.change)}">${num(q.change)} (${pct(q.change_pct)})</div></div>`;
}
async function loadOverview() {
  await guarded(null, async () => {
    const d = await api("/api/overview");
    setMeta(d.market, d.source);
    $("#indexCards").innerHTML = d.indices.map(q => qCard(q)).join("");
    const s = d.summary;
    $("#summaryText").textContent = s.text || "Index data unavailable right now.";
    const tot = (s.advancers + s.decliners + s.unchanged) || 1;
    $("#breadth").innerHTML = `<div class="bar"><span style="width:${s.advancers / tot * 100}%;background:var(--up)"></span><span style="width:${s.unchanged / tot * 100}%;background:#cbd2e6"></span><span style="width:${s.decliners / tot * 100}%;background:var(--down)"></span></div>
      <p class="muted" style="margin:6px 0 0">${s.advancers} advancing | ${s.decliners} declining${s.top_gainer ? ` | top gainer <b class="up">${esc(s.top_gainer.symbol)} ${pct(s.top_gainer.change_pct)}</b> | top loser <b class="down">${esc(s.top_loser.symbol)} ${pct(s.top_loser.change_pct)}</b>` : ""}</p>`;
    $("#moversTable tbody").innerHTML = d.movers.filter(m => !m.error).sort((a, b) => b.change_pct - a.change_pct).map(m =>
      `<tr class="click" data-sym="${esc(m.symbol)}"><td><b>${esc(m.symbol)}</b></td><td class="muted">${esc(m.name)}</td><td class="r">${num(m.price)}</td><td class="r ${cls(m.change)}">${num(m.change)}</td><td class="r ${cls(m.change)}">${pct(m.change_pct)}</td><td><button class="star ${watch.includes(m.symbol) ? "on" : ""}" data-star="${esc(m.symbol)}" title="Watchlist">&#9733;</button></td></tr>`).join("");
  });
}
$("#moversTable").addEventListener("click", e => {
  const st = e.target.closest("[data-star]");
  if (st) { toggleWatch(st.dataset.star); st.classList.toggle("on"); return; }
  const tr = e.target.closest("tr[data-sym]"); if (tr) openSymbol(tr.dataset.sym);
});
function toggleWatch(sym) { sym = sym.toUpperCase(); watch = watch.includes(sym) ? watch.filter(s => s !== sym) : [...watch, sym]; saveWatch(); }

/* ------------------------------------------------------------ explorer */
function buildRangeButtons() {
  $("#exRange").innerHTML = Object.keys(RANGES).map(r => `<button data-r="${r}" class="${r === exRange ? "on" : ""}">${r}</button>`).join("");
  $("#setRange").innerHTML = Object.keys(RANGES).map(r => `<option ${r === S.range ? "selected" : ""}>${r}</option>`).join("");
}
$("#exRange").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; exRange = b.dataset.r; buildRangeButtons(); loadChart(); });
["exSma20", "exSma50", "exVol"].forEach(id => $("#" + id).addEventListener("change", () => lastHist && renderExplorerChart(lastHist)));

let lastHist = null;
async function loadExplorer(sym) {
  sym = (sym || exSymbol || S.symbol).trim();
  if (!sym) return;
  exSymbol = sym.toUpperCase(); $("#exSymbol").value = exSymbol;
  await guarded($("#exGo"), async () => {
    const q = await api("/api/quote/" + encodeURIComponent(exSymbol));
    setMeta(null, q.source);
    const rows = [["Price", `Rs ${num(q.price)}`, `${num(q.change)} (${pct(q.change_pct)})`, cls(q.change)], ["Day range", `${num(q.low)} - ${num(q.high)}`, `open ${num(q.open)}`], ["52-week range", `${num(q.year_low)} - ${num(q.year_high)}`, ""], ["Volume", q.volume ? Number(q.volume).toLocaleString("en-IN") : "-", `as of ${esc(q.as_of)}`]];
    $("#exStats").innerHTML = `<div class="card"><div class="k">${esc(q.name)} (${esc(q.symbol)})</div><div class="v">${num(q.price)}</div><div class="s ${cls(q.change)}">${num(q.change)} (${pct(q.change_pct)})</div></div>` +
      rows.slice(1).map(r => `<div class="card"><div class="k">${r[0]}</div><div class="v" style="font-size:17px">${r[1]}</div><div class="s muted">${r[2]}</div></div>`).join("");
    await loadChart();
  });
}
async function loadChart() {
  if (!exSymbol) return;
  const [period, interval] = RANGES[exRange];
  await guarded(null, async () => {
    lastHist = await api(`/api/history/${encodeURIComponent(exSymbol)}?period=${period}&interval=${interval}`);
    renderExplorerChart(lastHist);
    const t = lastHist.technical || {};
    $("#exTech").innerHTML = Object.keys(t).length ? [`RSI ${t.rsi} - ${t.rsi_view}`, t.trend, t.macd_view].filter(Boolean).map(x => `<span class="chip static">${esc(x)}</span>`).join("") : "";
    const n = lastHist.dates.length, from = Math.max(0, n - 15);
    let h = `<thead><tr><th>Date</th><th class="r">Open</th><th class="r">High</th><th class="r">Low</th><th class="r">Close</th><th class="r">Volume</th></tr></thead><tbody>`;
    for (let i = n - 1; i >= from; i--) h += `<tr><td>${lastHist.dates[i]}</td><td class="r">${num(lastHist.open[i])}</td><td class="r">${num(lastHist.high[i])}</td><td class="r">${num(lastHist.low[i])}</td><td class="r">${num(lastHist.close[i])}</td><td class="r">${lastHist.volume[i] ? Number(lastHist.volume[i]).toLocaleString("en-IN") : "-"}</td></tr>`;
    $("#histTable").innerHTML = h + "</tbody>";
  });
}
function renderExplorerChart(h) {
  const up = h.close[h.close.length - 1] >= h.close[0], col = up ? "#0fa968" : "#e5484d";
  const ds = [{ label: "Close", data: h.close, borderColor: col, backgroundColor: col + "22", fill: true, pointRadius: 0, borderWidth: 2, tension: .1 }];
  if ($("#exSma20").checked) ds.push({ label: "SMA 20", data: h.sma20, borderColor: "#f5a623", pointRadius: 0, borderWidth: 1.2, fill: false });
  if ($("#exSma50").checked) ds.push({ label: "SMA 50", data: h.sma50, borderColor: "#5b5bf0", pointRadius: 0, borderWidth: 1.2, fill: false });
  draw("exChart", { type: "line", data: { labels: h.dates, datasets: ds }, options: lineOpts({ plugins: { legend: { display: true, labels: { boxWidth: 10 } } } }) });
  const showVol = $("#exVol").checked; $("#exVolBox").classList.toggle("hidden", !showVol);
  if (showVol) draw("exVolChart", { type: "bar", data: { labels: h.dates, datasets: [{ data: h.volume, backgroundColor: "#5b5bf066" }] }, options: lineOpts({ scales: { x: { display: false }, y: { grid: { color: "#edf0f9" }, ticks: { maxTicksLimit: 3 } } } }) });
}
$("#exGo").addEventListener("click", () => resolveAndLoad());
$("#exSymbol").addEventListener("keydown", e => { if (e.key === "Enter") resolveAndLoad(); });
async function resolveAndLoad() {
  const q = $("#exSymbol").value.trim(); if (!q) return;
  try {
    const res = await api("/api/search?q=" + encodeURIComponent(q));
    const exact = res.find(r => r.symbol.toUpperCase() === q.toUpperCase());
    $("#exResults").innerHTML = res.length > 1 && !exact ? res.map(r => `<span class="chip" data-s="${esc(r.symbol)}">${esc(r.symbol)} - ${esc(r.name)}</span>`).join("") : "";
    loadExplorer(exact ? exact.symbol : (res.length > 1 ? res[0].symbol : q));
  } catch (e) { loadExplorer(q); }
}
$("#exResults").addEventListener("click", e => { const c = e.target.closest("[data-s]"); if (c) { $("#exResults").innerHTML = ""; loadExplorer(c.dataset.s); } });
$("#exWatch").addEventListener("click", () => { if (!exSymbol) return; if (!watch.includes(exSymbol)) { watch.push(exSymbol); saveWatch(); } $("#exWatch").textContent = "Added"; setTimeout(() => $("#exWatch").textContent = "Add to watchlist", 1200); });

$("#cmpGo").addEventListener("click", () => guarded($("#cmpGo"), async () => {
  const d = await api(`/api/compare?symbols=${encodeURIComponent($("#cmpSymbols").value)}&period=${$("#cmpPeriod").value}`);
  const keys = Object.keys(d.series);
  draw("cmpChart", { type: "line", data: { labels: d.dates, datasets: keys.map((k, i) => ({ label: k, data: d.series[k], borderColor: COLORS[i % 6], pointRadius: 0, borderWidth: 1.8 })) }, options: lineOpts({ plugins: { legend: { display: true, labels: { boxWidth: 10 } } } }) });
  $("#cmpTable").innerHTML = `<thead><tr><th>Symbol</th><th>Company</th><th class="r">Return</th><th class="r">Volatility (ann.)</th></tr></thead><tbody>` +
    d.stats.map(s => `<tr><td><b>${esc(s.symbol)}</b></td><td class="muted">${esc(s.name)}</td><td class="r ${cls(s.return_pct)}">${pct(s.return_pct)}</td><td class="r">${num(s.volatility_pct, 1)}%</td></tr>`).join("") + "</tbody>";
}));

/* ------------------------------------------------------------ news */
async function loadNews() {
  await guarded($("#newsGo"), async () => {
    const sym = $("#newsSymbol").value.trim();
    const d = await api(`/api/news?symbol=${encodeURIComponent(sym)}&extra=${encodeURIComponent(S.news || "")}`);
    setMeta(null, null);
    const s = d.summary;
    draw("sentChart", { type: "doughnut", data: { labels: ["Positive", "Neutral", "Negative"], datasets: [{ data: [s.positive, s.neutral, s.negative], backgroundColor: ["#0fa968", "#cbd2e6", "#e5484d"], borderWidth: 0 }] }, options: { plugins: { legend: { position: "right", labels: { boxWidth: 10 } } }, cutout: "62%" } });
    $("#sentSummary").innerHTML = s.total ? `Overall tone: <b class="${s.label === "positive" ? "up" : s.label === "negative" ? "down" : ""}">${s.label}</b> (average score ${s.avg_score}) across ${s.total} headlines.` : "";
    $("#newsList").innerHTML = d.items.length ? d.items.map(i => `<div class="news-item"><span class="tag ${i.sentiment.label}">${i.sentiment.label} ${i.sentiment.score > 0 ? "+" : ""}${i.sentiment.score}</span><div><a href="${esc(i.link)}" target="_blank" rel="noopener noreferrer">${esc(i.title)}</a><small>${esc(i.source)} | ${esc(i.published)}</small></div></div>`).join("") : `<p class="muted">${esc(d.error || "No headlines found.")}</p>`;
  });
}
$("#newsGo").addEventListener("click", loadNews);
$("#newsSymbol").addEventListener("keydown", e => { if (e.key === "Enter") loadNews(); });

/* ------------------------------------------------------------ chat */
const SUGGEST = ["How is TCS doing today?", "What is RSI?", "Explain max drawdown", "Is Reliance volatile?", "What does P/E ratio mean?"];
function addMsg(role, text, meta) {
  const d = document.createElement("div"); d.className = "msg " + (role === "user" ? "user" : "bot"); d.textContent = text;
  if (meta) { const s = document.createElement("small"); s.textContent = meta; d.appendChild(s); }
  $("#chatLog").appendChild(d); $("#chatLog").scrollTop = 1e9; return d;
}
async function sendChat(text) {
  text = (text || $("#chatInput").value).trim(); if (!text) return;
  $("#chatInput").value = ""; addMsg("user", text);
  const wait = addMsg("bot", "Thinking...");
  try {
    const r = await post("/api/chat", { message: text, history: chatHistory });
    wait.remove(); addMsg("bot", r.reply, r.mode === "llm" ? "AI model, grounded in live data" : "rule-based mode, grounded in live data");
    chatHistory.push({ role: "user", content: text }, { role: "assistant", content: r.reply }); chatHistory = chatHistory.slice(-10);
  } catch (e) { wait.remove(); addMsg("bot", "Error: " + e.message); }
}
$("#chatSend").addEventListener("click", () => sendChat());
$("#chatInput").addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });
$("#chatSuggest").innerHTML = SUGGEST.map(s => `<span class="chip" data-q="${esc(s)}">${esc(s)}</span>`).join("");
$("#chatSuggest").addEventListener("click", e => { const c = e.target.closest("[data-q]"); if (c) sendChat(c.dataset.q); });

/* ------------------------------------------------------------ forecast */
$("#fcGo").addEventListener("click", () => guarded($("#fcGo"), async () => {
  const d = await post("/api/forecast", { symbol: $("#fcSymbol").value.trim(), model: $("#fcModel").value, horizon: +$("#fcHorizon").value || 10, period: $("#fcPeriod").value });
  const h = d.history, f = d.forecast, pad = new Array(h.dates.length).fill(null);
  const labels = [...h.dates, ...f.dates];
  const last = h.close[h.close.length - 1];
  const join = arr => [...new Array(h.dates.length - 1).fill(null), last, ...arr];
  draw("fcChart", {
    type: "line", data: {
      labels, datasets: [
        { label: "Actual close", data: [...h.close, ...new Array(f.dates.length).fill(null)], borderColor: "#1b2340", pointRadius: 0, borderWidth: 1.8 },
        { label: "Upper band", data: join(f.upper), borderColor: "transparent", backgroundColor: "#5b5bf022", pointRadius: 0, fill: "+1" },
        { label: "Lower band", data: join(f.lower), borderColor: "transparent", pointRadius: 0, fill: false },
        { label: "Forecast", data: join(f.values), borderColor: "#5b5bf0", borderDash: [6, 4], pointRadius: 2, borderWidth: 2 }]
    }, options: lineOpts({ plugins: { legend: { display: true, labels: { boxWidth: 10, filter: i => !i.text.includes("band") } } } })
  });
  const m = d.metrics, a = m.model, b = m.naive_baseline;
  $("#fcTable").innerHTML = `<thead><tr><th>Held-out test (${m.test_rows} days)</th><th class="r">${esc(d.model_name)}</th><th class="r">Naive baseline</th></tr></thead><tbody>
    <tr><td>RMSE (daily return)</td><td class="r">${(a.rmse_return * 100).toFixed(3)}%</td><td class="r">${(b.rmse_return * 100).toFixed(3)}%</td></tr>
    <tr><td>MAE (daily return)</td><td class="r">${(a.mae_return * 100).toFixed(3)}%</td><td class="r">${(b.mae_return * 100).toFixed(3)}%</td></tr>
    <tr><td>Next-day price MAPE</td><td class="r">${a.price_mape_pct.toFixed(3)}%</td><td class="r">${b.price_mape_pct.toFixed(3)}%</td></tr>
    <tr><td>Directional accuracy</td><td class="r">${frac(a.directional_accuracy)}</td><td class="r">${frac(b.directional_accuracy)}</td></tr></tbody>`;
  const good = m.beats_naive_rmse && m.beats_naive_direction;
  const v = $("#fcVerdict"); v.className = "callout " + (good ? "good" : "warn");
  v.innerHTML = `<b>${esc(d.symbol)}</b>: model projects <b class="${cls(d.expected_change_pct)}">${pct(d.expected_change_pct)}</b> over ${f.dates.length} trading days (last close Rs ${num(d.last_close)}). ` +
    (good ? "On held-out data the model beat the naive baseline on both error and direction - a mildly encouraging, not conclusive, result." : "On held-out data the model did <b>not</b> clearly beat the naive baseline on both error and direction - treat this forecast as low-confidence. That is common for stock prices.");
  $("#fcNote").textContent = d.disclaimer;
}));

/* ------------------------------------------------------------ models doc */
async function loadModels() {
  if ($("#modelDocs").dataset.done) return;
  await guarded(null, async () => {
    const d = await api("/api/models");
    const list = a => `<ul>${a.map(x => `<li>${esc(x)}</li>`).join("")}</ul>`;
    $("#modelDocs").innerHTML = `
      <div class="panel doc"><h3>Forecasting models</h3>${d.models.map(m => `<p><b>${esc(m.name)}</b> - ${esc(m.what)}<br><span class="muted">+ ${esc(m.pros)} &nbsp; - ${esc(m.cons)}</span></p>`).join("")}<h3>Features</h3>${list(d.features)}<h3>Validation</h3><p class="muted">${esc(d.validation)}</p></div>
      <div class="panel doc"><h3>Evaluation metrics</h3>${d.metrics.map(m => `<p><b>${esc(m.name)}</b><br><span class="muted">${esc(m.meaning)}</span></p>`).join("")}</div>
      <div class="panel doc"><h3>Sentiment analysis</h3><p>${esc(d.sentiment.method)}</p><p class="muted">${esc(d.sentiment.limits)}</p></div>
      <div class="panel doc"><h3>Limitations - please read</h3>${list(d.limitations)}</div>`;
    $("#modelDocs").dataset.done = 1;
  });
}

/* ------------------------------------------------------------ strategy */
const PARAMS = {
  sma_cross: [["fast", "Fast SMA", 20], ["slow", "Slow SMA", 50]],
  rsi_reversion: [["buy_below", "Buy below RSI", 30], ["sell_above", "Sell above RSI", 70]],
  breakout: [["entry", "Entry high (days)", 20], ["exit", "Exit low (days)", 10]], buy_hold: []
};
function renderParams() {
  $("#stParams").innerHTML = PARAMS[$("#stStrategy").value].map(([k, l, v]) => `<label>${l} <input data-p="${k}" type="number" value="${v}" style="width:80px"></label>`).join("");
}
$("#stStrategy").addEventListener("change", renderParams);
$("#stGo").addEventListener("click", () => guarded($("#stGo"), async () => {
  const params = {}; $$("#stParams input").forEach(i => params[i.dataset.p] = +i.value);
  const d = await post("/api/backtest", { symbol: $("#stSymbol").value.trim(), strategy: $("#stStrategy").value, params, period: $("#stPeriod").value, capital: +$("#stCapital").value || 100000, cost_bps: +$("#stCost").value || 0 });
  draw("stChart", { type: "line", data: { labels: d.dates, datasets: [{ label: "Strategy", data: d.equity, borderColor: "#5b5bf0", pointRadius: 0, borderWidth: 2 }, { label: "Buy & hold", data: d.buy_hold, borderColor: "#6b7694", borderDash: [5, 4], pointRadius: 0, borderWidth: 1.5 }] }, options: lineOpts({ plugins: { legend: { display: true, labels: { boxWidth: 10 } } } }) });
  const m = d.metrics, b = d.buy_hold_metrics;
  const card = (k, v, s, c) => `<div class="card"><div class="k">${k}</div><div class="v ${c || ""}" style="font-size:18px">${v}</div><div class="s muted">${s || ""}</div></div>`;
  $("#stMetrics").innerHTML = card("Total return", frac(m.total_return), "buy & hold " + frac(b.total_return), cls(m.total_return)) + card("CAGR", frac(m.cagr), "buy & hold " + frac(b.cagr)) +
    card("Max drawdown", frac(m.max_drawdown), "buy & hold " + frac(b.max_drawdown), "down") + card("Sharpe", m.sharpe == null ? "-" : num(m.sharpe), "buy & hold " + (b.sharpe == null ? "-" : num(b.sharpe))) +
    card("Trades", m.trades, m.win_rate == null ? "" : "win rate " + frac(m.win_rate, 0)) + card("Time in market", frac(m.time_in_market, 0), "final Rs " + num(m.final_value, 0));
  $("#stNote").textContent = d.assumptions + " Backtests do not predict future returns.";
  $("#stTrades").innerHTML = `<thead><tr><th>Entry</th><th>Exit</th><th class="r">Entry px</th><th class="r">Exit px</th><th class="r">Return</th><th>Status</th></tr></thead><tbody>` +
    (d.trades.length ? d.trades.map(t => `<tr><td>${t.entry}</td><td>${t.exit}</td><td class="r">${num(t.entry_price)}</td><td class="r">${num(t.exit_price)}</td><td class="r ${cls(t.return_pct)}">${pct(t.return_pct)}</td><td>${t.status}</td></tr>`).join("") : `<tr><td colspan="6" class="muted">No trades triggered.</td></tr>`) + "</tbody>";
}));

/* ------------------------------------------------------------ risk */
$("#rkGo").addEventListener("click", () => guarded($("#rkGo"), async () => {
  const d = await api(`/api/risk/${encodeURIComponent($("#rkSymbol").value.trim())}?period=${$("#rkPeriod").value}`);
  const card = (k, v, s, c) => `<div class="card"><div class="k">${k}</div><div class="v ${c || ""}" style="font-size:19px">${v}</div><div class="s muted">${s || ""}</div></div>`;
  $("#rkCards").innerHTML = card("Risk level", d.risk_level, "by annualised volatility") + card("Volatility (ann.)", frac(d.annualized_volatility)) + card("Max drawdown", frac(d.max_drawdown), "worst peak-to-trough", "down") +
    card("1-day VaR 95%", frac(d.var_95, 2), "exceeded on ~5% of days") + card("CVaR 95%", frac(d.cvar_95, 2), "avg loss on those days") + card("Sharpe", d.sharpe == null ? "-" : num(d.sharpe), "vs 7% risk-free") +
    card("Sortino", d.sortino == null ? "-" : num(d.sortino)) + card("Beta vs NIFTY", d.beta == null ? "-" : num(d.beta), d.beta == null ? "" : d.beta > 1 ? "more volatile than market" : "less volatile than market") +
    card("Best / worst day", `${frac(d.best_day, 1)} / ${frac(d.worst_day, 1)}`) + card("Return over period", frac(d.total_return), "annualised " + frac(d.annualized_return), cls(d.total_return));
  draw("rkDD", { type: "line", data: { labels: d.drawdown.dates, datasets: [{ data: d.drawdown.values, borderColor: "#e5484d", backgroundColor: "#e5484d33", fill: true, pointRadius: 0, borderWidth: 1.5 }] }, options: lineOpts() });
  draw("rkVol", { type: "line", data: { labels: d.rolling_vol.dates, datasets: [{ data: d.rolling_vol.values, borderColor: "#f5a623", pointRadius: 0, borderWidth: 1.5 }] }, options: lineOpts() });
  draw("rkHist", { type: "bar", data: { labels: d.histogram.labels, datasets: [{ data: d.histogram.counts, backgroundColor: d.histogram.labels.map(l => +l < 0 ? "#e5484d99" : "#0fa96899") }] }, options: lineOpts({ scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 10 } }, y: { grid: { color: "#edf0f9" } } } }) });
}));

/* ------------------------------------------------------------ watchlist */
async function loadWatchlist() {
  $("#wlEmpty").classList.toggle("hidden", watch.length > 0);
  if (!watch.length) { $("#wlTable").innerHTML = ""; return; }
  await guarded(null, async () => {
    const qs = await api("/api/quotes?symbols=" + encodeURIComponent(watch.join(",")));
    setMeta(null, qs.find(q => q.source)?.source);
    $("#wlTable").innerHTML = `<thead><tr><th>Symbol</th><th>Company</th><th class="r">Price (Rs)</th><th class="r">Change %</th><th class="r">Day range</th><th class="r">52w range</th><th></th></tr></thead><tbody>` +
      qs.map(q => q.error ? `<tr><td><b>${esc(q.symbol)}</b></td><td colspan="5" class="down">${esc(q.error)}</td><td><button class="ghost" data-rm="${esc(q.symbol)}">Remove</button></td></tr>` :
        `<tr class="click" data-sym="${esc(q.symbol)}"><td><b>${esc(q.symbol)}</b></td><td class="muted">${esc(q.name)}</td><td class="r">${num(q.price)}</td><td class="r ${cls(q.change)}">${pct(q.change_pct)}</td><td class="r">${num(q.low)} - ${num(q.high)}</td><td class="r">${num(q.year_low)} - ${num(q.year_high)}</td><td><button class="ghost" data-rm="${esc(q.symbol)}">Remove</button></td></tr>`).join("") + "</tbody>";
  });
}
$("#wlTable").addEventListener("click", e => {
  const rm = e.target.closest("[data-rm]"); if (rm) { watch = watch.filter(s => s !== rm.dataset.rm.toUpperCase()); saveWatch(); loadWatchlist(); return; }
  const tr = e.target.closest("tr[data-sym]"); if (tr) openSymbol(tr.dataset.sym);
});
$("#wlAdd").addEventListener("click", () => { const s = $("#wlSymbol").value.trim().toUpperCase(); if (s && !watch.includes(s)) { watch.push(s); saveWatch(); } $("#wlSymbol").value = ""; loadWatchlist(); });
$("#wlSymbol").addEventListener("keydown", e => { if (e.key === "Enter") $("#wlAdd").click(); });

/* ------------------------------------------------------------ settings */
function fillSettings() { $("#setSymbol").value = S.symbol; $("#setRefresh").value = S.refresh; $("#setNews").value = S.news; $("#setApi").value = S.apiBase; buildRangeButtons(); }
$("#setSave").addEventListener("click", () => {
  S = { symbol: $("#setSymbol").value.trim().toUpperCase() || DEFAULTS.symbol, range: $("#setRange").value, refresh: Math.max(0, +$("#setRefresh").value || 0), news: $("#setNews").value.trim(), apiBase: $("#setApi").value.trim() };
  try { localStorage.setItem("ss_settings", JSON.stringify(S)); } catch { }
  exRange = S.range; buildRangeButtons(); startTimer(); $("#setMsg").textContent = "Saved.";
});
$("#setReset").addEventListener("click", () => { try { localStorage.removeItem("ss_settings"); } catch { } S = { ...DEFAULTS }; fillSettings(); startTimer(); $("#setMsg").textContent = "Reset to defaults."; });

/* ------------------------------------------------------------ loaders / boot */
const loaders = {
  overview: loadOverview,
  explorer: () => { if (!lastHist || lastHist.symbol !== (exSymbol || "").toUpperCase()) loadExplorer(exSymbol || S.symbol); },
  news: () => { if (!$("#newsList").children.length) loadNews(); },
  chat: () => { if (!$("#chatLog").children.length) addMsg("bot", "Hi! I'm StockSense AI. Ask me about any NSE stock, an indicator, or a market term - I'll use live data where I can.\n\nResearch only, not financial advice."); },
  forecast: () => { }, models: loadModels, strategy: () => { }, risk: () => { }, watchlist: loadWatchlist, settings: fillSettings,
};
let timer = null;
function startTimer() {
  clearInterval(timer);
  if (S.refresh > 0) timer = setInterval(() => { if (document.hidden) return; if (current === "overview") loadOverview(); else if (current === "watchlist") loadWatchlist(); }, Math.max(5, S.refresh) * 1000);
}

(async function boot() {
  buildRangeButtons(); renderParams(); fillSettings();
  api("/api/stocks").then(list => { $("#symbols").innerHTML = list.map(s => `<option value="${esc(s.symbol)}">${esc(s.name)}</option>`).join(""); }).catch(() => { });
  api("/api/health").then(h => setMeta(h.market, h.demo ? "demo" : null)).catch(e => showError(e.message));
  startTimer();
  const start = location.hash.slice(1);
  show(loaders[start] ? start : "overview");
})();
