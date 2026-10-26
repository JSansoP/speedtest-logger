import time
from datetime import timedelta

import pytest

from backend.database import SessionLocal
from backend.latency import diagnose, evaluate_state, get_latency_settings, validate_latency_setting
from backend.models import (
    AppSettings,
    LatencyHourly,
    LatencyOutage,
    LatencySample,
    LatencyTarget,
    ReportConfig,
)
from collector import latency, probe
from collector.probe import ProbeResult
from reporting import alerts


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def targets(db):
    rows = [
        LatencyTarget(name="Router", host="192.168.50.1", layer="lan"),
        LatencyTarget(name="ISP gateway", host="5.180.229.90", layer="isp"),
        LatencyTarget(name="Cloudflare", host="1.1.1.1", layer="internet"),
        LatencyTarget(name="Google", host="8.8.8.8", layer="internet"),
    ]
    db.add_all(rows)
    db.commit()
    return {t.name: t for t in rows}


@pytest.fixture
def sent_alerts(monkeypatch):
    messages = []
    monkeypatch.setattr(alerts, "send_alert", lambda db, message: messages.append(message) or True)
    return messages


def fake_probe(monkeypatch, replies):
    """replies maps host to a list of RTTs; hosts missing from the map lose every packet."""

    def probe_hosts(hosts):
        return {h: ProbeResult(sent=10, rtts=list(replies.get(h, []))) for h in hosts}

    monkeypatch.setattr(probe, "probe_hosts", probe_hosts)


HEALTHY = {
    "192.168.50.1": [1.0] * 10,
    "5.180.229.90": [20.0] * 10,
    "1.1.1.1": [24.0] * 10,
    "8.8.8.8": [25.0] * 10,
}


def add_round(db, when, targets, received_by_name, median=20.0, under_load=False):
    for name, target in targets.items():
        received = received_by_name.get(name, 10)
        db.add(
            LatencySample(
                target_id=target.id,
                timestamp=when,
                sent=10,
                received=received,
                min_ms=median if received else None,
                median_ms=median if received else None,
                avg_ms=median if received else None,
                max_ms=median if received else None,
                jitter_ms=0.0 if received else None,
                under_load=under_load,
            )
        )
    db.commit()


def test_summarize_computes_aggregates_and_jitter():
    stats = probe.summarize(ProbeResult(sent=5, rtts=[10.0, 12.0, 11.0, 15.0]))
    assert stats["received"] == 4
    assert stats["min"] == 10.0
    assert stats["max"] == 15.0
    assert stats["median"] == 11.5
    assert stats["jitter"] == pytest.approx((2 + 1 + 4) / 3)


def test_summarize_without_replies_has_no_latency():
    stats = probe.summarize(ProbeResult(sent=10, rtts=[]))
    assert stats["received"] == 0
    assert stats["median"] is None


def test_load_sampler_reports_median(monkeypatch):
    replies = iter([5.0, 7.0, 9.0])

    class Reply:
        def __init__(self, rtt):
            self.avg_rtt = rtt
            self.is_alive = True

    def fake_ping(*args, **kwargs):
        return Reply(next(replies))

    monkeypatch.setattr(probe, "ping", fake_ping)
    with probe.LoadSampler(interval=0) as sampler:
        time.sleep(0.2)
    assert sampler.median == 7.0


def test_seed_default_targets_only_once(db):
    assert latency.seed_default_targets(db) is True
    assert db.query(LatencyTarget).count() == len(latency.DEFAULT_TARGETS)
    db.query(LatencyTarget).delete()
    db.commit()
    assert latency.seed_default_targets(db) is False
    assert db.query(LatencyTarget).count() == 0


def test_round_stores_one_sample_per_target(db, targets, monkeypatch):
    fake_probe(monkeypatch, HEALTHY)
    latency.run_latency_round()
    samples = db.query(LatencySample).all()
    assert len(samples) == 4
    assert len({s.timestamp for s in samples}) == 1
    assert all(s.received == 10 and not s.under_load for s in samples)


