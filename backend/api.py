import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from croniter import croniter
from flasgger import Swagger
from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from werkzeug.middleware.proxy_fix import ProxyFix

from collector.scheduler import scheduler, update_speedtest_interval
from collector.worker import is_running, start_background_run

from .database import SessionLocal, engine
from .models import AppSettings, Base, ReportConfig, SpeedTestResult

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
DATA_WINDOWS = {"last_day", "last_week", "last_month", "last_3_months", "last_6_months", "last_year"}

app = Flask(__name__, static_folder=None)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
swagger = Swagger(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API")

# Ensure tables are created
Base.metadata.create_all(bind=engine)


def to_utc_iso(value: datetime | None) -> str | None:
    """Serializes a naive UTC datetime as ISO 8601 with an explicit offset."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat() + "+00:00"
    return value.astimezone(UTC).isoformat()


def parse_utc(value: str) -> datetime:
    """Parses an ISO 8601 string into a naive UTC datetime."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def next_cron_run(schedule: str, last_run: datetime | None) -> str | None:
    """Returns the next run time for a report schedule, or None if the schedule is invalid."""
    if not croniter.is_valid(schedule):
        return None
    if last_run is None:
        return to_utc_iso(datetime.now(UTC))
    return to_utc_iso(croniter(schedule, last_run).get_next(datetime))


def validate_report_payload(data: dict, partial: bool) -> str | None:
    """Returns an error message if the report payload is invalid."""
    required = ("name", "schedule", "recipient")
    if not partial:
        missing = [key for key in required if not str(data.get(key) or "").strip()]
        if missing:
            return f"Missing required fields: {', '.join(missing)}"
    if "schedule" in data and not croniter.is_valid(str(data["schedule"]).strip()):
        return f"Invalid cron expression: {data['schedule']}"
    if "data_window" in data and data["data_window"] not in DATA_WINDOWS:
        return f"Invalid data window: {data['data_window']}"
    return None


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/static/<path:filename>")
def frontend_static(filename):
    return send_from_directory(FRONTEND_DIR, filename)


@app.route("/api/speedtests", methods=["GET"])
def get_speedtests():
    """
    Get speedtest results, newest first
    ---
    parameters:
      - name: limit
        in: query
        type: integer
        description: Number of results to return (0 for no limit)
        default: 100
      - name: since
        in: query
        type: string
        description: Only return results at or after this ISO 8601 timestamp
    responses:
      200:
        description: A list of speedtest results
      400:
        description: Invalid since parameter
    """
    db: Session = SessionLocal()
    try:
        limit = request.args.get("limit", default=100, type=int)
        query = db.query(SpeedTestResult).order_by(SpeedTestResult.timestamp.desc())
        since = request.args.get("since")
        if since:
            try:
                query = query.filter(SpeedTestResult.timestamp >= parse_utc(since))
            except ValueError:
                return jsonify({"error": f"Invalid since timestamp: {since}"}), 400
        if limit > 0:
            query = query.limit(limit)
        return jsonify([
            {
                "id": r.id,
                "timestamp": to_utc_iso(r.timestamp),
                "download": r.download,
                "upload": r.upload,
                "ping": r.ping,
                "server_name": r.server_name,
                "advertised_download": r.advertised_download,
                "advertised_upload": r.advertised_upload
            } for r in query.all()
        ])
    finally:
        db.close()

@app.route("/api/speedtests/run", methods=["POST"])
def trigger_speedtest():
    """
    Trigger a manual speedtest in the background
    ---
    responses:
      202:
        description: Speedtest started
      409:
        description: A speedtest is already running
    """
    if not start_background_run():
        return jsonify({"error": "A speedtest is already running."}), 409
    return jsonify({"message": "Speedtest started in background."}), 202

@app.route("/api/status", methods=["GET"])
def get_status():
    """
    Get collector status
    ---
    responses:
      200:
        description: Whether a test is running, the next scheduled run and result totals
    """
    db: Session = SessionLocal()
    try:
        total, last_timestamp = db.query(
            func.count(SpeedTestResult.id), func.max(SpeedTestResult.timestamp)
        ).one()
        interval = db.query(AppSettings).filter(AppSettings.key == "speedtest_interval").first()
        job = scheduler.get_job("speedtest_job")
        return jsonify({
            "running": is_running(),
            "next_run": to_utc_iso(job.next_run_time) if job and job.next_run_time else None,
            "interval_minutes": int(interval.value) if interval else 60,
            "total_results": total,
            "last_result_at": to_utc_iso(last_timestamp),
        })
    finally:
        db.close()

@app.route("/api/history/<int:id>", methods=["DELETE"])
def delete_speedtest(id):
    """
    Delete a specific speedtest result
    """
    db: Session = SessionLocal()
    try:
        record = db.query(SpeedTestResult).filter(SpeedTestResult.id == id).first()
        if record:
            db.delete(record)
            db.commit()
            return jsonify({"message": f"Deleted record {id}"}), 200
        return jsonify({"error": "Record not found"}), 404
    except SQLAlchemyError as e:
        logger.error(f"Error deleting record: {e}")
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()

@app.route("/api/history/all", methods=["DELETE"])
def delete_all_speedtests():
    """
    Delete all speedtest results
    """
    db: Session = SessionLocal()
    try:
        db.query(SpeedTestResult).delete()
        db.commit()
        return jsonify({"message": "All records deleted"}), 200
    except SQLAlchemyError as e:
        logger.error(f"Error deleting all records: {e}")
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()

@app.route("/api/reports", methods=["GET"])
def get_reports():
    """
    List all configured reports
    ---
    responses:
      200:
        description: A list of report configurations
    """
    db: Session = SessionLocal()
    try:
        reports = db.query(ReportConfig).all()
        return jsonify([
            {
                "id": r.id,
                "name": r.name,
                "type": r.type,
                "schedule": r.schedule,
                "recipient": r.recipient,
                "data_window": r.data_window or "last_day",
                "enabled": r.enabled,
                "last_run": to_utc_iso(r.last_run),
                "next_run": next_cron_run(r.schedule or "", r.last_run) if r.enabled else None
            } for r in reports
        ])
    finally:
        db.close()

@app.route("/api/reports", methods=["POST"])
def create_report():
    """
    Create a new report configuration
    ---
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            name: { type: string }
            type: { type: string, default: telegram }
            schedule: { type: string }
            recipient: { type: string }
            enabled: { type: boolean, default: true }
    responses:
      201:
        description: Report created successfully
    """
    data = request.get_json(silent=True) or {}
    error = validate_report_payload(data, partial=False)
    if error:
        return jsonify({"error": error}), 400
    db: Session = SessionLocal()
    try:
        if db.query(ReportConfig).filter(ReportConfig.name == data["name"].strip()).first():
            return jsonify({"error": f"A report named '{data['name'].strip()}' already exists"}), 409
        new_report = ReportConfig(
            name=data["name"].strip(),
            type=data.get("type", "telegram"),
            schedule=data["schedule"].strip(),
            recipient=data["recipient"].strip(),
            data_window=data.get("data_window", "last_day"),
            enabled=data.get("enabled", True)
        )
        db.add(new_report)
        db.commit()
        db.refresh(new_report)
        return jsonify({"message": "Report created"}), 201
    except SQLAlchemyError as e:
        logger.error(f"Error creating report: {e}")
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()

@app.route("/api/reports/<int:id>", methods=["PUT"])
def update_report(id):
    """
    Update an existing report configuration
    """
    data = request.get_json(silent=True) or {}
    error = validate_report_payload(data, partial=True)
    if error:
        return jsonify({"error": error}), 400
    db: Session = SessionLocal()
    try:
        report = db.query(ReportConfig).filter(ReportConfig.id == id).first()
        if not report:
            return jsonify({"error": "Report not found"}), 404
            
        if "name" in data: report.name = data["name"]
        if "type" in data: report.type = data["type"]
        if "schedule" in data: 
            report.schedule = data["schedule"]
            # Reset last_run so new schedule takes effect immediately
            report.last_run = None
        if "recipient" in data: report.recipient = data["recipient"]
        if "data_window" in data: report.data_window = data["data_window"]
        if "enabled" in data: report.enabled = data["enabled"]
        
        db.commit()
        return jsonify({"message": f"Report {id} updated"}), 200
    except SQLAlchemyError as e:
        logger.error(f"Error updating report: {e}")
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()

@app.route("/api/reports/<int:id>", methods=["DELETE"])
def delete_report(id):
    """
    Delete a report configuration
    """
    db: Session = SessionLocal()
    try:
        report = db.query(ReportConfig).filter(ReportConfig.id == id).first()
        if not report:
            return jsonify({"error": "Report not found"}), 404
            
        db.delete(report)
        db.commit()
        return jsonify({"message": f"Report {id} deleted"}), 200
    except SQLAlchemyError as e:
        logger.error(f"Error deleting report: {e}")
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()

@app.route("/api/settings", methods=["GET"])
def get_settings():
    """
    Get all application settings
    ---
    responses:
      200:
        description: A dictionary of key-value settings
    """
    db: Session = SessionLocal()
    try:
        settings = db.query(AppSettings).all()
        data = {s.key: s.value for s in settings}
        stored_token = data.pop("telegram_bot_token", None)
        data["has_env_token"] = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
        data["has_db_token"] = bool(stored_token)
        return jsonify(data)
    finally:
        db.close()

@app.route("/api/settings", methods=["POST"])
def update_settings():
    """
    Update application settings
    ---
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            speedtest_interval: { type: integer, example: 60 }
            telegram_bot_token: { type: string }
    responses:
      200:
        description: Settings updated successfully
    """
    data = request.get_json(silent=True) or {}
    if "speedtest_interval" in data:
        try:
            if int(data["speedtest_interval"]) < 1:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "speedtest_interval must be a positive integer"}), 400
    for key in ("advertised_download", "advertised_upload"):
        if key in data:
            try:
                if float(data[key]) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({"error": f"{key} must be a non-negative number"}), 400
    db: Session = SessionLocal()
    try:
        updated_keys = []
        for key, value in data.items():
            # If token is provided but it already exists in ENV, skip updating DB for security
            if key == "telegram_bot_token" and os.getenv("TELEGRAM_BOT_TOKEN"):
                continue
                
            setting = db.query(AppSettings).filter(AppSettings.key == key).first()
            if not setting:
                setting = AppSettings(key=key, value=str(value))
                db.add(setting)
            else:
                setting.value = str(value)
            
            # Special handling for interval change
            if key == "speedtest_interval":
                update_speedtest_interval(int(value))
            
            updated_keys.append(key)
        
        db.commit()
        return jsonify({"message": f"Updated settings: {', '.join(updated_keys)}"}), 200
    except SQLAlchemyError as e:
        logger.error(f"Error updating settings: {e}")
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()

@app.route("/api/debug/scheduler", methods=["GET"])
def debug_scheduler():
    """
    Inspect the background scheduler jobs
    ---
    responses:
      200:
        description: State of current jobs
    """
    jobs = scheduler.get_jobs()
    return jsonify([
        {
            "id": j.id,
            "next_run_time": to_utc_iso(j.next_run_time),
            "trigger": str(j.trigger),
            "pending": j.pending
        } for j in jobs
    ])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
