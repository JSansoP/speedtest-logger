const API = "/api";

const RANGES = [
  { key: "24h", label: "24 h", long: "last 24 hours", days: 1 },
  { key: "7d", label: "7 d", long: "last 7 days", days: 7 },
  { key: "30d", label: "30 d", long: "last 30 days", days: 30 },
  { key: "90d", label: "90 d", long: "last 90 days", days: 90 },
  { key: "1y", label: "1 y", long: "last year", days: 365 },
  { key: "all", label: "All", long: "all time", days: null },
];

const DATA_WINDOWS = {
  last_day: "Last 24 hours",
  last_week: "Last 7 days",
  last_month: "Last 30 days",
  last_3_months: "Last 3 months",
  last_6_months: "Last 6 months",
  last_year: "Last year",
};

const SCHEDULE_PRESETS = [
  { label: "Daily at 08:00", cron: "0 8 * * *" },
  { label: "Every Monday at 08:00", cron: "0 8 * * 1" },
  { label: "First of the month", cron: "0 8 1 * *" },
  { label: "Every 6 hours", cron: "0 */6 * * *" },
];

const PAGE_SIZE = 50;
const LOW_PLAN_PCT = 50;

const ICONS = {
  trash: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4h11M6 4V2.5h4V4M4 4l.7 9.5h6.6L12 4"/></svg>',
  edit: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.5 2.5l3 3L6 13H3v-3z"/></svg>',
  download: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2v8M4.5 6.5L8 10l3.5-3.5M2.5 13.5h11"/></svg>',
};

const state = {
  range: readPref("range", "7d"),
  unit: readPref("unit", "mbps"),
  status: null,
  settings: null,
  results: null,
  resultsRange: null,
  charts: [],
  historySort: { key: "timestamp", dir: -1 },
  historyPage: 0,
  confirmingId: null,
};

const view = document.getElementById("view");

/* Utilities */