def test_round_marks_samples_under_load(db, targets, monkeypatch):
    fake_probe(monkeypatch, HEALTHY)
    monkeypatch.setattr(latency.worker, "is_running", lambda: True)
    latency.run_latency_round()
    assert all(s.under_load for s in db.query(LatencySample).all())


def test_round_skips_disabled_targets(db, targets, monkeypatch):
    targets["Google"].enabled = False
    db.commit()
    fake_probe(monkeypatch, HEALTHY)
    latency.run_latency_round()
    assert db.query(LatencySample).count() == 3


def test_round_survives_probe_failure(db, targets, monkeypatch):
    def broken(hosts):
        raise OSError("no raw socket")

    monkeypatch.setattr(probe, "probe_hosts", broken)
    latency.run_latency_round()
    assert db.query(LatencySample).count() == 0


def test_rollup_aggregates_completed_hours_once(db, targets):
    now = latency.utcnow().replace(minute=30, second=0, microsecond=0)
    previous_hour = now.replace(minute=0) - timedelta(hours=1)
    for minute, median in ((0, 10.0), (1, 20.0), (2, 30.0)):
        add_round(db, previous_hour + timedelta(minutes=minute), {"Router": targets["Router"]}, {}, median=median)
    add_round(db, previous_hour + timedelta(minutes=3), {"Router": targets["Router"]}, {"Router": 0})
    add_round(db, now.replace(minute=0, second=5), {"Router": targets["Router"]}, {})

    assert latency.rollup_hourly(db, now) == 1
    assert latency.rollup_hourly(db, now) == 0
    row = db.query(LatencyHourly).one()
    assert row.hour == previous_hour
    assert row.samples == 4
    assert row.min_ms == 10.0
    assert row.median_ms == 20.0
    assert row.max_ms == 30.0
    assert row.loss_pct == pytest.approx(25.0)


def test_prune_removes_only_old_raw_samples(db, targets):
    now = latency.utcnow()
    router = {"Router": targets["Router"]}
    add_round(db, now - timedelta(days=91), router, {})
    add_round(db, now - timedelta(days=10), router, {})
    assert latency.prune_raw(db, now) == 1
    assert db.query(LatencySample).count() == 1


def states(**by_name):
    layers = {"Router": "lan", "ISP gateway": "isp", "Cloudflare": "internet", "Google": "internet", "VPS": "vpn"}
    return [{"name": n, "layer": layers[n], "state": by_name.get(n.replace(" ", "_"), "ok")} for n in layers]


def test_diagnosis_healthy():
    assert diagnose(states())["code"] == "ok"


def test_diagnosis_router_problem():
    assert diagnose(states(Router="down", ISP_gateway="down"))["code"] == "lan"


def test_diagnosis_isp_access_line():
    result = diagnose(states(ISP_gateway="down", Cloudflare="down", Google="down"))
    assert result["code"] == "isp_access"
    assert result["detail"].startswith("Router OK, ISP gateway unreachable")
    assert result["severity"] == "down"


def test_diagnosis_upstream():
    assert diagnose(states(Cloudflare="degraded", Google="down"))["code"] == "upstream"


def test_diagnosis_single_destination():
    result = diagnose(states(Google="degraded"))
    assert result["code"] == "destination"
    assert result["affected"] == ["Google"]
    assert result["severity"] == "warning"


def test_diagnosis_vpn_only():
    assert diagnose(states(VPS="down"))["code"] == "vpn"


def test_diagnosis_ignores_unknown_targets():
    assert diagnose(states(Router="unknown", Google="degraded"))["code"] == "destination"
    assert diagnose([{"name": "x", "layer": "lan", "state": "unknown"}])["code"] == "unknown"


def sample(received=10, median=20.0, age=timedelta(seconds=30)):
    now = latency.utcnow()
    return LatencySample(
        timestamp=now - age, sent=10, received=received, median_ms=median if received else None, under_load=False
    ), now


def test_state_down_when_last_round_lost_everything(db):
    settings = get_latency_settings(db)
    last, now = sample(received=0)
    assert evaluate_state([last], 20.0, settings, now) == "down"


