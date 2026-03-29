from sqlalchemy import create_engine, text, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DATABASE_URL = f"sqlite:///{DATA_DIR}/speedtest.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def run_migrations():
    """Add any missing columns to existing tables."""
    inspector = inspect(engine)

    if "speedtests" in inspector.get_table_names():
        existing = {col["name"] for col in inspector.get_columns("speedtests")}
        migrations = {
            "advertised_download": "ALTER TABLE speedtests ADD COLUMN advertised_download FLOAT",
            "advertised_upload": "ALTER TABLE speedtests ADD COLUMN advertised_upload FLOAT",
        }
        with engine.begin() as conn:
            for col_name, ddl in migrations.items():
                if col_name not in existing:
                    conn.execute(text(ddl))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
