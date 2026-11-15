import subprocess
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import text

from backend.database import SessionLocal, engine, run_migrations
from backend.models import AppSettings, SpeedTestResult
from collector import worker

OUTPUT = '{"downloadSpeed": 10, "downloadUnit": "Mbps", "uploadSpeed": 5, "uploadUnit": "Mbps", "latency": 9}'


def run_fake_speedtest(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=OUTPUT, returncode=0, stderr="")
    )
    worker.run_speedtest()


def set_isp(client, name):
    return client.post("/api/settings", json={"isp_name": name})


def stored_isp_names():
    db = SessionLocal()
    try:
        return [r.isp_name for r in db.query(SpeedTestResult).order_by(SpeedTestResult.id)]
    finally:
        db.close()


def test_worker_stores_current_isp_name(client, monkeypatch):
    set_isp(client, "Movistar")
    run_fake_speedtest(monkeypatch)
    assert stored_isp_names() == ["Movistar"]


def test_worker_keeps_previous_name_after_isp_change(client, monkeypatch):
    set_isp(client, "ibred")
    run_fake_speedtest(monkeypatch)
    set_isp(client, "Movistar")
    run_fake_speedtest(monkeypatch)
    assert stored_isp_names() == ["ibred", "Movistar"]


def test_worker_stores_no_isp_when_unset(monkeypatch):
    run_fake_speedtest(monkeypatch)
    assert stored_isp_names() == [None]


def test_speedtests_endpoint_exposes_isp_name(client):
    db = SessionLocal()
    db.add(SpeedTestResult(timestamp=datetime(2026, 1, 1), download=1, upload=1, ping=1, isp_name="ibred"))
    db.commit()
    db.close()
    assert client.get("/api/speedtests").get_json()[0]["isp_name"] == "ibred"


def test_settings_roundtrip_trims_isp_name(client):
    assert set_isp(client, "  Movistar  ").status_code == 200
    assert client.get("/api/settings").get_json()["isp_name"] == "Movistar"


def test_settings_rejects_invalid_isp_name(client):
    assert set_isp(client, "   ").status_code == 400
    assert set_isp(client, "x" * 61).status_code == 400
    assert set_isp(client, 5).status_code == 400


def test_migration_backfills_existing_rows_and_seeds_setting():
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE speedtests"))
        conn.execute(text("CREATE TABLE speedtests (id INTEGER PRIMARY KEY, timestamp DATETIME, download FLOAT)"))
        conn.execute(text("INSERT INTO speedtests (timestamp, download) VALUES ('2026-01-01 00:00:00', 100)"))

    run_migrations()

    with engine.connect() as conn:
        assert conn.execute(text("SELECT isp_name FROM speedtests")).scalars().all() == ["ibred"]
    db = SessionLocal()
    try:
        assert db.query(AppSettings).filter_by(key="isp_name").one().value == "ibred"
    finally:
        db.close()


def test_migration_does_not_overwrite_existing_values():
    db = SessionLocal()
    db.add(AppSettings(key="isp_name", value="Movistar"))
    db.add(SpeedTestResult(timestamp=datetime(2026, 1, 1), download=1, upload=1, ping=1, isp_name=None))
    db.commit()
    db.close()

    run_migrations()

    db = SessionLocal()
    try:
        assert db.query(AppSettings).filter_by(key="isp_name").one().value == "Movistar"
        assert db.query(SpeedTestResult).one().isp_name is None
    finally:
        db.close()
