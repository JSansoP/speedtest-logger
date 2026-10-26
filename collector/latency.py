"""Latency monitor jobs: probe rounds, hourly rollups, retention and outage tracking."""

import logging
import statistics
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.latency import (
    build_summary,
    get_latency_settings,
    loss_pct,
    medians,
    percentile,
)
from backend.models import AppSettings, LatencyHourly, LatencyOutage, LatencySample, LatencyTarget
from collector import probe, worker
from reporting import alerts

logger = logging.getLogger(__name__)

RAW_RETENTION = timedelta(days=90)

DEFAULT_TARGETS = [
    ("Router", "192.168.50.1", "lan"),
    ("ISP gateway", "5.180.229.90", "isp"),
    ("Cloudflare", "1.1.1.1", "internet"),
    ("Google", "8.8.8.8", "internet"),
    ("VPS", "10.8.0.1", "vpn"),
]


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def seed_default_targets(db: Session) -> bool:
    """Creates the default targets once; deleting them later does not bring them back."""
    if db.query(AppSettings).filter(AppSettings.key == "latency_targets_seeded").first():
        return False
    if db.query(LatencyTarget).count() == 0:
        for name, host, layer in DEFAULT_TARGETS:
            db.add(LatencyTarget(name=name, host=host, layer=layer, enabled=True))
    db.add(AppSettings(key="latency_targets_seeded", value="1"))
    db.commit()
    return True


def run_latency_round():
    """Probes every enabled target once and stores one aggregate sample per target."""
    db = SessionLocal()
    try:
        targets = db.query(LatencyTarget).filter(LatencyTarget.enabled.is_(True)).all()
        if not targets:
            return
        started = utcnow().replace(microsecond=0)
        loaded_before = worker.is_running()
        try:
            results = probe.probe_hosts(sorted({t.host for t in targets}))
        except Exception as e:  # noqa: BLE001
            logger.error("Latency round failed: %s", e)
            return
        under_load = loaded_before or worker.is_running()
        for target in targets:
            result = results.get(target.host)
            if result is None:
                continue
            stats = probe.summarize(result)
            db.add(
                LatencySample(
                    target_id=target.id,
                    timestamp=started,
                    sent=stats["sent"],
                    received=stats["received"],
                    min_ms=stats["min"],
                    median_ms=stats["median"],
                    avg_ms=stats["avg"],
                    max_ms=stats["max"],
                    jitter_ms=stats["jitter"],
                    under_load=under_load,
                )
            )
        db.commit()
        track_outages(db, started)
        check_degradation(db, started)
    except Exception:
        logger.exception("Latency round crashed")
        db.rollback()
    finally:
        db.close()


