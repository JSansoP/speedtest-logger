# Speedtest Logger

Self-hosted internet monitor: scheduled bandwidth tests plus a continuous latency and packet loss monitor, a web dashboard and Telegram reports.

## Stack

Python 3.14, uv, Flask + SQLAlchemy (SQLite), APScheduler, flasgger (Swagger at `/apidocs`), plain HTML/CSS/JS frontend with uPlot (no build step, vendored), icmplib for ICMP. Lint with `uv run ruff check`, test with `uv run pytest`.

## Architecture

- `main.py` creates tables, runs `run_migrations()`, seeds default latency targets, starts the APScheduler `BackgroundScheduler` and Flask (port 5000) in one process.
- `collector/worker.py`: runs `fast-cli`, stores a `SpeedTestResult`. A lock exposes `is_running()`. While the test runs, `probe.LoadSampler` pings 1.1.1.1 in a thread and the median is stored as `loaded_latency`.
- `collector/probe.py`: the only module that touches the network for ICMP (`probe_hosts`, `LoadSampler`) plus `summarize()`. Tests monkeypatch it; `tests/conftest.py` blocks `ping` and `async_multiping` for every test.
- `collector/latency.py`: jobs and state machines. `run_latency_round` (every 60 s, `max_instances=1`, `coalesce=True`), `run_latency_maintenance` (hourly at minute 5: hourly rollup plus 90 day raw prune), outage tracking, degradation alerts, `window_stats` for reports.
- `backend/latency.py`: pure logic and queries: settings with defaults, per-target state, `diagnose()` rules, summary payload.
- `backend/latency_api.py`: Flask blueprint for `/api/latency*`. `backend/api.py` holds the rest. `backend/timeutil.py` has the UTC helpers shared by both.
- `reporting/manager.py` builds scheduled Telegram reports (includes latency and outage stats). `reporting/alerts.py` sends outage and degradation alerts and resolves the bot token (env first, then DB).
- Frontend: `frontend/app.js` (router, dashboard, history, reports, settings), `frontend/latency.js` (latency view, target management, latency settings; receives helpers through a context object to avoid circular imports).

## Latency monitor design

- Each round pings every enabled target concurrently: 10 ICMP echoes at 0.5 s with a 2 s timeout. One `latency_samples` row per target per round with sent, received, min, median, avg, max, jitter (mean absolute difference of consecutive RTTs) and `under_load` (a speedtest was running during the round).
- Tables: `latency_targets`, `latency_samples` (index `(target_id, timestamp)`), `latency_hourly` (min/median/avg/max/p95 of the round medians, loss %, sample count), `latency_outages`. Timestamps are naive UTC like the rest of the DB.
- The rollup runs hourly instead of daily so ranges over 7 days include recent hours. It only aggregates completed hours that have no rollup yet; pruning deletes raw rows older than 90 days. Hourly rows are kept forever.
- Default targets are seeded once (flag `latency_targets_seeded` in `app_settings`, so deleting them does not bring them back): Router 192.168.50.1 (lan), ISP gateway 5.180.229.90 (isp), Cloudflare 1.1.1.1 and Google 8.8.8.8 (internet), VPS 10.8.0.1 (vpn, the WireGuard hub). Rows created with the old `tailnet` layer are renamed to `vpn` by `run_migrations()`.
- The ISP gateway is the first hop beyond the router that answers ICMP echo (found with traceroute on 2026-10-18). The earlier private hops (10.0.90.11 and following) only answer TTL-exceeded and show 100% loss when pinged directly.
- Target state: `unknown` without a sample in the last 3 minutes, `down` when the latest round lost every packet, `degraded` when loss over the last N rounds exceeds the threshold or the median exceeds baseline times a factor and a minimum absolute excess. Baseline is the 24 h median of unloaded round medians. All thresholds live in `app_settings` (`latency_*` keys, defaults in `backend/latency.py`).
- Diagnosis (`diagnose`): LAN target bad means LAN/router; else ISP target bad means access line; else all internet targets bad (two or more) means upstream; else some internet target bad means that destination only; else vpn bad means VPN/VPS.
- Outage: N consecutive rounds (`latency_outage_rounds`, default 2) with zero replies on every enabled internet target opens a `latency_outages` row and updates its diagnosis each round. The first round with replies closes it and `report_pending_outages` sends the Telegram message after recovery; unsent outages are retried every round for 24 hours.
- Degradation alert: loss over `latency_alert_minutes` above `latency_alert_loss_pct` on any target (window at least 80% filled, no open outage) with a global cooldown stored in `app_settings`.
- Alerts go to the recipients of all enabled Telegram report configs; there is no separate chat setting. Times use `report_timezone` (default Europe/Madrid, needs the `tzdata` package in the slim image).
- `/api/latency/summary` is read by the home-dashboard `latency` adapter (`targets[].state`, `targets[].median_ms`, `diagnosis.text`). Keep that shape stable.
- `/api/latency` returns columns of equal length with epoch-second `t`; raw samples up to 7 days, hourly rollups beyond, and reports the resolution used.

- Every page's top bar starts with a `.home-link` back to `http://personal-vps/home/` (absolute URL, because this UI is served from a different host than some of the other dashboards). Keep it when editing the top bar.

## Deployment

`HEARTBEAT_URL` uses the VPS WireGuard IP (`http://10.8.0.1/heartbeat/ping/speedtest`), not the `personal-vps` name: the container resolves through Docker DNS and the Pi has no entry for that name.

Docker Compose service `backend` (container `speedtest-backend`, bridge network, port 5000, image `ghcr.io/jsansop/speedtest-logger:latest`, data volume `/app/data`) on the Pi (`sanso@pi-nas`). GitHub Actions builds the image on push to main; `update_and_restart.sh` pulls and restarts it. Served at `http://pi-nas/speedtest/` through OMV nginx (`deploy/nginx/speedtest.conf`, `X-Forwarded-Prefix` with `ProxyFix`); the UI uses relative URLs.

## Pitfalls

- ICMP needs raw sockets: the container runs as root with the default Docker `NET_RAW`, which works from the bridge network including the VPS over WireGuard (Docker masquerades the bridge traffic leaving through `wg0`). `ping` and `traceroute` binaries are not installed; use icmplib (`icmplib.traceroute` works).
- Never hit the network in tests; `tests/conftest.py` makes any real probe raise.
- Telegram messages use legacy Markdown: escape user-defined names (`reporting.alerts.escape_markdown`).
- Change settings only through `/api/settings`; latency keys are validated in `backend/latency.py`.
- Heartbeat pings (`collector/heartbeat.py`) must never break or slow a speedtest.
