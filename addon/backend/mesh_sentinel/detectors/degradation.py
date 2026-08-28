"""Detects a device that is still reachable but getting worse.

Two signals, both cheap and both available from Zigbee2MQTT without polling:
falling link quality across snapshots, and a rising count of publish
timeouts / errors reported by the bridge for one device.
"""

from __future__ import annotations

from ..config import Settings
from ..models import (
    EVT_DEVICE_DEGRADED,
    EVT_DEVICE_ERROR,
    EVT_DEVICE_TIMEOUT,
    Event,
)
from ..storage import Repository

ERROR_WINDOW_SECONDS = 3600.0
ERROR_THRESHOLD = 5
MIN_SAMPLES = 3


class DegradationDetector:
    def __init__(self, repo: Repository, settings: Settings) -> None:
        self._repo = repo
        self._settings = settings

    def run(self, now: float) -> list[Event]:
        emitted: list[Event] = []
        for device in self._repo.list_devices():
            if device.disabled or device.availability == "offline":
                continue
            reasons = []

            errors = self._repo.events_between(
                now - ERROR_WINDOW_SECONDS,
                now,
                event_types=[EVT_DEVICE_TIMEOUT, EVT_DEVICE_ERROR],
                device_id=device.id,
            )
            if len(errors) >= ERROR_THRESHOLD:
                reasons.append(
                    {
                        "signal": "error_rate",
                        "count": len(errors),
                        "window_seconds": ERROR_WINDOW_SECONDS,
                    }
                )

            trend = self._linkquality_trend(device.id, now)
            if trend is not None:
                reasons.append(trend)

            if not reasons:
                continue

            # One open degradation event per device per hour is plenty.
            recent = self._repo.events_between(
                now - ERROR_WINDOW_SECONDS,
                now,
                event_types=[EVT_DEVICE_DEGRADED],
                device_id=device.id,
            )
            if recent:
                continue

            event = Event(
                ts=now,
                source="mesh_sentinel",
                event_type=EVT_DEVICE_DEGRADED,
                severity="warning",
                device_id=device.id,
                network_id=device.network_id,
                payload={"reasons": reasons},
            )
            self._repo.add_event(event)
            emitted.append(event)
        return emitted

    def _linkquality_trend(self, device_id: str, now: float) -> dict | None:
        snapshots = self._repo.snapshots_for_device(device_id, now - 24 * 3600.0)
        values = [s.linkquality for s in snapshots if s.linkquality is not None]
        if len(values) < MIN_SAMPLES * 2:
            return None
        recent = values[-MIN_SAMPLES:]
        baseline = values[:-MIN_SAMPLES]
        recent_avg = sum(recent) / len(recent)
        baseline_avg = sum(baseline) / len(baseline)
        if recent_avg >= self._settings.linkquality_degraded:
            return None
        if baseline_avg < self._settings.linkquality_degraded * 1.5:
            # It has always been weak; that is a placement problem, not a trend.
            return None
        return {
            "signal": "linkquality_drop",
            "baseline_avg": round(baseline_avg, 1),
            "recent_avg": round(recent_avg, 1),
            "samples": len(values),
        }
