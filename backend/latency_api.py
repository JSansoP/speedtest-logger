import ipaddress
import logging
import re
from datetime import UTC, datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .database import SessionLocal
from .latency import LAYERS, build_summary, get_latency_settings
from .models import LatencyHourly, LatencySample, LatencyTarget
from .timeutil import parse_utc, to_utc_iso

bp = Blueprint("latency", __name__)
logger = logging.getLogger("LatencyAPI")

RAW_RANGE_MAX = timedelta(days=7)
HOSTNAME_PATTERN = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")


def serialize_target(target: LatencyTarget) -> dict:
    return {"id": target.id, "name": target.name, "host": target.host, "layer": target.layer, "enabled": target.enabled}


def validate_target_payload(data: dict, partial: bool) -> str | None:
    """Returns an error message if the latency target payload is invalid."""
    if not partial:
        missing = [key for key in ("name", "host", "layer") if not str(data.get(key) or "").strip()]
        if missing:
            return f"Missing required fields: {', '.join(missing)}"
    if "name" in data and not str(data["name"] or "").strip():
        return "name cannot be empty"
    if "host" in data:
        host = str(data["host"] or "").strip()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not HOSTNAME_PATTERN.match(host):
                return f"Invalid host: {data['host']}"
    if "layer" in data and data["layer"] not in LAYERS:
        return f"Invalid layer: {data['layer']} (expected one of {', '.join(LAYERS)})"
    return None


@bp.route("/api/latency/targets", methods=["GET"])
def get_latency_targets():
    """
    List latency targets
    ---
    responses:
      200:
        description: All latency targets, including disabled ones
    """
    db: Session = SessionLocal()
    try:
        return jsonify([serialize_target(t) for t in db.query(LatencyTarget).order_by(LatencyTarget.id).all()])
    finally:
        db.close()


@bp.route("/api/latency/targets", methods=["POST"])
def create_latency_target():
    """
    Create a latency target
    ---
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            name: { type: string, example: Router }
            host: { type: string, example: 192.168.50.1 }
            layer: { type: string, enum: [lan, isp, internet, tailnet] }
            enabled: { type: boolean, default: true }
    responses:
      201:
        description: Target created
      400:
        description: Invalid payload
      409:
        description: A target with that name already exists
    """
    data = request.get_json(silent=True) or {}
    error = validate_target_payload(data, partial=False)
    if error:
        return jsonify({"error": error}), 400
    db: Session = SessionLocal()
    try:
        name = data["name"].strip()
        if db.query(LatencyTarget).filter(LatencyTarget.name == name).first():
            return jsonify({"error": f"A target named '{name}' already exists"}), 409
        target = LatencyTarget(
            name=name, host=data["host"].strip(), layer=data["layer"], enabled=bool(data.get("enabled", True))
        )
        db.add(target)
        db.commit()
        db.refresh(target)
        return jsonify(serialize_target(target)), 201
    except SQLAlchemyError as e:
        logger.error(f"Error creating latency target: {e}")
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()


@bp.route("/api/latency/targets/<int:id>", methods=["PUT"])
def update_latency_target(id):
    """
    Update a latency target
    ---
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Target updated
      404:
        description: Target not found
      409:
        description: A target with that name already exists
    """
    data = request.get_json(silent=True) or {}
    error = validate_target_payload(data, partial=True)
    if error:
        return jsonify({"error": error}), 400
    db: Session = SessionLocal()
    try:
        target = db.query(LatencyTarget).filter(LatencyTarget.id == id).first()
        if not target:
            return jsonify({"error": "Target not found"}), 404
        if "name" in data:
            name = data["name"].strip()
            clash = db.query(LatencyTarget).filter(LatencyTarget.name == name, LatencyTarget.id != id).first()
            if clash:
                return jsonify({"error": f"A target named '{name}' already exists"}), 409
            target.name = name
        if "host" in data:
            target.host = data["host"].strip()
        if "layer" in data:
            target.layer = data["layer"]
        if "enabled" in data:
            target.enabled = bool(data["enabled"])
        db.commit()
        return jsonify(serialize_target(target)), 200
    except SQLAlchemyError as e:
        logger.error(f"Error updating latency target: {e}")
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()


@bp.route("/api/latency/targets/<int:id>", methods=["DELETE"])
def delete_latency_target(id):
    """
    Delete a latency target and its samples
    ---
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses:
      200:
        description: Target deleted
      404:
        description: Target not found
    """
    db: Session = SessionLocal()
    try:
        target = db.query(LatencyTarget).filter(LatencyTarget.id == id).first()
        if not target:
            return jsonify({"error": "Target not found"}), 404
        db.query(LatencySample).filter(LatencySample.target_id == id).delete()
        db.query(LatencyHourly).filter(LatencyHourly.target_id == id).delete()
        db.delete(target)
        db.commit()
        return jsonify({"message": f"Target {id} deleted"}), 200
    except SQLAlchemyError as e:
        logger.error(f"Error deleting latency target: {e}")
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()