def test_state_unknown_when_stale(db):
    settings = get_latency_settings(db)
    last, now = sample(age=timedelta(minutes=10))
    assert evaluate_state([last], 20.0, settings, now) == "unknown"


def test_state_degraded_on_loss(db):
    settings = get_latency_settings(db)
    last, now = sample(received=8)
    assert evaluate_state([last], 20.0, settings, now) == "degraded"


def test_state_degraded_on_latency_against_baseline(db):
    settings = get_latency_settings(db)
    last, now = sample(median=90.0)
    assert evaluate_state([last], 20.0, settings, now) == "degraded"


def test_state_ok_for_small_absolute_increase(db):
    settings = get_latency_settings(db)
    last, now = sample(median=3.0)
    assert evaluate_state([last], 0.6, settings, now) == "ok"


def test_outage_lifecycle_reports_after_recovery(db, targets, sent_alerts):
    now = latency.utcnow().replace(microsecond=0)
    t0 = now - timedelta(minutes=5)
    dead = {"ISP gateway": 0, "Cloudflare": 0, "Google": 0}

    add_round(db, t0, targets, {})
    latency.track_outages(db, t0)
    assert db.query(LatencyOutage).count() == 0

    add_round(db, t0 + timedelta(minutes=1), targets, dead)
    latency.track_outages(db, t0 + timedelta(minutes=1))
    assert db.query(LatencyOutage).count() == 0

    add_round(db, t0 + timedelta(minutes=2), targets, dead)
    latency.track_outages(db, t0 + timedelta(minutes=2))
    outage = db.query(LatencyOutage).one()
    assert outage.started_at == t0 + timedelta(minutes=1)
    assert outage.ended_at is None
    assert sent_alerts == []

    add_round(db, t0 + timedelta(minutes=3), targets, dead)
    latency.track_outages(db, t0 + timedelta(minutes=3))
    assert db.query(LatencyOutage).count() == 1

    add_round(db, t0 + timedelta(minutes=4), targets, {})
    latency.track_outages(db, t0 + timedelta(minutes=4))
    db.refresh(outage)
    assert outage.ended_at == t0 + timedelta(minutes=4)
    assert outage.reported is True
    assert len(sent_alerts) == 1
    assert sent_alerts[0].startswith("Internet outage")
    assert "ISP gateway unreachable" in sent_alerts[0]


def test_outage_not_declared_when_one_internet_target_answers(db, targets, sent_alerts):
    now = latency.utcnow().replace(microsecond=0)
    for minute in range(3):
        when = now - timedelta(minutes=3 - minute)
        add_round(db, when, targets, {"Cloudflare": 0})
        latency.track_outages(db, when)
    assert db.query(LatencyOutage).count() == 0


def test_unreported_outage_is_retried(db, targets, monkeypatch):
    now = latency.utcnow().replace(microsecond=0)
    db.add(LatencyOutage(started_at=now - timedelta(minutes=8), ended_at=now - timedelta(minutes=3), diagnosis="x"))
    db.commit()
    monkeypatch.setattr(alerts, "send_alert", lambda db, message: False)
    latency.report_pending_outages(db)
    assert db.query(LatencyOutage).one().reported is False
    monkeypatch.setattr(alerts, "send_alert", lambda db, message: True)
    latency.report_pending_outages(db)
    assert db.query(LatencyOutage).one().reported is True


def fill_lossy_rounds(db, targets, now, minutes, received):
    for minute in range(minutes):
        add_round(db, now - timedelta(minutes=minutes - 1 - minute), {"Google": targets["Google"]}, {"Google": received})


def test_degradation_alert_with_cooldown(db, targets, sent_alerts):
    now = latency.utcnow().replace(microsecond=0)
    fill_lossy_rounds(db, targets, now, 10, received=8)
    latency.check_degradation(db, now)
    assert len(sent_alerts) == 1
    assert "Google 20%" in sent_alerts[0]
    latency.check_degradation(db, now + timedelta(minutes=1))
    assert len(sent_alerts) == 1
    fill_lossy_rounds(db, targets, now + timedelta(minutes=61), 10, received=8)
    latency.check_degradation(db, now + timedelta(minutes=61))
    assert len(sent_alerts) == 2


