# 🚀 Speedtest Logger

A fully containerized, automated internet performance monitor with a modern dashboard and Telegram reporting.

---

## ✨ Features

- **Automated Monitoring**: Scheduled speedtests (from 1 minute to any interval) using `fast-cli` (Fast.com powered by Netflix).
- **Modern Dashboard**: Dynamic, interactive charts built with **Streamlit** and **Plotly** (Dark Mode included).
- **Professional Reporting**: Modular reporting system with built-in **Telegram** notifications for 24-hour summaries.
- **Dynamic Configuration**: Change your test intervals directly from the web UI without restarting containers.
- **Privacy & Security**: Secure management of sensitive tokens using environment variables (`.env`).
- **Full API Documentation**: Interactive **Swagger UI** for developers at `/apidocs`.
- **Persistent Storage**: Data is safely stored in a local SQLite database that survives container restarts.

## 🛠️ Tech Stack

- **Language**: [Python 3.14.2+](https://www.python.org/)
- **Backend API**: [Flask](https://flask.palletsprojects.com/) + [SQLAlchemy](https://www.sqlalchemy.org/)
- **Frontend**: [Streamlit](https://streamlit.io/) + [Plotly](https://plotly.com/python/)
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

### 3. Launch with Docker
Use the included helper script to build and start the services:
```powershell
./update_and_restart.sh
```
*Manual alternative:* `docker compose up --build -d`

---

## 📊 Usage

### 🖥️ Dashboard
Access the interactive dashboard at:  
👉 [**http://localhost:8501**](http://localhost:8501)

- **Dashboard**: View latest stats and historical trends.
- **History**: Browse and sort every recorded speedtest.
- **Reports**: Set up your Telegram notifications.
- **Settings**: Adjust the test frequency (default 60 min).

### 🔌 API Documentation (Swagger)
For developers or integration:  
👉 [**http://localhost:5000/apidocs**](http://localhost:5000/apidocs)

### 🩺 Debugging
Check the real-time state of the background scheduler:  
👉 [**http://localhost:5000/api/debug/scheduler**](http://localhost:5000/api/debug/scheduler)

---

## 📁 Project Structure

```text
├── app.py                # Streamlit Dashboard (Frontend)
├── backend/
│   ├── api.py            # Flask REST API & Swagger UI
│   ├── database.py       # SQLAlchemy Connection & SQLite
│   └── models.py         # Database Schema
├── collector/
│   ├── scheduler.py      # Background APScheduler Logic
│   └── worker.py         # Speedtest Execution Logic
├── reporting/
│   ├── manager.py        # Report Dispatcher
│   └── providers/        # (e.g., Telegram)
├── Dockerfile            # Optimized uv-based multi-stage build
├── docker-compose.yml    # Service Orchestration
└── pyproject.toml        # uv Dependency Manifest
```

## 📜 License
This project is provided "as is" for monitoring personal home internet performance. Feel free to fork and expand!
