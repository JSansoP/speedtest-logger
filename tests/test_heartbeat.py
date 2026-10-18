import subprocess
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector import heartbeat, worker

URL = "http://personal-vps/heartbeat/ping/speedtest"
GOOD_OUTPUT = '{"downloadSpeed": 600, "downloadUnit": "Mbps", "uploadSpeed": 50, "uploadUnit": "Mbps", "latency": 9}'


@pytest.fixture
def urlopen(monkeypatch):
    response = MagicMock(status=200)
    response.__enter__.return_value = response
    mock = MagicMock(return_value=response)
    monkeypatch.setattr(heartbeat.urllib.request, "urlopen", mock)
    return mock


def test_disabled_without_url(urlopen):
    assert heartbeat.send() is False
    urlopen.assert_not_called()


def test_success_and_fail_urls(monkeypatch, urlopen):
    monkeypatch.setenv("HEARTBEAT_URL", URL + "/")
    assert heartbeat.send() is True
    assert heartbeat.send("fail") is True
    assert [c.args[0] for c in urlopen.call_args_list] == [URL, URL + "/fail"]
    assert all(c.kwargs["timeout"] == 5 for c in urlopen.call_args_list)


@pytest.mark.parametrize("error", [urllib.error.URLError("refused"), TimeoutError("timed out"), ValueError("bad url")])
def test_errors_are_swallowed(monkeypatch, error, caplog):
    monkeypatch.setenv("HEARTBEAT_URL", URL)
    monkeypatch.setattr(heartbeat.urllib.request, "urlopen", MagicMock(side_effect=error))
    assert heartbeat.send() is False
    assert "Heartbeat success failed" in caplog.text


def test_successful_speedtest_pings_success(monkeypatch):
    sent = []
    monkeypatch.setattr(heartbeat, "send", lambda suffix="": sent.append(suffix))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=GOOD_OUTPUT, returncode=0, stderr=""))
    assert worker.run_speedtest() is not None
    assert sent == [""]


def test_failed_speedtest_pings_fail(monkeypatch):
    sent = []
    monkeypatch.setattr(heartbeat, "send", lambda suffix="": sent.append(suffix))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="", returncode=1, stderr="boom"))
    assert worker.run_speedtest() is None
    assert sent == ["fail"]


def test_unreachable_monitor_does_not_break_the_speedtest(monkeypatch):
    monkeypatch.setenv("HEARTBEAT_URL", URL)
    monkeypatch.setattr(heartbeat.urllib.request, "urlopen", MagicMock(side_effect=urllib.error.URLError("down")))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=GOOD_OUTPUT, returncode=0, stderr=""))
    assert worker.run_speedtest() is not None