function readPref(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function writePref(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {}
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

async function api(path, options = {}) {
  const init = { ...options, headers: { Accept: "application/json" } };
  if (options.json !== undefined) {
    init.body = JSON.stringify(options.json);
    init.headers["Content-Type"] = "application/json";
  }
  let response;
  try {
    response = await fetch(API + path, init);
  } catch {
    throw new Error("Cannot reach the backend. Check that the service is running.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.error || `Request failed with status ${response.status}`);
  return body;
}

function formatSpeed(value) {
  if (value == null || Number.isNaN(value)) return "–";
  if (value >= 99.5) return value.toFixed(0);
  if (value >= 9.995) return value.toFixed(1);
  return value.toFixed(2);
}

function formatPlan(value) {
  if (value == null) return "–";
  return Number.isInteger(value) ? String(value) : formatSpeed(value);
}

function formatPing(value) {
  if (value == null || Number.isNaN(value)) return "–";
  return value >= 9.95 ? value.toFixed(0) : value.toFixed(1);
}

function formatPct(value) {
  if (value == null || Number.isNaN(value)) return "–";
  return `${value.toFixed(0)}%`;
}

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const dateTimeFormat = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const dayFormat = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const fullFormat = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

function isSameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function formatWhen(date) {
  if (!date) return "–";
  const now = new Date();
  if (isSameDay(date, now)) return `today ${timeFormat.format(date)}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (isSameDay(date, yesterday)) return `yesterday ${timeFormat.format(date)}`;
  return dateTimeFormat.format(date);
}

function quantile(sorted, q) {
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  return sorted[base + 1] !== undefined ? sorted[base] + rest * (sorted[base + 1] - sorted[base]) : sorted[base];
}

function summarize(values) {
  const clean = values.filter((v) => v != null && !Number.isNaN(v));
  if (!clean.length) return null;
  const sorted = [...clean].sort((a, b) => a - b);
  const mean = clean.reduce((sum, v) => sum + v, 0) / clean.length;
  const variance = clean.length > 1 ? clean.reduce((sum, v) => sum + (v - mean) ** 2, 0) / (clean.length - 1) : 0;
  return {
    count: clean.length,
    sorted,
    mean,
    median: quantile(sorted, 0.5),
    p10: quantile(sorted, 0.1),
    p90: quantile(sorted, 0.9),
    min: sorted[0],
    max: sorted[sorted.length - 1],
    std: Math.sqrt(variance),
  };
}

function niceCeil(value) {
  if (!(value > 0)) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((s) => s * magnitude >= value);
  return step * magnitude;
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function toast(message, kind = "info") {
  const el = document.createElement("div");
  el.className = `toast ${kind === "error" ? "error" : ""}`;
  el.textContent = message;
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), kind === "error" ? 8000 : 5000);
}

/* Data */

function rangeSince(rangeKey) {
  const range = RANGES.find((r) => r.key === rangeKey) ?? RANGES[1];
  if (range.days == null) return null;
  return new Date(Date.now() - range.days * 86400000);
}

async function loadResults(force = false) {
  if (!force && state.results && state.resultsRange === state.range) return state.results;
  const since = rangeSince(state.range);
  const query = since ? `?limit=0&since=${encodeURIComponent(since.toISOString())}` : "?limit=0";
  const rows = await api(`/speedtests${query}`);
  state.results = rows
    .map((r) => ({ ...r, time: new Date(r.timestamp) }))
    .sort((a, b) => a.time - b.time);
  state.resultsRange = state.range;
  return state.results;
}

async function loadSettings(force = false) {
  if (!force && state.settings) return state.settings;
  state.settings = await api("/settings");
  return state.settings;
}

function planValue(key) {
  const value = Number(state.settings?.[key]);
  return value > 0 ? value : null;
}

function pctOf(value, plan) {
  return plan > 0 && value != null ? (value / plan) * 100 : null;
}

/* Runner and status */

const runButton = document.getElementById("run-button");
const runnerStatus = document.getElementById("runner-status");
const progress = document.getElementById("progress");
let statusTimer = null;

function renderStatus() {
  const status = state.status;
  const running = Boolean(status?.running);
  runButton.disabled = running || !status;
  runButton.textContent = running ? "Testing…" : "Run test";
  progress.hidden = !running;
  if (!status) {
    runnerStatus.textContent = "Backend unreachable";
  } else if (running) {
    runnerStatus.textContent = "Measuring your connection";
  } else if (status.next_run) {
    runnerStatus.textContent = `Next test ${formatWhen(new Date(status.next_run))}`;
  } else {
    runnerStatus.textContent = "";
  }
}

async function refreshStatus() {
  const previous = state.status;
  try {
    state.status = await api("/status");
  } catch {
    state.status = null;
  }
  renderStatus();

  const finished = previous?.running && state.status && !state.status.running;
  const newResult = previous && state.status && previous.last_result_at !== state.status.last_result_at;
  if (newResult && state.results) await loadResults(true).catch(() => null);
  if (finished && newResult) {
    const latest = state.results?.at(-1);
    if (latest) toast(`Test finished: ${formatSpeed(latest.download)} Mbps down, ${formatSpeed(latest.upload)} Mbps up, ${formatPing(latest.ping)} ms.`);
    else toast("Test finished.");
  } else if (finished) {
    toast("The test did not produce a result. Check the backend logs for the fast-cli error.", "error");
  }
  if (newResult && ["dashboard", "history"].includes(currentView())) render();
  scheduleStatus();
}

function scheduleStatus() {
  clearTimeout(statusTimer);
  statusTimer = setTimeout(refreshStatus, state.status?.running ? 3000 : 30000);
}

runButton.addEventListener("click", async () => {
  runButton.disabled = true;
  try {
    await api("/speedtests/run", { method: "POST" });
  } catch (error) {
    toast(error.message, "error");
  }
  await refreshStatus();
});

/* Charts */

function destroyCharts() {
  state.charts.forEach(({ plot, observer }) => {
    observer.disconnect();
    plot.destroy();
  });
  state.charts = [];
}

function makeChart(container, { series, data, valueFormat, yLabel }) {
  const ink2 = cssVar("--ink-2");
  const muted = cssVar("--muted");
  const line = cssVar("--line");
  const surface = cssVar("--surface");
  const font = `12px ${cssVar("--font")}`;
  const pointCount = data[0].length;

  const axis = {
    stroke: muted,
    font,
    grid: { stroke: line, width: 1 },
    ticks: { show: false },
  };

  const opts = {
    width: container.clientWidth || 600,
    height: 240,
    padding: [12, 8, 0, 0],
    cursor: {
      points: { size: 9, width: 2, stroke: surface },
      drag: { x: true, y: false },
    },
    scales: { x: { time: true }, y: { range: (u, min, max) => [0, niceCeil(Math.max(max, 1) * 1.08)] } },
    axes: [
      { ...axis, grid: { show: false }, space: 80, values: timeAxisValues },
      { ...axis, size: 52, values: (u, ticks) => ticks.map((t) => (yLabel === "%" ? `${t}%` : t)) },
    ],
    legend: { live: true },
    hooks: {
      init: [
        (u) => {
          u.root.querySelectorAll(".u-legend .u-marker").forEach((marker, i) => {
            if (i > 0) marker.style.background = series[i - 1].color;
          });
        },
      ],
    },
    series: [
      { label: "Time", value: (u, v, si, idx) => legendValue(u, v, si, idx, (t) => fullFormat.format(new Date(t * 1000))) },
      ...series.map((s) => ({
        label: s.label,
        stroke: s.color,
        width: s.reference ? 1.5 : 2,
        dash: s.reference ? [5, 4] : undefined,
        paths: s.reference ? uPlot.paths.stepped({ align: 1 }) : undefined,
        fill: s.reference ? undefined : `${s.color}12`,
        points: { show: !s.reference && pointCount <= 72, size: 6, width: 2, stroke: surface, fill: s.color },
        value: (u, v, si, idx) => legendValue(u, v, si, idx, s.format ?? valueFormat),
        spanGaps: false,
      })),
    ],
  };

  const plot = new uPlot(opts, data, container);
  const observer = new ResizeObserver(() => {
    const width = container.clientWidth;
    if (width && width !== plot.width) plot.setSize({ width, height: 240 });
  });
  observer.observe(container);
  state.charts.push({ plot, observer });
}

function timeAxisValues(u, splits, axisIdx, space, increment) {
  let previousDay = null;
  return splits.map((t) => {
    const date = new Date(t * 1000);
    if (increment >= 86400) return dayFormat.format(date);
    const day = date.toDateString();
    const label = day !== previousDay ? `${timeFormat.format(date)}
${dayFormat.format(date)}` : timeFormat.format(date);
    previousDay = day;
    return label;
  });
}

function legendValue(u, value, seriesIdx, idx, format) {
  if (idx == null) {
    const column = u.data[seriesIdx];
    for (let i = column.length - 1; i >= 0; i--) {
      if (column[i] != null) return format(column[i]);
    }
    return "–";
  }
  return value == null ? "–" : format(value);
}

/* Router */

const VIEWS = { dashboard: renderDashboard, history: renderHistory, reports: renderReports, settings: renderSettings };

function currentView() {
  const name = location.hash.replace(/^#\//, "");
  return VIEWS[name] ? name : "dashboard";
}

let renderToken = 0;

async function render() {
  const name = currentView();
  const token = ++renderToken;
  document.querySelectorAll(".nav a").forEach((a) => {
    if (a.dataset.view === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  document.title = `${name[0].toUpperCase()}${name.slice(1)} – Speedtest Logger`;
  try {
    await VIEWS[name](() => token === renderToken);
  } catch (error) {
    if (token !== renderToken) return;
    destroyCharts();
    view.innerHTML = `
      <div class="panel empty">
        <h2>Could not load this page</h2>
        <p>${esc(error.message)}</p>
        <button class="button" type="button" data-action="retry">Try again</button>
      </div>`;
    view.querySelector("[data-action=retry]").addEventListener("click", render);
  }
}

window.addEventListener("hashchange", () => {
  state.confirmingId = null;
  render();
  view.focus({ preventScroll: true });
});

/* Shared controls */

function rangeControl() {
  return `
    <div class="segmented" role="group" aria-label="Time range">
      ${RANGES.map((r) => `<button type="button" data-range="${r.key}" aria-pressed="${r.key === state.range}">${r.label}</button>`).join("")}
    </div>`;
}

function bindRangeControl() {
  view.querySelectorAll("[data-range]").forEach((button) =>
    button.addEventListener("click", () => {
      if (button.dataset.range === state.range) return;
      state.range = button.dataset.range;
      state.historyPage = 0;
      writePref("range", state.range);
      render();
    }),
  );
}

function emptyResults() {
  const next = state.status?.next_run ? ` The next scheduled test runs ${formatWhen(new Date(state.status.next_run))}.` : "";
  const hasAny = state.status?.total_results > 0;
  return `
    <div class="panel empty">
      <h2>${hasAny ? "No tests in this range" : "No tests recorded yet"}</h2>
      <p>${hasAny ? "Pick a longer time range to see older results." : `Run a test now to get your first measurement.${next}`}</p>
      ${hasAny ? "" : '<button class="button primary" type="button" data-action="run">Run test</button>'}
    </div>`;
}

function bindEmpty() {
  view.querySelector("[data-action=run]")?.addEventListener("click", () => runButton.click());
}

/* Dashboard */

function stripMarkup(stats, latest, plan, color, format, unit) {
  const max = niceCeil(Math.max(stats.max, plan ?? 0) * 1.05);
  const pos = (v) => `${Math.min(100, Math.max(0, (v / max) * 100)).toFixed(2)}%`;
  const binCount = 64;
  const bins = new Array(binCount).fill(0);
  stats.sorted.forEach((v) => {
    bins[Math.min(binCount - 1, Math.floor((v / max) * binCount))]++;
  });
  const peak = Math.max(...bins);
  const rects = bins
    .map((count, i) => (count ? `<rect x="${i}" width="1.02" height="1" fill="${color}" opacity="${(0.16 + 0.84 * (count / peak)).toFixed(2)}"/>` : ""))
    .join("");
  const planFlip = plan != null && plan / max < 0.25;
  const description = `${stats.count} tests between ${format(stats.min)} and ${format(stats.max)} ${unit}, median ${format(stats.median)}${plan ? `, plan ${formatPlan(plan)}` : ""}.`;
  return `
    <figure class="strip" aria-label="${esc(description)}">
      <div class="strip-track">
        <svg viewBox="0 0 ${binCount} 1" preserveAspectRatio="none" aria-hidden="true">${rects}</svg>
        ${plan ? `<div class="strip-plan ${planFlip ? "flip" : ""}" style="left:${pos(plan)}"><span>Plan ${formatPlan(plan)}</span></div>` : ""}
        <div class="strip-mark" style="left:${pos(stats.median)}" title="Median ${format(stats.median)} ${unit}"></div>
        <div class="strip-dot" style="left:${pos(latest)}" title="Latest ${format(latest)} ${unit}"></div>
      </div>
      <div class="strip-axis" aria-hidden="true"><span>0</span><span>${formatPlan(max)} ${unit}</span></div>
    </figure>`;
}

function readoutMarkup({ label, colorVar, values, latest, latestTime, plan, unit, format, lowerIsBetter }) {
  const stats = summarize(values);
  const color = cssVar(colorVar);
  let sub;
  if (plan) {
    sub = `Median <strong>${format(stats.median)} ${unit}</strong>, ${formatPct(pctOf(stats.median, plan))} of the ${formatPlan(plan)} ${unit} plan.`;
  } else if (lowerIsBetter) {
    sub = `Median <strong>${format(stats.median)} ${unit}</strong>, worst 10% above ${format(stats.p90)} ${unit}.`;
  } else {
    sub = `Median <strong>${format(stats.median)} ${unit}</strong>. Set your plan in Settings to compare.`;
  }
  return `
    <article class="readout" style="--series:var(${colorVar})">
      <h2 class="readout-label"><span class="swatch"></span>${label}</h2>
      <p class="readout-value"><span class="num">${format(latest)}</span><span class="unit">${unit}</span></p>
      <p class="readout-sub">Latest test ${formatWhen(latestTime)}.<br>${sub}</p>
      ${stripMarkup(stats, latest, plan, color, format, unit)}
    </article>`;
}

function statsRow(label, colorVar, values, format, unit, plan, lowerIsBetter) {
  const s = summarize(values);
  const worst = lowerIsBetter ? s.p90 : s.p10;
  const ofPlan = plan ? formatPct(pctOf(s.median, plan)) : "–";
  return `
    <tr>
      <td class="row-label"><span class="swatch" style="--series:var(${colorVar})"></span>${label} <span class="subtle">${unit}</span></td>
      <td class="r">${format(values.at(-1))}</td>
      <td class="r">${format(s.median)}</td>
      <td class="r">${format(s.mean)}</td>
      <td class="r">${format(worst)}</td>
      <td class="r">${format(s.min)}</td>
      <td class="r">${format(s.max)}</td>
      <td class="r">${format(s.std)}</td>
      <td class="r ${plan ? "" : "muted"}">${ofPlan}</td>
    </tr>`;
}

async function renderDashboard(isCurrent) {
  if (!state.results || state.resultsRange !== state.range) {
    destroyCharts();
    view.innerHTML = `<div class="view-head"><h1>Dashboard</h1>${rangeControl()}</div><div class="skeleton"></div>`;
  }
  const [results] = await Promise.all([loadResults(), loadSettings()]);
  if (!isCurrent()) return;
  destroyCharts();

  const hasPlanData = results.some((r) => r.advertised_download > 0 || r.advertised_upload > 0);
  const unit = hasPlanData ? state.unit : "mbps";
  const head = `
    <div class="view-head">
      <h1>Dashboard</h1>
      <span class="toolbar-note">${results.length} ${results.length === 1 ? "test" : "tests"}</span>
      ${rangeControl()}
    </div>`;

  if (!results.length) {
    view.innerHTML = head + emptyResults();
    bindRangeControl();
    bindEmpty();
    return;
  }

  const latest = results.at(-1);
  const downloads = results.map((r) => r.download);
  const uploads = results.map((r) => r.upload);
  const pings = results.map((r) => r.ping);
  const planDown = planValue("advertised_download");
  const planUp = planValue("advertised_upload");

  view.innerHTML = `
    ${head}
    <section class="readouts" aria-label="Current readings">
      ${readoutMarkup({ label: "Download", colorVar: "--dl", values: downloads, latest: latest.download, latestTime: latest.time, plan: planDown, unit: "Mbps", format: formatSpeed })}
      ${readoutMarkup({ label: "Upload", colorVar: "--ul", values: uploads, latest: latest.upload, latestTime: latest.time, plan: planUp, unit: "Mbps", format: formatSpeed })}
      ${readoutMarkup({ label: "Latency", colorVar: "--ping", values: pings, latest: latest.ping, latestTime: latest.time, plan: null, unit: "ms", format: formatPing, lowerIsBetter: true })}
      <div class="strip-key" aria-hidden="true">
        <span><i class="key-density"></i>Darker band, more tests at that value</span>
        <span><i class="key-median"></i>Median</span>
        <span><i class="key-latest"></i>Latest test</span>
        <span><i class="key-plan"></i>Plan</span>
      </div>
    </section>
    <div class="charts">
      <section class="panel wide">
        <div class="panel-head">
          <h2>Download</h2>
          <p>${unit === "pct" ? "Percent of the plan in force at each test" : "Mbps, dashed line is the plan in force at each test"}</p>
          ${hasPlanData ? `<div class="segmented push" role="group" aria-label="Speed units">
            <button type="button" data-unit="mbps" aria-pressed="${unit === "mbps"}">Mbps</button>
            <button type="button" data-unit="pct" aria-pressed="${unit === "pct"}">% of plan</button>
          </div>` : ""}
        </div>
        <div class="chart" id="chart-download"></div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>Upload</h2><p>${unit === "pct" ? "Percent of plan" : "Mbps"}</p></div>
        <div class="chart" id="chart-upload"></div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>Latency</h2><p>Milliseconds, lower is better</p></div>
        <div class="chart" id="chart-ping"></div>
      </section>
    </div>
    <section class="panel">
      <div class="panel-head"><h2>Statistics</h2><p>${results.length} tests, ${esc(RANGES.find((r) => r.key === state.range).long)}. Worst 10% is the 10th percentile for speed and the 90th for latency.</p></div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th></th><th class="r">Latest</th><th class="r">Median</th><th class="r">Mean</th><th class="r">Worst 10%</th>
            <th class="r">Min</th><th class="r">Max</th><th class="r">Std dev</th><th class="r">Median of plan</th>
          </tr></thead>
          <tbody>
            ${statsRow("Download", "--dl", downloads, formatSpeed, "Mbps", planDown)}
            ${statsRow("Upload", "--ul", uploads, formatSpeed, "Mbps", planUp)}
            ${statsRow("Latency", "--ping", pings, formatPing, "ms", null, true)}
          </tbody>
        </table>
      </div>
    </section>`;

  bindRangeControl();
  view.querySelectorAll("[data-unit]").forEach((button) =>
    button.addEventListener("click", () => {
      state.unit = button.dataset.unit;
      writePref("unit", state.unit);
      renderDashboard(isCurrent);
    }),
  );

  const xs = results.map((r) => r.time.getTime() / 1000);
  const speedChart = (id, key, planKey, label, colorVar) => {
    const color = cssVar(colorVar);
    const planColor = cssVar("--ink-2");
    const planned = results.map((r) => (r[planKey] > 0 ? r[planKey] : null));
    const hasPlan = planned.some((v) => v != null);
    if (unit === "pct") {
      const pct = results.map((r) => pctOf(r[key], r[planKey] > 0 ? r[planKey] : null));
      makeChart(document.getElementById(id), {
        data: [xs, pct, results.map((r) => (r[planKey] > 0 ? 100 : null))],
        series: [{ label: `${label} % of plan`, color }, { label: "Plan", color: planColor, reference: true }],
        valueFormat: (v) => `${v.toFixed(0)}%`,
        yLabel: "%",
      });
    } else {
      const series = [{ label, color }];
      const data = [xs, results.map((r) => r[key])];
      if (hasPlan) {
        series.push({ label: "Plan", color: planColor, reference: true, format: (v) => `${formatPlan(v)} Mbps` });
        data.push(planned);
      }
      makeChart(document.getElementById(id), { data, series, valueFormat: (v) => `${formatSpeed(v)} Mbps` });
    }
  };
  speedChart("chart-download", "download", "advertised_download", "Download", "--dl");
  speedChart("chart-upload", "upload", "advertised_upload", "Upload", "--ul");
  makeChart(document.getElementById("chart-ping"), {
    data: [xs, pings],
    series: [{ label: "Latency", color: cssVar("--ping") }],
    valueFormat: (v) => `${formatPing(v)} ms`,
  });
}

/* History */

const HISTORY_COLUMNS = [
  { key: "timestamp", label: "Time", value: (r) => r.time.getTime() },
  { key: "download", label: "Download", unit: "Mbps", value: (r) => r.download, align: "r" },
  { key: "upload", label: "Upload", unit: "Mbps", value: (r) => r.upload, align: "r" },
  { key: "ping", label: "Latency", unit: "ms", value: (r) => r.ping, align: "r" },
  { key: "plan", label: "Download of plan", value: (r) => pctOf(r.download, r.advertised_download) ?? -1 },
  { key: "advertised", label: "Plan", unit: "down / up", value: (r) => r.advertised_download ?? -1, align: "r" },
  { key: "server", label: "Server", value: (r) => r.server_name ?? "" },
];

function pctCell(row) {
  const pct = pctOf(row.download, row.advertised_download);
  if (pct == null) return '<td class="muted">–</td>';
  const low = pct < LOW_PLAN_PCT;
  return `<td><span class="pct ${low ? "low" : ""}"><span class="pct-bar"><i style="width:${Math.min(100, pct).toFixed(1)}%"></i></span>${formatPct(pct)}</span></td>`;
}

function historyRow(r) {
  const plan = r.advertised_download || r.advertised_upload
    ? `${formatPlan(r.advertised_download || null)} / ${formatPlan(r.advertised_upload || null)}`
    : "–";
  if (state.confirmingId === r.id) {
    return `
      <tr class="confirming">
        <td colspan="7">Delete the test from ${esc(fullFormat.format(r.time))}? This cannot be undone.</td>
        <td><div class="row-actions">
          <button class="button ghost" type="button" data-cancel-delete>Cancel</button>
          <button class="button danger solid" type="button" data-confirm-delete="${r.id}">Delete</button>
        </div></td>
      </tr>`;
  }
  return `
    <tr>
      <td>${esc(fullFormat.format(r.time))}</td>
      <td class="r">${formatSpeed(r.download)}</td>
      <td class="r">${formatSpeed(r.upload)}</td>
      <td class="r">${formatPing(r.ping)}</td>
      ${pctCell(r)}
      <td class="r ${plan === "–" ? "muted" : ""}">${plan}</td>
      <td class="muted">${esc(r.server_name ?? "")}</td>
      <td><div class="row-actions">
        <button class="button ghost icon-button" type="button" data-delete="${r.id}" aria-label="Delete test from ${esc(fullFormat.format(r.time))}" title="Delete">${ICONS.trash}</button>
      </div></td>
    </tr>`;
}

function exportCsv(rows) {
  const header = ["timestamp_utc", "download_mbps", "upload_mbps", "ping_ms", "advertised_download_mbps", "advertised_upload_mbps", "server"];
  const quote = (v) => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const lines = rows.map((r) => [r.timestamp, r.download, r.upload, r.ping, r.advertised_download, r.advertised_upload, r.server_name].map(quote).join(","));
  const blob = new Blob([[header.join(","), ...lines].join("\n")], { type: "text/csv" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `speedtests-${state.range}-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

async function renderHistory(isCurrent) {
  destroyCharts();
  if (!state.results || state.resultsRange !== state.range) {
    view.innerHTML = `<div class="view-head"><h1>History</h1>${rangeControl()}</div><div class="skeleton"></div>`;
  }
  const results = await loadResults();
  if (!isCurrent()) return;

  const head = `
    <div class="view-head">
      <h1>History</h1>
      <span class="toolbar-note">${results.length} ${results.length === 1 ? "test" : "tests"}</span>
      ${rangeControl()}
      <button class="button" type="button" data-action="export" ${results.length ? "" : "disabled"}>${ICONS.download}Export CSV</button>
    </div>`;

  if (!results.length) {
    view.innerHTML = head + emptyResults();
    bindRangeControl();
    bindEmpty();
    return;
  }

  const { key, dir } = state.historySort;
  const column = HISTORY_COLUMNS.find((c) => c.key === key) ?? HISTORY_COLUMNS[0];
  const sorted = [...results].sort((a, b) => {
    const va = column.value(a);
    const vb = column.value(b);
    return (va < vb ? -1 : va > vb ? 1 : 0) * dir;
  });
  const pageCount = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  state.historyPage = Math.min(state.historyPage, pageCount - 1);
  const start = state.historyPage * PAGE_SIZE;
  const page = sorted.slice(start, start + PAGE_SIZE);

  view.innerHTML = `
    ${head}
    <section class="panel">
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            ${HISTORY_COLUMNS.map((c) => {
              const active = c.key === key;
              const sortState = active ? (dir === 1 ? "ascending" : "descending") : "none";
              return `<th class="${c.align ?? ""}" aria-sort="${sortState}"><button class="sort" type="button" data-sort="${c.key}">${c.label}${c.unit ? ` <span class="subtle">${c.unit}</span>` : ""}<span class="arrow" aria-hidden="true">${active ? (dir === 1 ? "↑" : "↓") : ""}</span></button></th>`;
            }).join("")}
            <th><span class="visually-hidden">Actions</span></th>
          </tr></thead>
          <tbody>${page.map(historyRow).join("")}</tbody>
        </table>
      </div>
      <div class="pager">
        <span>${start + 1}–${start + page.length} of ${sorted.length}</span>
        <div class="pager-controls">
          <button class="button" type="button" data-page="-1" ${state.historyPage === 0 ? "disabled" : ""}>Previous</button>
          <span>Page ${state.historyPage + 1} of ${pageCount}</span>
          <button class="button" type="button" data-page="1" ${state.historyPage >= pageCount - 1 ? "disabled" : ""}>Next</button>
        </div>
      </div>
    </section>`;

  bindRangeControl();
  view.querySelector("[data-action=export]").addEventListener("click", () => exportCsv(results));
  view.querySelectorAll("[data-sort]").forEach((button) =>
    button.addEventListener("click", () => {
      const sortKey = button.dataset.sort;
      state.historySort = { key: sortKey, dir: state.historySort.key === sortKey ? -state.historySort.dir : -1 };
      state.historyPage = 0;
      renderHistory(isCurrent);
    }),
  );
  view.querySelectorAll("[data-page]").forEach((button) =>
    button.addEventListener("click", () => {
      state.historyPage += Number(button.dataset.page);
      state.confirmingId = null;
      renderHistory(isCurrent);
      window.scrollTo({ top: 0 });
    }),
  );
  view.querySelectorAll("[data-delete]").forEach((button) =>
    button.addEventListener("click", () => {
      state.confirmingId = Number(button.dataset.delete);
      renderHistory(isCurrent);
      view.querySelector("[data-confirm-delete]")?.focus();
    }),
  );
  view.querySelector("[data-cancel-delete]")?.addEventListener("click", () => {
    state.confirmingId = null;
    renderHistory(isCurrent);
  });
  view.querySelector("[data-confirm-delete]")?.addEventListener("click", async (event) => {
    const id = Number(event.currentTarget.dataset.confirmDelete);
    event.currentTarget.disabled = true;
    try {
      await api(`/history/${id}`, { method: "DELETE" });
      state.results = state.results.filter((r) => r.id !== id);
      state.confirmingId = null;
      toast("Test deleted.");
      refreshStatus();
    } catch (error) {
      toast(error.message, "error");
    }
    renderHistory(isCurrent);
  });
}

/* Reports */

function reportDialog(report, onSaved) {
  const editing = Boolean(report);
  const r = report ?? { name: "", recipient: "", schedule: "0 8 * * *", data_window: "last_day", enabled: true };
  const dialog = document.createElement("dialog");
  dialog.innerHTML = `
    <form method="dialog" novalidate>
      <header>
        <h2>${editing ? "Edit report" : "New report"}</h2>
        <p>A Telegram summary of your tests, sent on a schedule.</p>
      </header>
      <div class="dialog-body">
        <div class="field">
          <label for="r-name">Name</label>
          <input class="input" id="r-name" name="name" required value="${esc(r.name)}" placeholder="Daily summary" autocomplete="off">
        </div>
        <div class="field">
          <label for="r-recipient">Telegram chat ID</label>
          <input class="input" id="r-recipient" name="recipient" required value="${esc(r.recipient)}" inputmode="numeric" autocomplete="off">
          <span class="hint">The chat or group that receives the report. Message @userinfobot on Telegram to find yours.</span>
        </div>
        <div class="field">
          <label for="r-schedule">Schedule</label>
          <input class="input cron" id="r-schedule" name="schedule" required value="${esc(r.schedule)}" autocomplete="off" spellcheck="false">
          <div class="chips">${SCHEDULE_PRESETS.map((p) => `<button class="chip" type="button" data-cron="${p.cron}">${p.label}</button>`).join("")}</div>
          <span class="hint">Cron expression, evaluated in UTC.</span>
        </div>
        <div class="field">
          <label for="r-window">Data covered</label>
          <select class="input" id="r-window" name="data_window">
            ${Object.entries(DATA_WINDOWS).map(([value, label]) => `<option value="${value}" ${value === r.data_window ? "selected" : ""}>${label}</option>`).join("")}
          </select>
        </div>
        <label class="check"><input type="checkbox" name="enabled" ${r.enabled ? "checked" : ""}>Send this report</label>
      </div>
      <div class="form-actions">
        <span class="form-error" aria-live="polite"></span>
        <button class="button ghost" type="button" data-close>Cancel</button>
        <button class="button primary" type="submit">${editing ? "Save report" : "Create report"}</button>
      </div>
    </form>`;
  document.body.append(dialog);
  const form = dialog.querySelector("form");
  const errorEl = dialog.querySelector(".form-error");
  dialog.querySelectorAll("[data-cron]").forEach((chip) =>
    chip.addEventListener("click", () => {
      form.schedule.value = chip.dataset.cron;
    }),
  );
  dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => dialog.remove());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      name: form.name.value.trim(),
      recipient: form.recipient.value.trim(),
      schedule: form.schedule.value.trim(),
      data_window: form.data_window.value,
      enabled: form.enabled.checked,
      type: "telegram",
    };
    const missing = ["name", "recipient", "schedule"].find((k) => !payload[k]);
    if (missing) {
      errorEl.textContent = "Name, chat ID and schedule are required.";
      form[missing].focus();
      return;
    }
    const submit = form.querySelector("[type=submit]");
    submit.disabled = true;
    try {
      if (editing) await api(`/reports/${report.id}`, { method: "PUT", json: payload });
      else await api("/reports", { method: "POST", json: payload });
      dialog.close();
      toast(editing ? "Report saved." : "Report created.");
      onSaved();
    } catch (error) {
      errorEl.textContent = error.message;
      submit.disabled = false;
    }
  });
  dialog.showModal();
}

async function renderReports(isCurrent) {
  destroyCharts();
  const [reports, settings] = await Promise.all([api("/reports"), loadSettings(true)]);
  if (!isCurrent()) return;
  const tokenMissing = !settings.has_env_token && !settings.has_db_token;
  const rerender = () => renderReports(isCurrent);

  const notice = tokenMissing
    ? `<p class="notice notice-block">No Telegram bot token is configured, so reports will not be sent. Add one in <a href="#/settings">Settings</a> or set TELEGRAM_BOT_TOKEN in .env.</p>`
    : "";

  const body = reports.length
    ? `
      <section class="panel">
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>Name</th><th>Status</th><th>Chat ID</th><th>Schedule <span class="subtle">UTC</span></th><th>Data covered</th><th>Last sent</th><th>Next send</th><th></th></tr></thead>
            <tbody>
              ${reports.map((r) => state.confirmingId === `report-${r.id}`
                ? `<tr class="confirming"><td colspan="7">Delete the report “${esc(r.name)}”? It will stop being sent.</td>
                    <td><div class="row-actions"><button class="button ghost" type="button" data-cancel-delete>Cancel</button><button class="button danger solid" type="button" data-confirm-report="${r.id}">Delete</button></div></td></tr>`
                : `<tr>
                  <td class="row-label">${esc(r.name)}</td>
                  <td><span class="status-dot ${r.enabled ? "" : "off"}">${r.enabled ? "Active" : "Paused"}</span></td>
                  <td>${esc(r.recipient)}</td>
                  <td class="cron">${esc(r.schedule)}</td>
                  <td>${esc(DATA_WINDOWS[r.data_window] ?? r.data_window)}</td>
                  <td class="${r.last_run ? "" : "muted"}">${r.last_run ? formatWhen(new Date(r.last_run)) : "Never"}</td>
                  <td class="${r.next_run ? "" : "muted"}">${r.next_run ? formatWhen(new Date(r.next_run)) : "–"}</td>
                  <td><div class="row-actions">
                    <button class="button ghost icon-button" type="button" data-edit="${r.id}" aria-label="Edit ${esc(r.name)}" title="Edit">${ICONS.edit}</button>
                    <button class="button ghost icon-button" type="button" data-delete-report="${r.id}" aria-label="Delete ${esc(r.name)}" title="Delete">${ICONS.trash}</button>
                  </div></td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>
      </section>`
    : `
      <div class="panel empty">
        <h2>No reports yet</h2>
        <p>Create a report to get a summary of download, upload and latency on Telegram, daily or on any schedule.</p>
        <button class="button primary" type="button" data-action="new-report">New report</button>
      </div>`;

  view.innerHTML = `
    <div class="view-head">
      <h1>Reports</h1>
      ${reports.length ? '<button class="button primary" type="button" data-action="new-report">New report</button>' : ""}
    </div>
    ${notice}
    ${body}`;

  view.querySelectorAll("[data-action=new-report]").forEach((b) => b.addEventListener("click", () => reportDialog(null, rerender)));
  view.querySelectorAll("[data-edit]").forEach((b) =>
    b.addEventListener("click", () => reportDialog(reports.find((r) => r.id === Number(b.dataset.edit)), rerender)),
  );
  view.querySelectorAll("[data-delete-report]").forEach((b) =>
    b.addEventListener("click", () => {
      state.confirmingId = `report-${b.dataset.deleteReport}`;
      rerender();
    }),
  );
  view.querySelector("[data-cancel-delete]")?.addEventListener("click", () => {
    state.confirmingId = null;
    rerender();
  });
  const confirm = view.querySelector("[data-confirm-report]");
  confirm?.focus();
  confirm?.addEventListener("click", async () => {
    confirm.disabled = true;
    try {
      await api(`/reports/${confirm.dataset.confirmReport}`, { method: "DELETE" });
      toast("Report deleted.");
    } catch (error) {
      toast(error.message, "error");
    }
    state.confirmingId = null;
    rerender();
  });
}

/* Settings */

function deleteAllDialog(total, onDone) {
  const dialog = document.createElement("dialog");
  dialog.innerHTML = `
    <form method="dialog" novalidate>
      <header>
        <h2>Delete all test results</h2>
        <p>This permanently removes all ${total} recorded tests. Reports and settings are kept.</p>
      </header>
      <div class="dialog-body">
        <div class="field">
          <label for="confirm-text">Type <strong>delete</strong> to confirm</label>
          <input class="input" id="confirm-text" autocomplete="off" spellcheck="false">
        </div>
      </div>
      <div class="form-actions">
        <span class="form-error" aria-live="polite"></span>
        <button class="button ghost" type="button" data-close>Cancel</button>
        <button class="button danger solid" type="submit" disabled>Delete all results</button>
      </div>
    </form>`;
  document.body.append(dialog);
  const input = dialog.querySelector("#confirm-text");
  const submit = dialog.querySelector("[type=submit]");
  input.addEventListener("input", () => {
    submit.disabled = input.value.trim().toLowerCase() !== "delete";
  });
  dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => dialog.remove());
  dialog.querySelector("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      await api("/history/all", { method: "DELETE" });
      dialog.close();
      toast("All test results deleted.");
      onDone();
    } catch (error) {
      dialog.querySelector(".form-error").textContent = error.message;
      submit.disabled = false;
    }
  });
  dialog.showModal();
}

function themeChoice() {
  return document.documentElement.dataset.theme ?? "system";
}

async function renderSettings(isCurrent) {
  destroyCharts();
  const settings = await loadSettings(true);
  if (!isCurrent()) return;
  const total = state.status?.total_results ?? 0;

  const tokenField = settings.has_env_token
    ? `<p class="notice">The bot token is set by the TELEGRAM_BOT_TOKEN environment variable. Change it in .env and restart the backend.</p>`
    : `
      <div class="field">
        <label for="s-token">Bot token</label>
        <input class="input" id="s-token" name="telegram_bot_token" type="password" autocomplete="off" spellcheck="false"
          placeholder="${settings.has_db_token ? "A token is saved. Enter a new one to replace it." : "123456:ABC-DEF..."}">
        <span class="hint">Get one from @BotFather. Stored in the database; setting TELEGRAM_BOT_TOKEN in .env is safer.</span>
      </div>`;

  view.innerHTML = `
    <div class="view-head"><h1>Settings</h1></div>
    <div class="settings">
      <form class="panel" id="settings-form" novalidate>
        <section class="settings-section">
          <div><h2>Testing</h2><p>How often the backend measures your connection.</p></div>
          <div class="settings-fields">
            <div class="field">
              <label for="s-interval">Test every</label>
              <div class="input-unit"><input class="input" id="s-interval" name="speedtest_interval" type="number" min="1" step="1" required value="${esc(settings.speedtest_interval ?? 60)}"><span>minutes</span></div>
              <span class="hint">Each test downloads and uploads data for about 30 seconds.</span>
            </div>
          </div>
        </section>
        <section class="settings-section">
          <div><h2>Internet plan</h2><p>The speeds your ISP sells you. Each new test stores the plan in force, so changing it keeps history accurate.</p></div>
          <div class="settings-fields">
            <div class="field-row">
              <div class="field">
                <label for="s-down">Download</label>
                <div class="input-unit"><input class="input" id="s-down" name="advertised_download" type="number" min="0" step="any" value="${esc(Number(settings.advertised_download) || "")}" placeholder="0"><span>Mbps</span></div>
              </div>
              <div class="field">
                <label for="s-up">Upload</label>
                <div class="input-unit"><input class="input" id="s-up" name="advertised_upload" type="number" min="0" step="any" value="${esc(Number(settings.advertised_upload) || "")}" placeholder="0"><span>Mbps</span></div>
              </div>
            </div>
            <span class="hint">Leave empty to hide plan comparisons.</span>
          </div>
        </section>
        <section class="settings-section">
          <div><h2>Telegram</h2><p>The bot that sends your reports.</p></div>
          <div class="settings-fields">${tokenField}</div>
        </section>
        <div class="form-actions">
          <span class="form-error" aria-live="polite"></span>
          <button class="button primary" type="submit">Save settings</button>
        </div>
      </form>
      <section class="panel">
        <div class="settings-section">
          <div><h2>Appearance</h2><p>Stored in this browser only.</p></div>
          <div class="settings-fields">
            <div class="segmented start" role="group" aria-label="Theme">
              ${["system", "light", "dark"].map((t) => `<button type="button" data-theme-choice="${t}" aria-pressed="${themeChoice() === t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}
            </div>
          </div>
        </div>
        <div class="settings-section">
          <div><h2>Data</h2><p>${total} ${total === 1 ? "test" : "tests"} recorded.</p></div>
          <div class="settings-fields">
            <div class="button-row">
              <a class="button" href="/apidocs" target="_blank" rel="noopener">Open API docs</a>
              <button class="button danger" type="button" data-action="delete-all" ${total ? "" : "disabled"}>Delete all results</button>
            </div>
          </div>
        </div>
      </section>
    </div>`;

  const form = document.getElementById("settings-form");
  const errorEl = form.querySelector(".form-error");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.textContent = "";
    const interval = Number(form.speedtest_interval.value);
    if (!Number.isInteger(interval) || interval < 1) {
      errorEl.textContent = "Test interval must be a whole number of minutes, 1 or more.";
      form.speedtest_interval.focus();
      return;
    }
    const payload = {
      speedtest_interval: interval,
      advertised_download: Number(form.advertised_download.value) || 0,
      advertised_upload: Number(form.advertised_upload.value) || 0,
    };
    const token = form.telegram_bot_token?.value.trim();
    if (token) payload.telegram_bot_token = token;
    const submit = form.querySelector("[type=submit]");
    submit.disabled = true;
    try {
      await api("/settings", { method: "POST", json: payload });
      state.settings = null;
      toast("Settings saved.");
      await refreshStatus();
      renderSettings(isCurrent);
    } catch (error) {
      errorEl.textContent = error.message;
      submit.disabled = false;
    }
  });

  view.querySelectorAll("[data-theme-choice]").forEach((button) =>
    button.addEventListener("click", () => {
      const choice = button.dataset.themeChoice;
      if (choice === "system") delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = choice;
      writePref("theme", choice === "system" ? null : choice);
      view.querySelectorAll("[data-theme-choice]").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    }),
  );

  view.querySelector("[data-action=delete-all]").addEventListener("click", () =>
    deleteAllDialog(total, async () => {
      state.results = null;
      await refreshStatus();
      renderSettings(isCurrent);
    }),
  );
}

/* Boot */

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (currentView() === "dashboard") render();
});

new MutationObserver(() => {
  if (currentView() === "dashboard" && state.results) render();
}).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshStatus();
});

refreshStatus().then(render);
