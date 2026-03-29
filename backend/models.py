from sqlalchemy import Column, Integer, Float, String, DateTime, Boolean
from .database import Base
from datetime import datetime

class SpeedTestResult(Base):
    __tablename__ = "speedtests"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    download = Column(Float) # Mbps
    upload = Column(Float)   # Mbps
    ping = Column(Float)     # ms
    server_name = Column(String)
    server_id = Column(String)

class ReportConfig(Base):
    __tablename__ = "report_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    type = Column(String, default="telegram") # 'telegram'
    schedule = Column(String) # Cron expression or 'interval:60' (minutes)
    recipient = Column(String) # e.g. chat_id for telegram
    template = Column(String) # Custom template or 'default'
    enabled = Column(Boolean, default=True)
    last_run = Column(DateTime, nullable=True)

class AppSettings(Base):
    __tablename__ = "app_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    value = Column(String)
