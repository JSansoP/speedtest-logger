import speedtest
from sqlalchemy.orm import Session
from datetime import datetime
from backend.database import SessionLocal, engine
from backend.models import SpeedTestResult, AppSettings, Base
import logging

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

def run_speedtest():
    """
    Executes a speedtest using the speedtest-cli library and logs the result to the DB.
    """
    logger.info("Starting speedtest...")
    try:
        st = speedtest.Speedtest()
        st.get_best_server()
        
        # Performance: download() and upload() return bits per second. Divide by 10**6 for Mbps.
        download_bps = st.download()
        logger.info(f"Download complete: {download_bps / 10**6:.2f} Mbps")
        
        upload_bps = st.upload()
        logger.info(f"Upload complete: {upload_bps / 10**6:.2f} Mbps")
        
        ping = st.results.ping
        results_dict = st.results.dict()
        
        server = results_dict.get('server', {})
        server_name = server.get('name', 'Unknown')
        server_id = str(server.get('id', 'N/A'))

        db: Session = SessionLocal()
        try:
            adv_download, adv_upload = _get_advertised_speeds(db)
            new_result = SpeedTestResult(
                download=download_bps / 10**6,
                upload=upload_bps / 10**6,
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
            logger.info(f"Speedtest result saved: {new_result.id}")
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
