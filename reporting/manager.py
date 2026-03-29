from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.models import ReportConfig, SpeedTestResult, AppSettings
from datetime import datetime, timedelta, timezone
from .providers.telegram import send_telegram_message
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_reports():
    """
    Checks for all enabled report configurations and sends them if needed.
    """
    db: Session = SessionLocal()
    try:
        reports = db.query(ReportConfig).filter(ReportConfig.enabled == True).all()
        for report in reports:
            # Fetch latest data for summary
            last_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            data = db.query(SpeedTestResult).filter(SpeedTestResult.timestamp >= last_24h.replace(tzinfo=None)).all()
            
            if not data:
                logger.info(f"No data for report: {report.name}")
                continue
                
            avg_download = sum(d.download for d in data) / len(data)
            avg_upload = sum(d.upload for d in data) / len(data)
            max_download = max(d.download for d in data)
            
            message = (
                f"🚀 *Speedtest Report: {report.name}*\n"
                f"📅 Last 24 Hours Summary\n\n"
                f"⬇️ Avg Download: {avg_download:.2f} Mbps\n"
                f"⬆️ Avg Upload: {avg_upload:.2f} Mbps\n"
                f"📊 Max Download: {max_download:.2f} Mbps\n"
                f"📈 Total Tests: {len(data)}"
            )
            
            if report.type == "telegram":
                # Priority: 1. Environment Variable, 2. Database
                bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                if not bot_token:
                    token_setting = db.query(AppSettings).filter(AppSettings.key == "telegram_bot_token").first()
                    bot_token = token_setting.value if token_setting else None
                
                if bot_token:
                    await send_telegram_message(bot_token, report.recipient, message)
                    report.last_run = datetime.now(timezone.utc).replace(tzinfo=None)
                    db.commit()
                    logger.info(f"Report sent to Telegram: {report.name}")
                else:
                    logger.warning(f"Telegram token not found (env or DB) for report: {report.name}")

    finally:
        db.close()
