"""Turns 'we have not heard from this device' into a normalised event.

Zigbee2MQTT publishes availability only when the availability feature is on, and
even then a battery device can be legitimately quiet for hours. So the threshold
depends on the power source, and a device is never marked offline before it has
been seen at least once.
"""

from __future__ import annotations

import logging

from ..config import Settings
from ..models import (
    EVT_DEVICE_OFFLINE,
    EVT_DEVICE_ONLINE,
    Device,
    Event,
)
from ..storage import Repository

_LOGGER = logging.getLogger(__name__)


class StalenessDetector:
    def __init__(self, repo: Repository, settings: Settings) -> None:
        self._repo = repo
        self._settings = settings

    def stale_after(self, device: Device) -> float:
        if device.is_battery:
            return self._settings.battery_stale_hours * 3600.0
        return self._settings.mains_stale_minutes * 60.0

    def run(self, now: float) -> list[Event]:
        """Emit offline events for devices that went quiet past their budget."""

        emitted: list[Event] = []
        for device in self._repo.list_devices():
            if device.disabled or device.device_type == "coordinator":
                continue
            if device.last_seen is None:
                # Never heard from - not the same as "went away".
                continue
            silence = now - device.last_seen
            budget = self.stale_after(device)
            if silence <= budget:
                continue
            if device.availability == "offline":
                continue
            event = Event(
                ts=now,
                source="mesh_sentinel",
                event_type=EVT_DEVICE_OFFLINE,
                severity="warning",
                device_id=device.id,
                network_id=device.network_id,
                payload={
                    "reason": "stale",
                    "silence_seconds": round(silence),
                    "budget_seconds": round(budget),
                    "last_seen": device.last_seen,
                },
            )
            self._repo.add_event(event)
            self._repo.set_availability(device.id, "offline", now)
            emitted.append(event)
            _LOGGER.info(
                "Device %s marked offline after %ss of silence (budget %ss)",
                device.friendly_name or device.id,
                round(silence),
                round(budget),
            )
        return emitted

    def mark_online(self, device: Device, now: float) -> Event | None:
        """Called by collectors when a device speaks again."""

        if device.availability == "online":
            return None
        event = Event(
            ts=now,
            source="mesh_sentinel",
            event_type=EVT_DEVICE_ONLINE,
            device_id=device.id,
            network_id=device.network_id,
            payload={"reason": "message_received"},
        )
        self._repo.add_event(event)
        self._repo.set_availability(device.id, "online", now)
        return event
