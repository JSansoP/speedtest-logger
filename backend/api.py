from flask import Flask, jsonify, request
from sqlalchemy.orm import Session
from flasgger import Swagger
from .database import SessionLocal, engine
from .models import SpeedTestResult, ReportConfig, AppSettings, Base
from collector.worker import run_speedtest
from collector.scheduler import update_speedtest_interval, scheduler
import threading
import logging
import os

app = Flask(__name__)
swagger = Swagger(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API")

# Ensure tables are created
Base.metadata.create_all(bind=engine)

@app.route("/api/speedtests", methods=["GET"])
def get_speedtests():
    """
    Get latest speedtest results
    ---
    parameters:
      - name: limit
        in: query
        type: integer
        description: Number of results to return
        default: 100
    responses:
      200:
        description: A list of speedtest results
    """
    db: Session = SessionLocal()
    try:
        limit = request.args.get("limit", default=100, type=int)
        results = db.query(SpeedTestResult).order_by(SpeedTestResult.timestamp.desc()).limit(limit).all()
        return jsonify([
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "download": r.download,
                "upload": r.upload,
                "ping": r.ping,
                "server_name": r.server_name
            } for r in results
        ])
    finally:
        db.close()

@app.route("/api/speedtests/run", methods=["POST"])
def trigger_speedtest():
    """
    Trigger a manual speedtest in the background
    ---
    responses:
      200:
        description: Speedtest started message
    """
    thread = threading.Thread(target=run_speedtest)
    thread.start()
    return jsonify({"message": "Speedtest started in background."})

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
    except Exception as e:
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
    except Exception as e:
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
                "enabled": r.enabled,
                "last_run": r.last_run.isoformat() if r.last_run else None
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
    data = request.json
    db: Session = SessionLocal()
    try:
        new_report = ReportConfig(
            name=data["name"],
            type=data.get("type", "telegram"),
            schedule=data["schedule"],
            recipient=data["recipient"],
            enabled=data.get("enabled", True)
        )
        db.add(new_report)
        db.commit()
        db.refresh(new_report)
        return jsonify({"message": "Report created"}), 201
    except Exception as e:
        logger.error(f"Error creating report: {e}")
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()

@app.route("/api/reports/<int:id>", methods=["PUT"])
def update_report(id):
    """
    Update an existing report configuration
    """
    data = request.json
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
        if "enabled" in data: report.enabled = data["enabled"]
        
        db.commit()
        return jsonify({"message": f"Report {id} updated"}), 200
    except Exception as e:
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
    except Exception as e:
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
        
        # Overlay environment variables
        env_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if env_token:
            data["telegram_bot_token"] = "___ENVIORNMENT_VARIABLE___"
            data["has_env_token"] = True
        else:
            data["has_env_token"] = False
            
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
    data = request.json
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
    except Exception as e:
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
            "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
            "trigger": str(j.trigger),
            "pending": j.pending
        } for j in jobs
    ])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
