"""ICMP probing layer. Everything that touches the network lives here so tests can replace it."""

import asyncio
import itertools
import logging
import statistics
import threading
from dataclasses import dataclass, field

from icmplib import async_multiping, ping

logger = logging.getLogger(__name__)

PROBE_COUNT = 10
PROBE_INTERVAL = 0.5
PROBE_TIMEOUT = 2
LOAD_PROBE_HOST = "1.1.1.1"


@dataclass
class ProbeResult:
    sent: int
    rtts: list[float] = field(default_factory=list)

    @property
    def received(self) -> int:
        return len(self.rtts)


def probe_hosts(hosts: list[str]) -> dict[str, ProbeResult]:
    """Pings every host concurrently and returns the raw round trip times per host."""
    if not hosts:
        return {}
    results = asyncio.run(
        async_multiping(
            hosts,
            count=PROBE_COUNT,
            interval=PROBE_INTERVAL,
            timeout=PROBE_TIMEOUT,
            privileged=True,
        )
    )
    return {r.address: ProbeResult(sent=r.packets_sent, rtts=list(r.rtts)) for r in results}


def summarize(result: ProbeResult) -> dict:
    """Reduces raw round trip times to the aggregate stored per round."""
    rtts = result.rtts
    if not rtts:
        return {"sent": result.sent, "received": 0, "min": None, "median": None, "avg": None, "max": None, "jitter": None}
    jitter = statistics.mean(abs(b - a) for a, b in itertools.pairwise(rtts)) if len(rtts) > 1 else 0.0
    return {
        "sent": result.sent,
        "received": len(rtts),
        "min": min(rtts),
        "median": statistics.median(rtts),
        "avg": statistics.mean(rtts),
        "max": max(rtts),
        "jitter": jitter,
    }


class LoadSampler:
    """Pings a host in a background thread while a speedtest runs and reports the median latency."""

    def __init__(self, host: str = LOAD_PROBE_HOST, interval: float = PROBE_INTERVAL):
        self.host = host
        self.interval = interval
        self.rtts: list[float] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                reply = ping(self.host, count=1, timeout=PROBE_TIMEOUT, privileged=True)
                if reply.is_alive:
                    self.rtts.append(reply.avg_rtt)
            except Exception as e:  # noqa: BLE001
                logger.warning("Load latency probe failed: %s", e)
                return
            self._stop.wait(self.interval)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=PROBE_TIMEOUT + 1)

    @property
    def median(self) -> float | None:
        return statistics.median(self.rtts) if self.rtts else None