def _hour_start(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def rollup_hourly(db: Session, now: datetime) -> int:
    """Aggregates completed hours of raw samples that have no rollup yet. Returns the rows created."""
    current_hour = _hour_start(now)
    created = 0
    for target in db.query(LatencyTarget).all():
        last_hour = db.query(func.max(LatencyHourly.hour)).filter(LatencyHourly.target_id == target.id).scalar()
        query = db.query(LatencySample).filter(
            LatencySample.target_id == target.id, LatencySample.timestamp < current_hour
        )
        if last_hour:
            query = query.filter(LatencySample.timestamp >= last_hour + timedelta(hours=1))
        buckets: dict[datetime, list[LatencySample]] = {}
        for sample in query.order_by(LatencySample.timestamp):
            buckets.setdefault(_hour_start(sample.timestamp), []).append(sample)
        for hour, samples in buckets.items():
            values = medians(samples)
            db.add(
                LatencyHourly(
                    target_id=target.id,
                    hour=hour,
                    min_ms=min(values) if values else None,
                    median_ms=statistics.median(values) if values else None,
                    avg_ms=statistics.mean(values) if values else None,
                    max_ms=max(values) if values else None,
                    p95_ms=percentile(values, 95),
                    loss_pct=loss_pct(samples) or 0.0,
                    samples=len(samples),
                )
            )
            created += 1
    db.commit()
    return created


def prune_raw(db: Session, now: datetime) -> int:
    """Deletes raw samples past retention that are already rolled up."""
    deleted = db.query(LatencySample).filter(LatencySample.timestamp < now - RAW_RETENTION).delete()
    db.commit()
    return deleted


def run_latency_maintenance():
    db = SessionLocal()
    try:
        now = utcnow()
        rolled = rollup_hourly(db, now)
        pruned = prune_raw(db, now)
        logger.info("Latency maintenance: %d hourly rows created, %d raw samples pruned", rolled, pruned)
    except Exception:
        logger.exception("Latency maintenance failed")
        db.rollback()
    finally:
        db.close()


def internet_target_ids(db: Session) -> list[int]:
    rows = db.query(LatencyTarget.id).filter(LatencyTarget.layer == "internet", LatencyTarget.enabled.is_(True)).all()
    return [r[0] for r in rows]


def internet_is_down(db: Session, rounds: int) -> bool | None:
    """True if the last `rounds` rounds lost every packet on every internet target; None without enough data."""
    ids = internet_target_ids(db)
    if not ids:
        return None
    stamps = [
        r[0]
        for r in db.query(LatencySample.timestamp)
        .filter(LatencySample.target_id.in_(ids))
        .group_by(LatencySample.timestamp)
        .order_by(LatencySample.timestamp.desc())
        .limit(rounds)
        .all()
    ]
    if len(stamps) < rounds:
        return None
    received = (
        db.query(func.sum(LatencySample.received))
        .filter(LatencySample.target_id.in_(ids), LatencySample.timestamp >= stamps[-1])
        .scalar()
    )
    return not received


def track_outages(db: Session, round_time: datetime):
    """Opens an outage after N dead rounds, closes it on recovery and reports closed outages."""
    settings = get_latency_settings(db)
    rounds = settings["latency_outage_rounds"]
    ids = internet_target_ids(db)
    open_outage = db.query(LatencyOutage).filter(LatencyOutage.ended_at.is_(None)).first()
    down = internet_is_down(db, rounds)
    if down is None:
        return

    if down:
        diagnosis = build_summary(db, round_time)["diagnosis"]
        if open_outage is None:
            first_round = (
                db.query(LatencySample.timestamp)
                .filter(LatencySample.target_id.in_(ids))
                .group_by(LatencySample.timestamp)
                .order_by(LatencySample.timestamp.desc())
                .limit(rounds)
                .all()[-1][0]
            )
            open_outage = LatencyOutage(started_at=first_round, diagnosis=diagnosis["detail"], reported=False)
            db.add(open_outage)
        else:
            open_outage.diagnosis = diagnosis["detail"]
        db.commit()
    else:
        alive = (
            db.query(func.sum(LatencySample.received))
            .filter(LatencySample.target_id.in_(ids), LatencySample.timestamp == round_time)
            .scalar()
        )
        if open_outage is not None and alive:
            open_outage.ended_at = round_time
            db.commit()

    if settings["latency_alerts_enabled"]:
        report_pending_outages(db)


def report_pending_outages(db: Session):
    since = utcnow() - timedelta(days=1)
    pending = (
        db.query(LatencyOutage)
        .filter(LatencyOutage.ended_at.isnot(None), LatencyOutage.reported.is_(False), LatencyOutage.ended_at >= since)
        .order_by(LatencyOutage.started_at)
        .all()
    )
    for outage in pending:
        if alerts.send_alert(db, alerts.format_outage(outage, get_latency_settings(db)["report_timezone"])):
            outage.reported = True
            db.commit()


def check_degradation(db: Session, round_time: datetime):
    """Sends an alert when a target keeps losing packets for the configured period, with a cooldown."""
    settings = get_latency_settings(db)
    if not settings["latency_alerts_enabled"]:
        return
    if db.query(LatencyOutage).filter(LatencyOutage.ended_at.is_(None)).first():
        return
    window = timedelta(minutes=settings["latency_alert_minutes"])
    cooldown_key = "latency_degradation_last_alert"
    last_alert = db.query(AppSettings).filter(AppSettings.key == cooldown_key).first()
    if last_alert and round_time - datetime.fromisoformat(last_alert.value) < timedelta(
        minutes=settings["latency_alert_cooldown_minutes"]
    ):
        return

    expected_rounds = settings["latency_alert_minutes"]
    affected = []
    for target in db.query(LatencyTarget).filter(LatencyTarget.enabled.is_(True)).all():
        samples = (
            db.query(LatencySample)
            .filter(LatencySample.target_id == target.id, LatencySample.timestamp > round_time - window)
            .all()
        )
        if len(samples) < expected_rounds * 0.8:
            continue
        loss = loss_pct(samples)
        if loss is not None and loss > settings["latency_alert_loss_pct"]:
            affected.append((target.name, loss))
    if not affected:
        return

    diagnosis = build_summary(db, round_time)["diagnosis"]
    message = alerts.format_degradation(affected, settings["latency_alert_minutes"], diagnosis["detail"])
    if alerts.send_alert(db, message):
        if last_alert:
            last_alert.value = round_time.isoformat()
        else:
            db.add(AppSettings(key=cooldown_key, value=round_time.isoformat()))
        db.commit()


def window_stats(db: Session, since: datetime, now: datetime) -> list[dict]:
    """Per target latency and loss over a window, from raw samples up to 7 days and rollups beyond."""
    stats = []
    use_raw = now - since <= timedelta(days=7)
    for target in db.query(LatencyTarget).order_by(LatencyTarget.id).all():
        if use_raw:
            rows = db.query(LatencySample).filter(LatencySample.target_id == target.id, LatencySample.timestamp >= since).all()
            values = medians(rows)
            loss = loss_pct(rows)
        else:
            rows = db.query(LatencyHourly).filter(LatencyHourly.target_id == target.id, LatencyHourly.hour >= since).all()
            values = [r.median_ms for r in rows if r.median_ms is not None]
            total = sum(r.samples for r in rows)
            loss = sum(r.loss_pct * r.samples for r in rows) / total if total else None
        if not values and loss is None:
            continue
        stats.append(
            {
                "name": target.name,
                "median_ms": statistics.median(values) if values else None,
                "p95_ms": percentile(values, 95),
                "loss_pct": loss,
            }
        )
    return stats


def outage_stats(db: Session, since: datetime, now: datetime) -> tuple[int, timedelta]:
    outages = db.query(LatencyOutage).filter(LatencyOutage.started_at >= since).all()
    total = sum(((o.ended_at or now) - o.started_at for o in outages), timedelta())
    return len(outages), total

