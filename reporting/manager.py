from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.models import ReportConfig, SpeedTestResult, AppSettings
from datetime import datetime, timedelta, timezone
from croniter import croniter
from .providers.telegram import send_telegram_message
import logging
import os
import asyncio
import statistics

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Maps data_window values to timedelta offsets
DATA_WINDOW_MAP = {
    "last_day": timedelta(days=1),
    "last_week": timedelta(weeks=1),
    "last_month": timedelta(days=30),
    "last_3_months": timedelta(days=90),
    "last_6_months": timedelta(days=180),
    "last_year": timedelta(days=365),
}

# Human-friendly labels for the report message
DATA_WINDOW_LABELS = {
    "last_day": "Last 24 Hours",
    "last_week": "Last 7 Days",
    "last_month": "Last 30 Days",
    "last_3_months": "Last 3 Months",
    "last_6_months": "Last 6 Months",
    "last_year": "Last Year",
}

def sync_run_reports():
    asyncio.run(run_reports())

async def run_reports():
    """
    Checks for all enabled report configurations and sends them if needed.
    """
    db: Session = SessionLocal()
    try:
        reports = db.query(ReportConfig).filter(ReportConfig.enabled == True).all()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        
        for report in reports:
            # Check schedule using cron expression
            if report.last_run:
                schedule = str(report.schedule).strip()
                try:
                    cron = croniter(schedule, report.last_run)
                    next_run = cron.get_next(datetime)
                    if now < next_run:
                        continue
                except (ValueError, KeyError) as e:
                    logger.warning(f"Invalid cron expression '{schedule}' for report '{report.name}': {e}")
                    continue
            
            # Determine data window from report config (default to last_day)
            window_key = report.data_window or "last_day"
            window_delta = DATA_WINDOW_MAP.get(window_key, timedelta(days=1))
            window_label = DATA_WINDOW_LABELS.get(window_key, "Last 24 Hours")
            cutoff = now - window_delta

            # Fetch data within the configured window
            data = db.query(SpeedTestResult).filter(SpeedTestResult.timestamp >= cutoff).all()
            
            if not data:
                logger.info(f"No data for report: {report.name} (window: {window_label})")
                continue
                
            downloads = [d.download for d in data]
            uploads = [d.upload for d in data]
            pings = [d.ping for d in data]

            avg_download = statistics.mean(downloads)
            med_download = statistics.median(downloads)
            std_download = statistics.stdev(downloads) if len(downloads) > 1 else 0.0
            min_download = min(downloads)
            max_download = max(downloads)

            avg_upload = statistics.mean(uploads)
            med_upload = statistics.median(uploads)
            std_upload = statistics.stdev(uploads) if len(uploads) > 1 else 0.0
            min_upload = min(uploads)
            max_upload = max(uploads)

            avg_ping = statistics.mean(pings)
            med_ping = statistics.median(pings)
            std_ping = statistics.stdev(pings) if len(pings) > 1 else 0.0
            min_ping = min(pings)
            max_ping = max(pings)

            # Per-row percentage calculations using each row's stored advertised speed
            pct_downloads = [(d.download / d.advertised_download) * 100 for d in data if d.advertised_download and d.advertised_download > 0]
            pct_uploads = [(d.upload / d.advertised_upload) * 100 for d in data if d.advertised_upload and d.advertised_upload > 0]

            message = (
                f"🚀 *Speedtest Report: {report.name}*\n"
                f"📅 {window_label} Summary · {len(data)} tests\n"
                f"{'─' * 28}\n\n"
                f"⬇️ *Download (Mbps)*\n"
                f"  Avg: {avg_download:.2f}  ·  Med: {med_download:.2f}\n"
                f"  Std: {std_download:.2f}  ·  Min: {min_download:.2f}  ·  Max: {max_download:.2f}\n"
            )
            if pct_downloads:
                avg_pct_download = statistics.mean(pct_downloads)
                message += f"  📶 {avg_pct_download:.1f}% of advertised (per-test avg)\n"
            message += (
                f"\n⬆️ *Upload (Mbps)*\n"
                f"  Avg: {avg_upload:.2f}  ·  Med: {med_upload:.2f}\n"
                f"  Std: {std_upload:.2f}  ·  Min: {min_upload:.2f}  ·  Max: {max_upload:.2f}\n"
            )
            if pct_uploads:
                avg_pct_upload = statistics.mean(pct_uploads)
                message += f"  📶 {avg_pct_upload:.1f}% of advertised (per-test avg)\n"
            message += (
                f"\n🏓 *Ping (ms)*\n"
                f"  Avg: {avg_ping:.1f}  ·  Med: {med_ping:.1f}\n"
                f"  Std: {std_ping:.1f}  ·  Min: {min_ping:.1f}  ·  Max: {max_ping:.1f}"
            )
            
            if report.type == "telegram":
                # Priority: 1. Environment Variable, 2. Database
                bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                if not bot_token:
                    token_setting = db.query(AppSettings).filter(AppSettings.key == "telegram_bot_token").first()
                    bot_token = token_setting.value if token_setting else None
                
                if bot_token:
                    await send_telegram_message(bot_token, report.recipient, message)
                    report.last_run = now
                    db.commit()
                    logger.info(f"Report sent to Telegram: {report.name}")
                else:
                    logger.warning(f"Telegram token not found (env or DB) for report: {report.name}")

    finally:
        db.close()
