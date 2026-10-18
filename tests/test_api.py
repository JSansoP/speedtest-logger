from datetime import datetime, timedelta

import pytest

from backend.database import SessionLocal
from backend.models import AppSettings, SpeedTestResult
from collector import worker


def add_result(timestamp: datetime, download: float = 100.0) -> None:
    db = SessionLocal()
    db.add(SpeedTestResult(timestamp=timestamp, download=download, upload=10.0, ping=12.0, server_name="Fast.com"))
    db.commit()
    db.close()


def test_index_serves_frontend(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"<html" in response.data


def test_static_assets_are_served(client):
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/vendor/uPlot.iife.min.js").status_code == 200


def test_static_rejects_path_traversal(client):
    assert client.get("/static/../backend/api.py").status_code == 404


def test_speedtests_timestamps_include_utc_offset(client):
    add_result(datetime(2026, 1, 1, 12, 0))
    body = client.get("/api/speedtests").get_json()
    assert body[0]["timestamp"] == "2026-01-01T12:00:00+00:00"


def test_speedtests_since_filters_older_results(client):
    now = datetime(2026, 1, 10, 12, 0)
    add_result(now - timedelta(days=3), download=1.0)
    add_result(now - timedelta(hours=2), download=2.0)
    body = client.get("/api/speedtests?since=2026-01-10T00:00:00Z&limit=0").get_json()
    assert [r["download"] for r in body] == [2.0]


def test_speedtests_since_converts_offsets_to_utc(client):
    add_result(datetime(2026, 1, 10, 11, 30))
    body = client.get("/api/speedtests?since=2026-01-10T13:00:00%2B02:00").get_json()
    assert len(body) == 1


def test_speedtests_limit_zero_returns_all(client):
    base = datetime(2026, 1, 1)
    for i in range(120):
        add_result(base + timedelta(minutes=i))
    assert len(client.get("/api/speedtests").get_json()) == 100
    assert len(client.get("/api/speedtests?limit=0").get_json()) == 120


def test_speedtests_rejects_invalid_since(client):
    assert client.get("/api/speedtests?since=yesterday").status_code == 400


def test_status_reports_totals(client):
    add_result(datetime(2026, 1, 1, 8, 0))
    add_result(datetime(2026, 1, 2, 9, 0))
    body = client.get("/api/status").get_json()
    assert body["total_results"] == 2
    assert body["last_result_at"] == "2026-01-02T09:00:00+00:00"
    assert body["running"] is False
    assert body["interval_minutes"] == 60


def test_status_with_no_results(client):
    body = client.get("/api/status").get_json()
    assert body["total_results"] == 0
    assert body["last_result_at"] is None


def test_run_returns_conflict_while_running(client, monkeypatch):
    monkeypatch.setattr(worker, "_run_speedtest", lambda: None)
    assert worker._run_lock.acquire(blocking=False)
    try:
        assert client.post("/api/speedtests/run").status_code == 409
    finally:
        worker._run_lock.release()


def test_run_starts_background_test(client, monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "_run_speedtest", lambda: calls.append(1))
    assert client.post("/api/speedtests/run").status_code == 202
    worker._run_lock.acquire(timeout=2)
    worker._run_lock.release()
    assert calls == [1]


def test_scheduled_run_skips_when_already_running(monkeypatch):
    monkeypatch.setattr(worker, "_run_speedtest", lambda: pytest.fail("should not run"))
    worker._run_lock.acquire()
    try:
        assert worker.run_speedtest() is None
    finally:
        worker._run_lock.release()


def valid_report(**overrides):
    payload = {"name": "Daily", "schedule": "0 8 * * *", "recipient": "123", "data_window": "last_day"}
    payload.update(overrides)
    return payload


def test_create_and_list_report(client):
    assert client.post("/api/reports", json=valid_report()).status_code == 201
    reports = client.get("/api/reports").get_json()
    assert reports[0]["name"] == "Daily"
    assert reports[0]["next_run"] is not None


def test_create_report_rejects_invalid_cron(client):
    response = client.post("/api/reports", json=valid_report(schedule="every day"))
    assert response.status_code == 400
    assert "cron" in response.get_json()["error"]


def test_create_report_rejects_missing_fields(client):
    response = client.post("/api/reports", json={"name": "x"})
    assert response.status_code == 400


def test_create_report_rejects_duplicate_name(client):
    client.post("/api/reports", json=valid_report())
    assert client.post("/api/reports", json=valid_report()).status_code == 409


def test_update_report_rejects_invalid_window(client):
    client.post("/api/reports", json=valid_report())
    report_id = client.get("/api/reports").get_json()[0]["id"]
    assert client.put(f"/api/reports/{report_id}", json={"data_window": "forever"}).status_code == 400


def test_disabled_report_has_no_next_run(client):
    client.post("/api/reports", json=valid_report(enabled=False))
    assert client.get("/api/reports").get_json()[0]["next_run"] is None


def test_settings_never_expose_stored_token(client):
    db = SessionLocal()
    db.add(AppSettings(key="telegram_bot_token", value="secret"))
    db.commit()
    db.close()
    body = client.get("/api/settings").get_json()
    assert "telegram_bot_token" not in body
    assert body["has_db_token"] is True
    assert body["has_env_token"] is False


def test_settings_rejects_invalid_interval(client):
    assert client.post("/api/settings", json={"speedtest_interval": 0}).status_code == 400
    assert client.post("/api/settings", json={"speedtest_interval": "abc"}).status_code == 400


def test_settings_rejects_negative_advertised_speed(client):
    assert client.post("/api/settings", json={"advertised_download": -5}).status_code == 400


def test_settings_saves_values(client):
    response = client.post("/api/settings", json={"advertised_download": 600, "advertised_upload": 60})
    assert response.status_code == 200
    body = client.get("/api/settings").get_json()
    assert float(body["advertised_download"]) == 600
