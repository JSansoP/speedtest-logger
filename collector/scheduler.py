from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from .worker import run_speedtest
from backend.database import SessionLocal
from backend.models import AppSettings
import logging
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Scheduler")

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
    logger.info(f"Dynamically updating speedtest interval to {minutes} minutes")
    try:
        # Check if job exists
        job = scheduler.get_job("speedtest_job")
        if job:
            logger.info(f"Existing job found. Rescheduling. Next run was: {job.next_run_time}")
            scheduler.reschedule_job(
                job_id="speedtest_job",
                trigger=IntervalTrigger(minutes=minutes)
            )
            logger.info("Reschedule successful.")
        else:
            logger.warning("Job 'speedtest_job' not found. Creating a new one.")
            scheduler.add_job(
                run_speedtest,
                IntervalTrigger(minutes=minutes),
                id="speedtest_job",
                replace_existing=True,
                misfire_grace_time=30
            )
            logger.info("New job created.")
        return True
    except Exception as e:
        logger.error(f"Failed to update interval: {e}")
        return False

def start_scheduler():
    interval_minutes = get_interval_from_db()
    
    logger.info(f"Starting scheduler: Initial interval is {interval_minutes} minutes")
    
    # We use a unique ID "speedtest_job" so we can find it later
    # We add a 30s grace time for misfires (if the machine is overloaded)
    scheduler.add_job(
        run_speedtest,
        IntervalTrigger(minutes=interval_minutes),
        id="speedtest_job",
        replace_existing=True,
        misfire_grace_time=30,
        next_run_time=datetime.now() # Run first time immediately
    )

    scheduler.start()
    logger.info(f"Scheduler started with jobs: {[j.id for j in scheduler.get_jobs()]}")
    return scheduler

if __name__ == "__main__":
    start_scheduler()
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
