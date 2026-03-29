from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from .worker import run_speedtest
from backend.database import SessionLocal
from backend.models import AppSettings
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = BackgroundScheduler()

def get_interval_from_db():
    db = SessionLocal()
    try:
        interval_setting = db.query(AppSettings).filter(AppSettings.key == "speedtest_interval").first()
        return int(interval_setting.value) if interval_setting else 60
    finally:
        db.close()

def update_speedtest_interval(minutes: int):
    """
    Update the speedtest job schedule dynamically.
    """
    logger.info(f"Rescheduling speedtest job to {minutes} minutes")
    try:
        scheduler.reschedule_job(
            job_id="speedtest_job",
            trigger=IntervalTrigger(minutes=minutes)
        )
        return True
    except Exception as e:
        logger.error(f"Failed to reschedule job: {e}")
        return False

def start_scheduler():
    interval_minutes = get_interval_from_db()
    
    logger.info(f"Adding speedtest job with interval: {interval_minutes} minutes")
    scheduler.add_job(
        run_speedtest,
        IntervalTrigger(minutes=interval_minutes),
        id="speedtest_job",
        replace_existing=True
    )

    scheduler.start()
    logger.info("Scheduler started.")
    return scheduler

if __name__ == "__main__":
    start_scheduler()
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