def epoch(value: datetime) -> int:
    return int(value.replace(tzinfo=UTC).timestamp())


def raw_columns(samples: list) -> dict:
    return {
        "t": [epoch(s.timestamp) for s in samples],
        "sent": [s.sent for s in samples],
        "received": [s.received for s in samples],
        "loss_pct": [round((1 - s.received / s.sent) * 100, 2) if s.sent else None for s in samples],
        "min": [s.min_ms for s in samples],
        "median": [s.median_ms for s in samples],
        "avg": [s.avg_ms for s in samples],
        "max": [s.max_ms for s in samples],
        "jitter": [s.jitter_ms for s in samples],
        "under_load": [bool(s.under_load) for s in samples],
    }


def hourly_columns(rows: list) -> dict:
    return {
        "t": [epoch(r.hour) for r in rows],
        "samples": [r.samples for r in rows],
        "loss_pct": [r.loss_pct for r in rows],
        "min": [r.min_ms for r in rows],
        "median": [r.median_ms for r in rows],
        "avg": [r.avg_ms for r in rows],
        "max": [r.max_ms for r in rows],
        "p95": [r.p95_ms for r in rows],
    }


@bp.route("/api/latency", methods=["GET"])
def get_latency():
    """
    Latency series per target, as columns of equal length
    ---
    parameters:
      - name: target
        in: query
        type: integer
        description: Target id (all targets when omitted)
      - name: from
        in: query
        type: string
        description: ISO 8601 start (default 24 hours before "to")
      - name: to
        in: query
        type: string
        description: ISO 8601 end (default now)
    responses:
      200:
        description: >
          Raw per-round samples for ranges up to 7 days (resolution "raw"), hourly rollups beyond
          (resolution "hourly"). Timestamps in "t" are epoch seconds (UTC).
      400:
        description: Invalid parameter
    """
    try:
        end = parse_utc(request.args["to"]) if request.args.get("to") else datetime.now(UTC).replace(tzinfo=None)
        start = parse_utc(request.args["from"]) if request.args.get("from") else end - timedelta(hours=24)
    except ValueError:
        return jsonify({"error": "Invalid from or to timestamp"}), 400
    if start >= end:
        return jsonify({"error": "from must be before to"}), 400
    target_id = request.args.get("target", type=int)
    resolution = "raw" if end - start <= RAW_RANGE_MAX else "hourly"
    db: Session = SessionLocal()
    try:
        query = db.query(LatencyTarget).order_by(LatencyTarget.id)
        if target_id is not None:
            query = query.filter(LatencyTarget.id == target_id)
        series = []
        for target in query.all():
            if resolution == "raw":
                rows = (
                    db.query(LatencySample)
                    .filter(
                        LatencySample.target_id == target.id,
                        LatencySample.timestamp >= start,
                        LatencySample.timestamp <= end,
                    )
                    .order_by(LatencySample.timestamp)
                    .all()
                )
                columns = raw_columns(rows)
            else:
                rows = (
                    db.query(LatencyHourly)
                    .filter(LatencyHourly.target_id == target.id, LatencyHourly.hour >= start, LatencyHourly.hour <= end)
                    .order_by(LatencyHourly.hour)
                    .all()
                )
                columns = hourly_columns(rows)
            series.append({"id": target.id, "name": target.name, "layer": target.layer, **columns})
        return jsonify({"resolution": resolution, "from": to_utc_iso(start), "to": to_utc_iso(end), "targets": series})
    finally:
        db.close()


@bp.route("/api/latency/summary", methods=["GET"])
def get_latency_summary():
    """
    Current state of every enabled latency target plus the overall diagnosis
    ---
    responses:
      200:
        description: >
          targets[] with id, name, host, layer, state (ok, degraded, down, unknown), last round values,
          loss and median over the last hour and p95 over 24 hours; diagnosis with code, text, detail,
          severity and affected targets.
    """
    db: Session = SessionLocal()
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        summary = build_summary(db, now)
        for target in summary["targets"]:
            target["last_at"] = to_utc_iso(target["last_at"])
            for key, value in target.items():
                if isinstance(value, float):
                    target[key] = round(value, 2)
        summary["updated_at"] = to_utc_iso(now)
        settings = get_latency_settings(db)
        summary["thresholds"] = {
            "loss_pct": settings["latency_loss_pct"],
            "baseline_factor": settings["latency_baseline_factor"],
        }
        return jsonify(summary)
    finally:
        db.close()