def test_degradation_needs_a_full_window(db, targets, sent_alerts):
    now = latency.utcnow().replace(microsecond=0)
    fill_lossy_rounds(db, targets, now, 3, received=5)
    latency.check_degradation(db, now)
    assert sent_alerts == []


def test_degradation_alerts_can_be_disabled(db, targets, sent_alerts):
    db.add(AppSettings(key="latency_alerts_enabled", value="0"))
    db.commit()
    now = latency.utcnow().replace(microsecond=0)
    fill_lossy_rounds(db, targets, now, 10, received=5)
    latency.check_degradation(db, now)
    assert sent_alerts == []


def test_window_stats_and_outage_stats(db, targets):
    now = latency.utcnow().replace(microsecond=0)
    for minute in range(4):
        add_round(db, now - timedelta(minutes=minute), {"Router": targets["Router"]}, {"Router": 5 if minute == 0 else 10}, median=2.0 + minute)
    stats = latency.window_stats(db, now - timedelta(days=1), now)
    assert [s["name"] for s in stats] == ["Router"]
    assert stats[0]["median_ms"] == 3.5
    assert stats[0]["loss_pct"] == pytest.approx(12.5)

    db.add(LatencyOutage(started_at=now - timedelta(hours=2), ended_at=now - timedelta(hours=1)))
    db.commit()
    count, total = latency.outage_stats(db, now - timedelta(days=1), now)
    assert count == 1
    assert total == timedelta(hours=1)


def test_window_stats_uses_hourly_rollups_for_long_windows(db, targets):
    now = latency.utcnow()
    db.add(
        LatencyHourly(
            target_id=targets["Router"].id, hour=now - timedelta(days=20), median_ms=4.0, p95_ms=6.0, loss_pct=2.0, samples=60
        )
    )
    db.commit()
    stats = latency.window_stats(db, now - timedelta(days=30), now)
    assert stats[0]["median_ms"] == 4.0
    assert stats[0]["loss_pct"] == 2.0


def test_setting_validation():
    assert validate_latency_setting("latency_loss_pct", 5) is None
    assert validate_latency_setting("latency_loss_pct", 150) is not None
    assert validate_latency_setting("latency_state_rounds", "abc") is not None
    assert validate_latency_setting("report_timezone", "Europe/Madrid") is None
    assert validate_latency_setting("report_timezone", "Nowhere/Land") is not None


def test_format_outage_uses_local_time(db):
    outage = LatencyOutage(
        started_at=latency.utcnow().replace(hour=11, minute=2),
        ended_at=latency.utcnow().replace(hour=11, minute=7),
        diagnosis="Router OK, ISP gateway unreachable: access line.",
    )
    message = alerts.format_outage(outage, "UTC")
    assert message == "Internet outage 11:02 to 11:07 (5 min). Router OK, ISP gateway unreachable: access line."


def test_send_alert_needs_token_and_recipient(db, monkeypatch):
    sent = []

    async def fake_send(token, chat, message):
        sent.append((token, chat, message))

    monkeypatch.setattr(alerts, "send_telegram_message", fake_send)
    assert alerts.send_alert(db, "hi") is False
    db.add(AppSettings(key="telegram_bot_token", value="tok"))
    db.add(ReportConfig(name="daily", schedule="0 8 * * *", recipient="123", enabled=True))
    db.commit()
    assert alerts.send_alert(db, "hi") is True
    assert sent == [("tok", "123", "hi")]


def test_migration_renames_tailnet_layer(db):
    from backend.database import run_migrations

    db.add(LatencyTarget(name="Old VPS", host="10.8.0.1", layer="tailnet", enabled=True))
    db.add(LatencyTarget(name="Router", host="192.168.50.1", layer="lan", enabled=True))
    db.commit()

    run_migrations()
    db.expire_all()

    layers = {t.name: t.layer for t in db.query(LatencyTarget).all()}
    assert layers == {"Old VPS": "vpn", "Router": "lan"}
