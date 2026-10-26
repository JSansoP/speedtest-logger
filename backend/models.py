from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, UniqueConstraint

from .database import Base


class SpeedTestResult(Base):
    __tablename__ = "speedtests"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    download = Column(Float) # Mbps
    upload = Column(Float)   # Mbps
    ping = Column(Float)     # ms
    server_name = Column(String)
    server_id = Column(String)
    advertised_download = Column(Float, nullable=True)  # Mbps - ISP promised speed at time of test
    advertised_upload = Column(Float, nullable=True)     # Mbps - ISP promised speed at time of test
    loaded_latency = Column(Float, nullable=True)        # ms - median latency to 1.1.1.1 during the test

class ReportConfig(Base):
    __tablename__ = "report_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    type = Column(String, default="telegram") # 'telegram'
    schedule = Column(String) # Cron expression or 'interval:60' (minutes)
    recipient = Column(String) # e.g. chat_id for telegram
    template = Column(String) # Custom template or 'default'
    data_window = Column(String, default="last_day") # last_day, last_week, last_month, last_3_months, last_6_months, last_year
    enabled = Column(Boolean, default=True)
    last_run = Column(DateTime, nullable=True)

class AppSettings(Base):
    __tablename__ = "app_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    value = Column(String)


class LatencyTarget(Base):
    __tablename__ = "latency_targets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)
    host = Column(String)
    layer = Column(String)  # lan, isp, internet, vpn
    enabled = Column(Boolean, default=True)


class LatencySample(Base):
    """Aggregate of one probe round against one target."""

    __tablename__ = "latency_samples"
    __table_args__ = (Index("ix_latency_samples_target_timestamp", "target_id", "timestamp"),)

    id = Column(Integer, primary_key=True)
    target_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    sent = Column(Integer, nullable=False)
    received = Column(Integer, nullable=False)
    min_ms = Column(Float, nullable=True)
    median_ms = Column(Float, nullable=True)
    avg_ms = Column(Float, nullable=True)
    max_ms = Column(Float, nullable=True)
    jitter_ms = Column(Float, nullable=True)
    under_load = Column(Boolean, default=False)


class LatencyHourly(Base):
    __tablename__ = "latency_hourly"
    __table_args__ = (UniqueConstraint("target_id", "hour", name="uq_latency_hourly_target_hour"),)

    id = Column(Integer, primary_key=True)
    target_id = Column(Integer, nullable=False)
    hour = Column(DateTime, nullable=False)
    min_ms = Column(Float, nullable=True)
    median_ms = Column(Float, nullable=True)
    avg_ms = Column(Float, nullable=True)
    max_ms = Column(Float, nullable=True)
    p95_ms = Column(Float, nullable=True)
    loss_pct = Column(Float, nullable=False)
    samples = Column(Integer, nullable=False)


class LatencyOutage(Base):
    __tablename__ = "latency_outages"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    diagnosis = Column(String, default="")
    reported = Column(Boolean, default=False)
