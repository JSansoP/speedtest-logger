const STATE_LABEL = { ok: "OK", degraded: "Degraded", down: "Down", unknown: "No data" };
const LAYER_LABEL = { lan: "LAN", isp: "ISP access", internet: "Internet", vpn: "VPN" };
const CHART_HEIGHT = 200;
const RAW_GAP_SECONDS = 180;
const HOURLY_GAP_SECONDS = 3 * 3600 + 60;
const MAX_TICKS = 2000;

function formatMs(value) {
  if (value == null || Number.isNaN(value)) return "–";
  return value >= 9.95 ? value.toFixed(0) : value.toFixed(1);
}

function formatLoss(value) {
  if (value == null || Number.isNaN(value)) return "–";
  if (value === 0) return "0%";
  return value < 10 ? `${value.toFixed(1)}%` : `${value.toFixed(0)}%`;
}

function formatDuration(ms) {
  const minutes = Math.max(1, Math.round(ms / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${String(minutes % 60).padStart(2, "0")} min`;
}

/* Dashboard view */

function diagnosisMarkup(ctx, diagnosis) {
  const severity = { ok: "ok", warning: "degraded", down: "down" }[diagnosis.severity] ?? "unknown";
  return `
    <article class="readout diagnosis">
      <h2 class="readout-label">Diagnosis</h2>
      <p class="state"><span class="dot ${severity}"></span>${ctx.esc(diagnosis.text)}</p>
      <p class="readout-sub">${ctx.esc(diagnosis.detail)}</p>
    </article>`;
}

function targetReadoutMarkup(ctx, t) {
  const sub = t.state === "unknown"
    ? "No recent measurement. The probe job may have stopped."
    : `Loss <strong>${formatLoss(t.loss_1h_pct)}</strong> over the last hour, jitter ${formatMs(t.jitter_ms)} ms.<br>24 h worst 5% above ${formatMs(t.p95_24h_ms)} ms.`;
  return `
    <article class="readout">
      <h2 class="readout-label"><span class="dot ${t.state}" title="${STATE_LABEL[t.state]}"></span>${ctx.esc(t.name)}</h2>
      <p class="readout-meta">${LAYER_LABEL[t.layer] ?? t.layer} · ${ctx.esc(t.host)}</p>
      <p class="readout-value"><span class="num">${formatMs(t.median_ms)}</span><span class="unit">ms</span></p>
      <p class="readout-sub">${sub}</p>
    </article>`;
}

function chartData(series, resolution) {
  const gap = resolution === "raw" ? RAW_GAP_SECONDS : HOURLY_GAP_SECONDS;
  const xs = [];
  const median = [];
  const low = [];
  const high = [];
  const loss = [];
  series.t.forEach((t, i) => {
    if (i > 0 && t - series.t[i - 1] > gap) {
      xs.push(series.t[i - 1] + gap / 2);
      median.push(null);
      low.push(null);
      high.push(null);
      loss.push(null);
    }
    xs.push(t);
    median.push(series.median[i]);
    low.push(series.min[i]);
    high.push(series.max[i]);
    loss.push(series.loss_pct[i] > 0 ? series.loss_pct[i] : null);
  });
  return [xs, median, low, high, loss];
}

function drawTestTicks(testTimes) {
  return (u) => {
    const { ctx: g } = u;
    const { top, width } = u.bbox;
    const dpr = devicePixelRatio || 1;
    g.save();
    g.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--ink-2").trim();
    g.globalAlpha = 0.6;
    g.lineWidth = dpr;
    g.beginPath();
    const visible = testTimes.filter((t) => t >= u.scales.x.min && t <= u.scales.x.max);
    if (visible.length * 6 * dpr <= width) {
      for (const t of visible) {
        const x = Math.round(u.valToPos(t, "x", true));
        g.moveTo(x, top);
        g.lineTo(x, top + 9 * dpr);
      }
    }
    g.stroke();
    g.restore();
  };
}

function makeLatencyChart(ctx, container, series, resolution, testTimes) {
  const color = ctx.cssVar("--ping");
  const bad = ctx.cssVar("--bad");
  const muted = ctx.cssVar("--muted");
  const line = ctx.cssVar("--line");
  const surface = ctx.cssVar("--surface");
  const font = `12px ${ctx.cssVar("--font")}`;
  const data = chartData(series, resolution);
  const axis = { stroke: muted, font, grid: { stroke: line, width: 1 }, ticks: { show: false } };
  const ms = (v) => `${formatMs(v)} ms`;
  const hidden = { stroke: "transparent", width: 0, points: { show: false }, spanGaps: false };
  const lo = resolution === "raw" ? "Min" : "Lowest";
  const hi = resolution === "raw" ? "Max" : "Highest";

  const plot = new uPlot(
    {
      width: container.clientWidth || 600,
      height: CHART_HEIGHT,
      padding: [12, 8, 0, 0],
      cursor: { points: { size: 9, width: 2, stroke: surface }, drag: { x: true, y: false } },
      scales: { x: { time: true }, y: { range: (u, min, max) => [0, ctx.niceCeil(Math.max(max, 1) * 1.1)] }, loss: { range: [0, 100] } },
      axes: [
        { ...axis, grid: { show: false }, space: 80, values: ctx.timeAxisValues },
        { ...axis, size: 52 },
      ],
      bands: [{ series: [3, 2], fill: `${color}26` }],
      legend: { live: true },
      hooks: {
        init: [
          (u) => {
            const markers = [color, muted, muted, bad];
            u.root.querySelectorAll(".u-legend .u-marker").forEach((marker, i) => {
              if (i > 0) marker.style.background = markers[i - 1];
            });
          },
        ],
        draw: [drawTestTicks(testTimes)],
      },
      series: [
        { label: "Time", value: (u, v, si, idx) => ctx.legendValue(u, v, si, idx, (t) => ctx.fullFormat.format(new Date(t * 1000))) },
        {
          label: "Median",
          stroke: color,
          width: 2,
          spanGaps: false,
          points: { show: data[0].length <= 72, size: 6, width: 2, stroke: surface, fill: color },
          value: (u, v, si, idx) => ctx.legendValue(u, v, si, idx, ms),
        },
        { label: lo, ...hidden, value: (u, v, si, idx) => ctx.legendValue(u, v, si, idx, ms) },
        { label: hi, ...hidden, value: (u, v, si, idx) => ctx.legendValue(u, v, si, idx, ms) },
        {
          label: "Loss",
          scale: "loss",
          paths: () => null,
          points: { show: true, size: 7, width: 0, fill: bad },
          value: (u, v, si, idx) => (idx == null ? "" : v == null ? "0%" : formatLoss(v)),
        },
      ],
    },
    data,
    container,
  );
  const observer = new ResizeObserver(() => {
    const width = container.clientWidth;
    if (width && width !== plot.width) plot.setSize({ width, height: CHART_HEIGHT });
  });
  observer.observe(container);
  ctx.state.charts.push({ plot, observer });
}

function outagesMarkup(ctx, outages) {
  if (!outages.length) {
    return `
      <section class="panel">
        <div class="panel-head"><h2>Outages</h2><p>An outage is every internet target losing all packets for two rounds in a row.</p></div>
        <p class="panel-empty">No outages recorded.</p>
      </section>`;
  }
  const rows = outages
    .map((o) => {
      const start = new Date(o.started_at);
      const end = o.ended_at ? new Date(o.ended_at) : null;
      return `
        <tr>
          <td>${ctx.formatWhen(start)}</td>
          <td>${end ? ctx.formatWhen(end) : '<span class="status-dot bad">Ongoing</span>'}</td>
          <td class="r">${formatDuration((end ?? new Date()) - start)}</td>
          <td>${ctx.esc(o.diagnosis || "–")}</td>
          <td class="${o.reported ? "" : "muted"}">${o.reported ? "Sent" : end ? "Pending" : "After recovery"}</td>
        </tr>`;
    })
    .join("");
  return `
    <section class="panel">
      <div class="panel-head"><h2>Outages</h2><p>Latest ${outages.length}. Telegram is told after the connection is back.</p></div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>Started</th><th>Ended</th><th class="r">Duration</th><th>Diagnosis</th><th>Telegram</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>`;
}

export async function renderLatency(ctx, isCurrent) {
  const { view, state, api, esc } = ctx;
  ctx.destroyCharts();
  view.innerHTML = `<div class="view-head"><h1>Latency</h1>${ctx.rangeControl()}</div><div class="skeleton"></div>`;

  const since = ctx.rangeSince(state.range) ?? new Date(0);
  const query = new URLSearchParams({ from: since.toISOString(), to: new Date().toISOString() });
  const [summary, latency, outages, results] = await Promise.all([
    api("/latency/summary"),
    api(`/latency?${query}`),
    api("/latency/outages"),
    ctx.loadResults(),
  ]);
  if (!isCurrent()) return;
  ctx.destroyCharts();

  const head = `
    <div class="view-head">
      <h1>Latency</h1>
      <span class="toolbar-note">${summary.targets.length} ${summary.targets.length === 1 ? "target" : "targets"}, one round per minute</span>
      ${ctx.rangeControl()}
    </div>`;

  if (!summary.targets.length) {
    view.innerHTML = `${head}
      <div class="panel empty">
        <h2>No latency targets</h2>
        <p>Add the router, your ISP gateway and a few internet hosts in Settings to see where problems start.</p>
        <a class="button primary" href="#/settings">Open settings</a>
      </div>`;
    ctx.bindRangeControl();
    return;
  }

  const byId = new Map(latency.targets.map((s) => [s.id, s]));
  const resolutionNote = latency.resolution === "raw" ? "One point per minute" : "Hourly rollups of the median";
  view.innerHTML = `
    ${head}
    <section class="readouts latency-readouts" aria-label="Current readings">
      ${diagnosisMarkup(ctx, summary.diagnosis)}
      ${summary.targets.map((t) => targetReadoutMarkup(ctx, t)).join("")}
    </section>
    <div class="strip-key chart-key" aria-hidden="true">
      <span><i class="key-line"></i>Median</span>
      <span><i class="key-band"></i>${latency.resolution === "raw" ? "Lowest to highest reply" : "Lowest to highest hourly median"}</span>
      <span><i class="key-loss"></i>Packet loss, higher means more lost</span>
      <span><i class="key-tick"></i>Speedtest run</span>
    </div>
    <div class="charts latency-charts">
      ${summary.targets
        .map(
          (t) => `
        <section class="panel">
          <div class="panel-head"><h2>${esc(t.name)}</h2><p>${LAYER_LABEL[t.layer] ?? t.layer}. ${resolutionNote}.</p></div>
          <div class="chart" id="latency-chart-${t.id}"></div>
        </section>`,
        )
        .join("")}
    </div>
    ${outagesMarkup(ctx, outages)}`;

  ctx.bindRangeControl();
  const testTimes = results.slice(-MAX_TICKS).map((r) => r.time.getTime() / 1000);
  for (const target of summary.targets) {
    const series = byId.get(target.id);
    const container = document.getElementById(`latency-chart-${target.id}`);
    if (!series || !series.t.length) {
      container.innerHTML = '<p class="panel-empty">No samples in this range.</p>';
      continue;
    }
    makeLatencyChart(ctx, container, series, latency.resolution, testTimes);
  }
}

/* Settings */

const NUMBER_FIELDS = [
  "latency_loss_pct",
  "latency_baseline_factor",
  "latency_min_excess_ms",
  "latency_state_rounds",
  "latency_outage_rounds",
  "latency_alert_loss_pct",
  "latency_alert_minutes",
  "latency_alert_cooldown_minutes",
];

function numberField(ctx, settings, name, label, unit, hint, step = "any") {
  return `
    <div class="field">
      <label for="s-${name}">${label}</label>
      <div class="input-unit"><input class="input" id="s-${name}" name="${name}" type="number" min="0" step="${step}" required value="${ctx.esc(Number(settings[name]))}"><span>${unit}</span></div>
      <span class="hint">${hint}</span>
    </div>`;
}

export function latencySettingsMarkup(ctx, settings) {
  return `
    <section class="settings-section">
      <div><h2>Latency states</h2><p>When a target counts as degraded. A target is down when its latest round loses every packet.</p></div>
      <div class="settings-fields">
        <div class="field-row">
          ${numberField(ctx, settings, "latency_loss_pct", "Loss above", "%", "Degraded when recent rounds lose more than this.")}
          ${numberField(ctx, settings, "latency_state_rounds", "Recent rounds", "rounds", "How many rounds are averaged.", "1")}
        </div>
        <div class="field-row">
          ${numberField(ctx, settings, "latency_baseline_factor", "Latency above", "× baseline", "Baseline is the median of the last 24 hours.")}
          ${numberField(ctx, settings, "latency_min_excess_ms", "and at least", "ms more", "Ignores small jumps on very fast links.")}
        </div>
      </div>
    </section>
    <section class="settings-section">
      <div><h2>Latency alerts</h2><p>Sent to the chats of your enabled Telegram reports. Outages are reported after the connection recovers.</p></div>
      <div class="settings-fields">
        <label class="check"><input type="checkbox" name="latency_alerts_enabled" ${Number(settings.latency_alerts_enabled) ? "checked" : ""}>Send outage and packet loss alerts</label>
        ${numberField(ctx, settings, "latency_outage_rounds", "Outage after", "rounds", "Consecutive rounds with 100% loss on every internet target.", "1")}
        <div class="field-row">
          ${numberField(ctx, settings, "latency_alert_loss_pct", "Loss alert above", "%", "Sustained loss on any target.")}
          ${numberField(ctx, settings, "latency_alert_minutes", "for at least", "minutes", "Length of the window.", "1")}
        </div>
        ${numberField(ctx, settings, "latency_alert_cooldown_minutes", "Wait between loss alerts", "minutes", "Avoids repeating the same alert.", "1")}
        <div class="field">
          <label for="s-report_timezone">Time zone for alerts</label>
          <input class="input" id="s-report_timezone" name="report_timezone" required value="${ctx.esc(settings.report_timezone)}" autocomplete="off" spellcheck="false">
          <span class="hint">IANA name, for example Europe/Madrid.</span>
        </div>
      </div>
    </section>`;
}

export function readLatencySettings(form) {
  const payload = {};
  for (const name of NUMBER_FIELDS) payload[name] = Number(form[name].value);
  payload.latency_alerts_enabled = form.latency_alerts_enabled.checked ? 1 : 0;
  payload.report_timezone = form.report_timezone.value.trim();
  return payload;
}

export function targetsPanelMarkup(ctx, targets) {
  const { esc, state } = ctx;
  if (!targets.length) {
    return `
      <section class="panel">
        <div class="settings-section">
          <div><h2>Latency targets</h2><p>Hosts pinged every minute.</p></div>
          <div class="settings-fields"><div><p class="notice">No targets. Add your router, your ISP gateway and a couple of internet hosts.</p></div>
            <div class="button-row"><button class="button" type="button" data-action="new-target">Add target</button></div></div>
        </div>
      </section>`;
  }
  const rows = targets
    .map((t) =>
      state.confirmingId === `target-${t.id}`
        ? `<tr class="confirming"><td colspan="4">Delete ${esc(t.name)} and all its samples? This cannot be undone.</td>
            <td><div class="row-actions"><button class="button ghost" type="button" data-cancel-delete>Cancel</button><button class="button danger solid" type="button" data-confirm-target="${t.id}">Delete</button></div></td></tr>`
        : `<tr>
            <td class="row-label">${esc(t.name)}</td>
            <td>${LAYER_LABEL[t.layer] ?? esc(t.layer)}</td>
            <td>${esc(t.host)}</td>
            <td><span class="status-dot ${t.enabled ? "" : "off"}">${t.enabled ? "Active" : "Paused"}</span></td>
            <td><div class="row-actions">
              <button class="button ghost icon-button" type="button" data-edit-target="${t.id}" aria-label="Edit ${esc(t.name)}" title="Edit">${ctx.ICONS.edit}</button>
              <button class="button ghost icon-button" type="button" data-delete-target="${t.id}" aria-label="Delete ${esc(t.name)}" title="Delete">${ctx.ICONS.trash}</button>
            </div></td>
          </tr>`,
    )
    .join("");
  return `
    <section class="panel">
      <div class="panel-head"><h2>Latency targets</h2><p>Pinged every minute. The layer drives the diagnosis.</p>
        <button class="button push" type="button" data-action="new-target">Add target</button></div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>Name</th><th>Layer</th><th>Host</th><th>Status</th><th></th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>`;
}

function targetDialog(ctx, target, onSaved) {
  const { esc, api, toast } = ctx;
  const editing = Boolean(target);
  const t = target ?? { name: "", host: "", layer: "internet", enabled: true };
  const dialog = document.createElement("dialog");
  dialog.innerHTML = `
    <form method="dialog" novalidate>
      <header>
        <h2>${editing ? "Edit target" : "New target"}</h2>
        <p>A host that is pinged every minute with ICMP echo requests.</p>
      </header>
      <div class="dialog-body">
        <div class="field">
          <label for="t-name">Name</label>
          <input class="input" id="t-name" name="name" required value="${esc(t.name)}" placeholder="Router" autocomplete="off">
        </div>
        <div class="field">
          <label for="t-host">Host</label>
          <input class="input" id="t-host" name="host" required value="${esc(t.host)}" placeholder="192.168.50.1" autocomplete="off" spellcheck="false">
          <span class="hint">IP address or host name.</span>
        </div>
        <div class="field">
          <label for="t-layer">Layer</label>
          <select class="input" id="t-layer" name="layer">
            ${Object.entries(LAYER_LABEL).map(([value, label]) => `<option value="${value}" ${value === t.layer ? "selected" : ""}>${label}</option>`).join("")}
          </select>
          <span class="hint">LAN is your router, ISP access is the first hop beyond it, Internet is far away hosts, VPN is a WireGuard peer.</span>
        </div>
        <label class="check"><input type="checkbox" name="enabled" ${t.enabled ? "checked" : ""}>Probe this target</label>
      </div>
      <div class="form-actions">
        <span class="form-error" aria-live="polite"></span>
        <button class="button ghost" type="button" data-close>Cancel</button>
        <button class="button primary" type="submit">${editing ? "Save target" : "Add target"}</button>
      </div>
    </form>`;
  document.body.append(dialog);
  const form = dialog.querySelector("form");
  const errorEl = dialog.querySelector(".form-error");
  dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => dialog.remove());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      name: form.name.value.trim(),
      host: form.host.value.trim(),
      layer: form.layer.value,
      enabled: form.enabled.checked,
    };
    const missing = ["name", "host"].find((k) => !payload[k]);
    if (missing) {
      errorEl.textContent = "Name and host are required.";
      form[missing].focus();
      return;
    }
    const submit = form.querySelector("[type=submit]");
    submit.disabled = true;
    try {
      if (editing) await api(`/latency/targets/${target.id}`, { method: "PUT", json: payload });
      else await api("/latency/targets", { method: "POST", json: payload });
      dialog.close();
      toast(editing ? "Target saved." : "Target added.");
      onSaved();
    } catch (error) {
      errorEl.textContent = error.message;
      submit.disabled = false;
    }
  });
  dialog.showModal();
}

export function bindTargetsPanel(ctx, targets, rerender) {
  const { view, state } = ctx;
  view.querySelectorAll("[data-action=new-target]").forEach((b) => b.addEventListener("click", () => targetDialog(ctx, null, rerender)));
  view.querySelectorAll("[data-edit-target]").forEach((b) =>
    b.addEventListener("click", () => targetDialog(ctx, targets.find((t) => t.id === Number(b.dataset.editTarget)), rerender)),
  );
  view.querySelectorAll("[data-delete-target]").forEach((b) =>
    b.addEventListener("click", () => {
      state.confirmingId = `target-${b.dataset.deleteTarget}`;
      rerender();
    }),
  );
  view.querySelector("[data-cancel-delete]")?.addEventListener("click", () => {
    state.confirmingId = null;
    rerender();
  });
  const confirm = view.querySelector("[data-confirm-target]");
  confirm?.focus();
  confirm?.addEventListener("click", async () => {
    confirm.disabled = true;
    try {
      await ctx.api(`/latency/targets/${confirm.dataset.confirmTarget}`, { method: "DELETE" });
      ctx.toast("Target deleted.");
    } catch (error) {
      ctx.toast(error.message, "error");
    }
    state.confirmingId = null;
    rerender();
  });
}
