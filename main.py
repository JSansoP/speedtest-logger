import threading
import os
import sys
import logging
import time
from backend.api import app as flask_app
from collector.scheduler import start_scheduler
from backend.database import engine, Base, run_migrations

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MainOrchestrator")

def run_flask():
    """Starts the Flask API."""
    logger.info("Starting Flask API on http://0.0.0.0:5000...")
    flask_app.run(host="0.0.0.0", port=5000, use_reloader=False)

def main():
    """Main entry point for Speedtest Logger."""
    # Ensure database tables are created
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)
    run_migrations()
    logger.info("Database migrations complete.")
    
    # Start Scheduler in background
    logger.info("Starting Scheduler...")
    scheduler = start_scheduler()
    
    # Start Flask API in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    logger.info("Speedtest Logger core services are running.")
    logger.info("Instructions:")
    logger.info("1. API is running on http://localhost:5000")
    logger.info("2. To start the dashboard, run: uv run streamlit run app.py")
    
    try:
        # Keep main thread alive
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down services...")
        scheduler.shutdown()
        sys.exit(0)

if __name__ == "__main__":
    main()
