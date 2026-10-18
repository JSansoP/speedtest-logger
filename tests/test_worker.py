import subprocess
from types import SimpleNamespace

from backend.database import SessionLocal
from backend.models import SpeedTestResult
from collector import worker


def fake_run(stdout="", returncode=0, stderr=""):
    return lambda *args, **kwargs: SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


def stored_results():
    db = SessionLocal()
    try:
        return db.query(SpeedTestResult).all()
    finally:
        db.close()


def test_missing_fast_cli_returns_none(monkeypatch):
    def raise_missing(*args, **kwargs):
        raise FileNotFoundError("fast")

    monkeypatch.setattr(subprocess, "run", raise_missing)
    assert worker.run_speedtest() is None


def test_timeout_returns_none(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("fast", 180)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert worker.run_speedtest() is None


def test_failed_exit_code_returns_none(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run(returncode=1, stderr="boom"))
    assert worker.run_speedtest() is None
    assert stored_results() == []


def test_unparseable_output_returns_none(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run(stdout="no json here"))
    assert worker.run_speedtest() is None


def test_successful_run_stores_result_in_mbps(monkeypatch):
    output = '{"downloadSpeed": 1.2, "downloadUnit": "Gbps", "uploadSpeed": 50, "uploadUnit": "Mbps", "latency": 9}'
    monkeypatch.setattr(subprocess, "run", fake_run(stdout=output))
    result = worker.run_speedtest()
    assert result is not None
    [stored] = stored_results()
    assert stored.download == 1200.0
    assert stored.upload == 50.0
    assert stored.ping == 9.0
    assert stored.timestamp.tzinfo is None
