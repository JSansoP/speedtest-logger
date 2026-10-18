"""Telegram alerts for the latency monitor."""

import asyncio
import logging
import os
from datetime import UTC
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.models import AppSettings, LatencyOutage, ReportConfig

from .providers.telegram import send_telegram_message

logger = logging.getLogger(__name__)


def resolve_bot_token(db: Session) -> str | None:
    """Environment variable first, then the token stored in the database."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        return token
    setting = db.query(AppSettings).filter(AppSettings.key == "telegram_bot_token").first()
    return setting.value if setting and setting.value else None


def escape_markdown(text: str) -> str:
    for char in ("_", "*", "`", "["):
        text = text.replace(char, "\\" + char)
    return text


def alert_recipients(db: Session) -> list[str]:
    reports = db.query(ReportConfig).filter(ReportConfig.type == "telegram", ReportConfig.enabled.is_(True)).all()
    return sorted({r.recipient for r in reports if r.recipient})


def send_alert(db: Session, message: str) -> bool:
    """Sends the message to every Telegram recipient of the enabled reports. True if all were delivered."""
    token = resolve_bot_token(db)
    recipients = alert_recipients(db)
    if not token or not recipients:
        logger.warning("Alert not sent: no Telegram token or recipient configured")
        return False
    try:
        for recipient in recipients:
            asyncio.run(send_telegram_message(token, recipient, message))
    except Exception as e:  # noqa: BLE001
        logger.error("Alert delivery failed: %s", e)
        return False
    return True


def _local(value, timezone: str):
    return value.replace(tzinfo=UTC).astimezone(ZoneInfo(timezone))


def format_outage(outage: LatencyOutage, timezone: str) -> str:
    start = _local(outage.started_at, timezone)
    end = _local(outage.ended_at, timezone)
    minutes = max(round((outage.ended_at - outage.started_at).total_seconds() / 60), 1)
    detail = escape_markdown(outage.diagnosis or "")
    return f"Internet outage {start:%H:%M} to {end:%H:%M} ({minutes} min). {detail}".strip()


def format_degradation(affected: list[tuple[str, float]], minutes: int, detail: str) -> str:
    targets = ", ".join(f"{escape_markdown(name)} {loss:.0f}%" for name, loss in affected)
    return f"Sustained packet loss over the last {minutes} min: {targets}. {escape_markdown(detail)}"
