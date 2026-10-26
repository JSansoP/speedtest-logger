# 🚀 Speedtest Logger

A fully containerized, automated internet performance monitor with a modern dashboard and Telegram reporting.

---

## ✨ Features

- **Automated Monitoring**: Scheduled speedtests (from 1 minute to any interval) using `fast-cli` (Fast.com powered by Netflix).
- **Latency Monitor**: SmokePing-style probing every minute (ICMP, 10 pings per target) of your router, ISP gateway and internet hosts. Tracks latency, jitter and packet loss, shows latency under load during speedtests, diagnoses where a problem is (LAN, ISP access line, upstream, one destination) and reports outages on Telegram after the connection recovers.
- **Fast Dashboard**: Lightweight web UI served by the backend itself, with plan-vs-actual readouts, interactive charts, light and dark themes, and CSV export.
- **Professional Reporting**: Modular reporting system with built-in **Telegram** notifications for 24-hour summaries.
- **Dynamic Configuration**: Change your test intervals directly from the web UI without restarting containers.
- **Privacy & Security**: Secure management of sensitive tokens using environment variables (`.env`).
- **Full API Documentation**: Interactive **Swagger UI** for developers at `/apidocs`.
- **Persistent Storage**: Data is safely stored in a local SQLite database that survives container restarts.

## 🛠️ Tech Stack

- **Language**: [Python 3.14.2+](https://www.python.org/)
- **Backend API**: [Flask](https://flask.palletsprojects.com/) + [SQLAlchemy](https://www.sqlalchemy.org/)
- **Frontend**: Plain HTML, CSS and JavaScript (no build step) with [uPlot](https://github.com/leeoniya/uPlot) for charts
- **Scheduling**: [APScheduler](https://apscheduler.readthedocs.io/)
- **Package Manager**: [uv](https://github.com/astral-sh/uv) (Extremely fast, deterministic builds)
- **Containerization**: [Docker](https://www.docker.com/) & [Docker Compose](https://docs.docker.com/compose/)

---

## 🚀 Quick Start

### 1. Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

### 2. Configure Environment
Copy the example environment file and add your Telegram bot token:
```powershell
cp .env.example .env
```
Edit `.env`:
```env
TELEGRAM_BOT_TOKEN=your_token_from_botfather
```

Optional: set `HEARTBEAT_URL` to a [heartbeat-monitor](https://github.com/JSansoP/heartbeat-monitor) ping URL (for example `http://10.8.0.1/heartbeat/ping/speedtest`, the VPS over WireGuard). After every speedtest the backend pings it, or `<url>/fail` when the test errors. Pings use a 5 s timeout and failures are only logged, so the speedtest never depends on the monitor.

### 3. Launch with Docker
Use the included helper script to build and start the services:
```powershell
./update_and_restart.sh
```
*Manual alternative:* `docker compose up --build -d`

---

## 📊 Usage

### 🖥️ Dashboard
Access the dashboard at:  
👉 [**http://localhost:5000**](http://localhost:5000)

- **Dashboard**: View latest stats and historical trends.
- **History**: Browse and sort every recorded speedtest.
- **Reports**: Set up your Telegram notifications.
- **Latency**: Per-target readouts, a diagnosis, one chart per target (median line, min-max band, loss markers, speedtest runs) and the outage list.
- **Settings**: Adjust the test frequency (default 60 min), latency thresholds and alerts, and manage the latency targets.

### 📡 Latency monitor
Targets are stored in the database and edited in Settings. Defaults, created on first start: Router `192.168.50.1` (LAN), ISP gateway `5.180.229.90` (ISP access), Cloudflare `1.1.1.1` and Google `8.8.8.8` (internet), VPS `10.8.0.1` (VPN, the WireGuard hub). Change them to match your network. To find your ISP gateway, run a traceroute from the container and pick the first hop beyond the router that answers pings.

- Probing needs raw ICMP sockets: the container runs as root with the default Docker `NET_RAW` capability, nothing else to configure.
- Raw samples are kept for 90 days, hourly rollups forever.
- Outage reports and sustained packet loss alerts go to the chats of your enabled Telegram reports. An outage is two consecutive rounds with 100% loss on every internet target; the message is sent after recovery. Thresholds are in Settings.
- Endpoints: `/api/latency`, `/api/latency/summary`, `/api/latency/outages`, `/api/latency/targets` (see `/apidocs`).

### Serving under a subpath (e.g. `http://pi-nas/speedtest/`)
The UI uses relative URLs and honors `X-Forwarded-Prefix`, so it can sit behind a reverse proxy at any path.
For openMediaVault, copy the included nginx snippet into OMV's custom include folder:
```bash
sudo cp deploy/nginx/speedtest.conf /etc/nginx/openmediavault-webgui.d/
sudo nginx -t && sudo systemctl reload nginx
```
OMV regenerates its own nginx config but keeps files in that folder.

### 🔌 API Documentation (Swagger)
For developers or integration:  
👉 [**http://localhost:5000/apidocs**](http://localhost:5000/apidocs)

### 🩺 Debugging
Check the real-time state of the background scheduler:  
👉 [**http://localhost:5000/api/debug/scheduler**](http://localhost:5000/api/debug/scheduler)

---

## 📁 Project Structure

```text
├── frontend/             # Web UI (index.html, app.js, app.css, vendored uPlot and font)
├── backend/
│   ├── api.py            # Flask REST API & Swagger UI
│   ├── latency.py        # Latency settings, states, diagnosis, summary
│   ├── latency_api.py    # /api/latency endpoints
│   ├── database.py       # SQLAlchemy Connection & SQLite
│   └── models.py         # Database Schema
├── collector/
│   ├── heartbeat.py      # Optional pings to heartbeat-monitor
│   ├── latency.py        # Probe rounds, rollups, outage tracking, alerts
│   ├── probe.py          # ICMP probing layer (icmplib)
│   ├── scheduler.py      # Background APScheduler Logic
│   └── worker.py         # Speedtest Execution Logic
├── reporting/
│   ├── alerts.py         # Telegram outage and packet loss alerts
│   ├── manager.py        # Report Dispatcher
│   └── providers/        # (e.g., Telegram)
├── CLAUDE.md             # Architecture notes and design decisions
├── Dockerfile            # Optimized uv-based multi-stage build
├── docker-compose.yml    # Service Orchestration
└── pyproject.toml        # uv Dependency Manifest
```

## 📜 License
This project is provided "as is" for monitoring personal home internet performance. Feel free to fork and expand!

## 🧪 Development
```powershell
uv sync
uv run pytest
uv run ruff check .
```
