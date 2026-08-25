import subprocess
import json
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from backend.database import SessionLocal, engine
from backend.models import SpeedTestResult, AppSettings, Base

# Ensure tables are created
Base.metadata.create_all(bind=engine)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _get_advertised_speeds(db):
    """Read current advertised speeds from AppSettings."""
    adv_down = db.query(AppSettings).filter(AppSettings.key == "advertised_download").first()
    adv_up = db.query(AppSettings).filter(AppSettings.key == "advertised_upload").first()
    return (
        float(adv_down.value) if adv_down and adv_down.value else None,
        float(adv_up.value) if adv_up and adv_up.value else None,
    )

def _normalize_to_mbps(speed, unit: str | None) -> float:
    """Normalize speed value to Mbps based on unit string."""
    if speed is None:
        return 0.0
    try:
        val = float(speed)
    except (ValueError, TypeError):
        return 0.0

    if not unit:
        return val

    unit_clean = str(unit).strip().lower()
    if unit_clean == "gbps":
        return val * 1000.0
    elif unit_clean == "kbps":
        return val / 1000.0
    elif unit_clean == "bps":
        return val / 1_000_000.0
    # Default assumes Mbps
    return val

def _parse_fast_output(raw_output: str) -> dict:
    """Safely extracts and parses the JSON dictionary from fast-cli output."""
    output = raw_output.strip()
    start_idx = output.find("{")
    end_idx = output.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
        json_str = output[start_idx : end_idx + 1]
        return json.loads(json_str)
    raise ValueError(f"No JSON object found in output: {raw_output}")

def run_speedtest():
    """
    Executes a speedtest using the fast-cli tool (Fast.com) and logs the result to the DB.
    """
    logger.info("Starting speedtest using fast-cli...")
    try:
        cmd = ["fast", "--upload", "--json"]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"fast-cli exited with code {result.returncode}: {error_msg}")

        data = _parse_fast_output(result.stdout)
        logger.info(f"fast-cli raw output: {data}")

        download_mbps = _normalize_to_mbps(data.get("downloadSpeed"), data.get("downloadUnit"))
        upload_mbps = _normalize_to_mbps(data.get("uploadSpeed"), data.get("uploadUnit"))
        ping = float(data.get("latency") or 0.0)

        user_location = data.get("userLocation")
        server_name = f"Fast.com ({user_location})" if user_location else "Fast.com"
        server_id = str(data.get("userIp") or "fast.com")

        logger.info(f"Download: {download_mbps:.2f} Mbps | Upload: {upload_mbps:.2f} Mbps | Latency: {ping:.1f} ms | Server: {server_name}")

        db: Session = SessionLocal()
        try:
            adv_download, adv_upload = _get_advertised_speeds(db)
            new_result = SpeedTestResult(
                download=download_mbps,
                upload=upload_mbps,
                ping=ping,
                server_name=server_name,
                server_id=server_id,
                advertised_download=adv_download,
                advertised_upload=adv_upload,
                timestamp=datetime.utcnow()
            )
            db.add(new_result)
            db.commit()
            db.refresh(new_result)
            logger.info(f"Speedtest result saved: ID={new_result.id}")
            return new_result
        except Exception as e:
            logger.error(f"Error saving to database: {e}")
            db.rollback()
            raise
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Speedtest failed: {e}")
        return None

if __name__ == "__main__":
    # Test run
    run_speedtest()

