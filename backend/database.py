import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATA_DIR}/speedtest.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

DEFAULT_ISP_NAME = "ibred"

def run_migrations():
    """Add any missing columns to existing tables."""
    inspector = inspect(engine)

    if "speedtests" in inspector.get_table_names():
        existing = {col["name"] for col in inspector.get_columns("speedtests")}
        migrations = {
            "advertised_download": "ALTER TABLE speedtests ADD COLUMN advertised_download FLOAT",
            "advertised_upload": "ALTER TABLE speedtests ADD COLUMN advertised_upload FLOAT",
            "loaded_latency": "ALTER TABLE speedtests ADD COLUMN loaded_latency FLOAT",
        }
        with engine.begin() as conn:
            for col_name, ddl in migrations.items():
                if col_name not in existing:
                    conn.execute(text(ddl))
            if "isp_name" not in existing:
                conn.execute(text("ALTER TABLE speedtests ADD COLUMN isp_name VARCHAR"))
                conn.execute(
                    text("UPDATE speedtests SET isp_name = :name WHERE isp_name IS NULL"),
                    {"name": DEFAULT_ISP_NAME},
                )

    if "app_settings" in inspector.get_table_names():
        with engine.begin() as conn:
            has_setting = conn.execute(text("SELECT 1 FROM app_settings WHERE key = 'isp_name'")).first()
            if not has_setting:
                conn.execute(
                    text("INSERT INTO app_settings (key, value) VALUES ('isp_name', :name)"),
                    {"name": DEFAULT_ISP_NAME},
                )

    if "latency_targets" in inspector.get_table_names():
        with engine.begin() as conn:
            conn.execute(text("UPDATE latency_targets SET layer = 'vpn' WHERE layer = 'tailnet'"))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
