"""Latency monitor logic: settings, per-target state, diagnosis and the summary payload."""

import math
import statistics
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import AppSettings, LatencySample, LatencyTarget

LAYERS = ("lan", "isp", "internet", "tailnet")
ROUND_SECONDS = 60
STALE_AFTER = timedelta(seconds=ROUND_SECONDS * 3)

SETTING_DEFAULTS = {
    "latency_loss_pct": 5.0,
    "latency_baseline_factor": 3.0,
    "latency_min_excess_ms": 15.0,
    "latency_state_rounds": 3,
    "latency_outage_rounds": 2,
    "latency_alerts_enabled": 1,
    "latency_alert_loss_pct": 5.0,
    "latency_alert_minutes": 10,
    "latency_alert_cooldown_minutes": 60,
    "report_timezone": "Europe/Madrid",
}
SETTING_RANGES = {
    "latency_loss_pct": (0.0, 100.0),
    "latency_baseline_factor": (1.0, 100.0),
    "latency_min_excess_ms": (0.0, 10000.0),
    "latency_state_rounds": (1, 60),
    "latency_outage_rounds": (1, 60),
    "latency_alerts_enabled": (0, 1),
    "latency_alert_loss_pct": (0.0, 100.0),
    "latency_alert_minutes": (1, 1440),
    "latency_alert_cooldown_minutes": (1, 10080),
}

BAD_STATES = ("degraded", "down")


def get_latency_settings(db: Session) -> dict:
    """Returns every latency setting, falling back to its default."""
    stored = {s.key: s.value for s in db.query(AppSettings).filter(AppSettings.key.in_(SETTING_DEFAULTS)).all()}
    settings = {}
    for key, default in SETTING_DEFAULTS.items():
        raw = stored.get(key)
        if raw in (None, ""):
            settings[key] = default
        elif isinstance(default, str):
            settings[key] = raw
        else:
            try:
                settings[key] = type(default)(float(raw))
            except ValueError:
                settings[key] = default
    return settings


def validate_latency_setting(key: str, value) -> str | None:
    """Returns an error message if the value is not valid for the latency setting."""
    if key == "report_timezone":
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(str(value))
        except (ZoneInfoNotFoundError, ValueError):
            return f"report_timezone is not a valid timezone: {value}"
        return None
    low, high = SETTING_RANGES[key]
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"{key} must be a number"
    if not low <= number <= high:
        return f"{key} must be between {low:g} and {high:g}"
    return None


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(pct / 100 * len(ordered)) - 1, 0)]


def loss_pct(samples) -> float | None:
    sent = sum(s.sent for s in samples)
    if not sent:
        return None
    return (1 - sum(s.received for s in samples) / sent) * 100


def medians(samples) -> list[float]:
    return [s.median_ms for s in samples if s.median_ms is not None]


def evaluate_state(recent: list, baseline_ms: float | None, settings: dict, now: datetime) -> str:
    """Classifies a target as ok, degraded, down or unknown from its newest samples (newest first)."""
    if not recent or now - recent[0].timestamp > STALE_AFTER:
        return "unknown"
    last = recent[0]
    if last.received == 0:
        return "down"
    window = recent[: settings["latency_state_rounds"]]
    loss = loss_pct(window)
    if loss is not None and loss > settings["latency_loss_pct"]:
        return "degraded"
    recent_medians = medians(window)
    if baseline_ms and recent_medians:
        current = statistics.median(recent_medians)
        if (
            current > baseline_ms * settings["latency_baseline_factor"]
            and current - baseline_ms > settings["latency_min_excess_ms"]
        ):
            return "degraded"
    return "ok"


def _status_word(state: str) -> str:
    return {"ok": "OK", "degraded": "degraded", "down": "unreachable"}.get(state, "unknown")


def diagnose(targets: list[dict]) -> dict:
    """Applies the layer rules to target states and returns the diagnosis."""
    live = [t for t in targets if t["state"] != "unknown"]
    if not live:
        return {"code": "unknown", "text": "No recent data", "detail": "No recent data", "severity": "unknown", "affected": []}

    def bad(layer):
        return [t for t in live if t["layer"] == layer and t["state"] in BAD_STATES]

    internet = [t for t in live if t["layer"] == "internet"]
    internet_bad = bad("internet")

    if bad("lan"):
        code, text, cause, affected = "lan", "LAN / router problem", "LAN / router", bad("lan")
    elif bad("isp"):
        code, text, cause, affected = "isp_access", "ISP access line", "access line", bad("isp")
    elif internet_bad and len(internet_bad) == len(internet) and len(internet) > 1:
        code, text, cause, affected = "upstream", "Upstream / ISP core", "upstream / ISP core", internet_bad
    elif internet_bad:
        names = ", ".join(t["name"] for t in internet_bad)
        code, text, cause, affected = "destination", f"Only {names}", "that destination only", internet_bad
    elif bad("tailnet"):
        code, text, cause, affected = "tailnet", "Tailnet / VPS", "tailnet / VPS", bad("tailnet")
    else:
        return {
            "code": "ok",
            "text": "All targets healthy",
            "detail": "All targets responding",
            "severity": "ok",
            "affected": [],
        }

    lan_isp = [t for t in live if t["layer"] in ("lan", "isp")]
    shown = lan_isp if code in ("lan", "isp_access", "upstream") else affected
    statuses = ", ".join(f"{t['name']} {_status_word(t['state'])}" for t in shown)
    severity = "down" if any(t["state"] == "down" for t in affected) else "warning"
    return {
        "code": code,
        "text": text,
        "detail": f"{statuses}: {cause}.",
        "severity": severity,
        "affected": [t["name"] for t in affected],
    }


def baseline_median(samples_24h: list) -> float | None:
    unloaded = medians([s for s in samples_24h if not s.under_load]) or medians(samples_24h)
    return statistics.median(unloaded) if unloaded else None


def target_status(db: Session, target: LatencyTarget, settings: dict, now: datetime) -> dict:
    """Builds the summary entry of one target."""
    samples = (
        db.query(LatencySample)
        .filter(LatencySample.target_id == target.id, LatencySample.timestamp >= now - timedelta(hours=24))
        .order_by(LatencySample.timestamp.desc())
        .all()
    )
    baseline = baseline_median(samples)
    state = evaluate_state(samples[:60], baseline, settings, now)
    last = samples[0] if samples else None
    hour = [s for s in samples if s.timestamp >= now - timedelta(hours=1)]
    hour_medians = medians(hour)
    return {
        "id": target.id,
        "name": target.name,
        "host": target.host,
        "layer": target.layer,
        "state": state,
        "last_at": last.timestamp if last else None,
        "median_ms": last.median_ms if last else None,
        "loss_pct": loss_pct([last]) if last else None,
        "jitter_ms": last.jitter_ms if last else None,
        "loss_1h_pct": loss_pct(hour),
        "median_1h_ms": statistics.median(hour_medians) if hour_medians else None,
        "p95_24h_ms": percentile(medians(samples), 95),
        "baseline_ms": baseline,
    }


def build_summary(db: Session, now: datetime) -> dict:
    settings = get_latency_settings(db)
    targets = db.query(LatencyTarget).filter(LatencyTarget.enabled.is_(True)).order_by(LatencyTarget.id).all()
    statuses = [target_status(db, t, settings, now) for t in targets]
    return {"targets": statuses, "diagnosis": diagnose(statuses)}
