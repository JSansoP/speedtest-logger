"""Optional heartbeat pings to heartbeat-monitor after each speedtest.

Sending a heartbeat must never break or slow down a speedtest: short timeout,
every error is caught and only logged, and nothing is sent when HEARTBEAT_URL
is unset.
"""

import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

TIMEOUT = 5


def send(suffix: str = "") -> bool:
    """GET HEARTBEAT_URL, or HEARTBEAT_URL/<suffix> (e.g. "fail"). Returns True on HTTP 200."""
    base = os.getenv("HEARTBEAT_URL", "").strip()
    if not base:
        return False
    url = base.rstrip("/") + (f"/{suffix}" if suffix else "")
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            return response.status == 200
    except Exception as e:  # noqa: BLE001
        logger.warning("Heartbeat %s failed: %s", suffix or "success", e)
        return False
