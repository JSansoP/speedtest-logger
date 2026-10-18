import asyncio
from datetime import timedelta

from backend.database import SessionLocal
from backend.models import AppSettings, LatencyOutage, LatencySample, LatencyTarget, ReportConfig, SpeedTestResult
from collector.latency import utcnow
from reporting import manager


def test_report_includes_latency_and_outages(monkeypatch):
    sent = []

    async def fake_send(token, chat, message):
        sent.append(message)

    monkeypatch.setattr(manager, "send_telegram_message", fake_send)
    db = SessionLocal()
    now = utcnow()
    router = LatencyTarget(name="Home_Router", host="192.168.50.1", layer="lan")
    db.add_all([router, AppSettings(key="telegram_bot_token", value="tok")])
    db.add(ReportConfig(name="daily", schedule="0 8 * * *", recipient="1", data_window="last_day"))
    db.add(
        SpeedTestResult(
            download=30, upload=5, ping=12, server_name="s", server_id="1", loaded_latency=80.0, timestamp=now
        )
    )
    db.commit()
    for minute in range(4):
        db.add(
            LatencySample(
                target_id=router.id,
                timestamp=now - timedelta(minutes=minute),
                sent=10,
                received=10,
                median_ms=2.0,
                under_load=False,
            )
        )
    db.add(LatencyOutage(started_at=now - timedelta(hours=3), ended_at=now - timedelta(hours=3) + timedelta(minutes=5)))
    db.commit()
    db.close()

    asyncio.run(manager.run_reports())

    [message] = sent
    assert "Under load: Med: 80.0" in message
    assert "Latency and loss" in message
    assert r"Home\_Router: Med 2.0 ms" in message
    assert "Loss 0.00%" in message
    assert "Outages: 1  ·  Total downtime: 5 min" in message
