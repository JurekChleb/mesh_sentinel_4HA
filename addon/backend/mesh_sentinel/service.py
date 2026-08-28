"""Wiring: collectors, detectors, correlation and the periodic jobs.

Everything that touches wall-clock scheduling lives here so the detection layer
below stays a pure function of (events, now).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from . import retention, supervisor
from .clock import Clock
from .collectors import HomeAssistantCollector, Z2MCollector
from .config import Settings
from .correlation import CorrelationEngine
from .correlation.engine import EvaluationResult
from .detectors import DegradationDetector, StalenessDetector
from .models import EVT_ADDON_START, Event, Snapshot
from .storage import Database, Repository

_LOGGER = logging.getLogger(__name__)

NETWORK_ID = "z2m"


class MeshSentinelService:
    def __init__(
        self,
        settings: Settings,
        clock: Clock | None = None,
        repository: Repository | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock or Clock()
        if repository is not None:
            self.repo = repository
            self._db: Database | None = None
        else:
            self._db = Database(settings.db_path)
            self.repo = Repository(self._db)

        self.staleness = StalenessDetector(self.repo, settings)
        self.degradation = DegradationDetector(self.repo, settings)
        self.engine = CorrelationEngine(self.repo, settings, network_id=NETWORK_ID)
        self.z2m = Z2MCollector(self.repo, settings, self.clock)
        self.hass = HomeAssistantCollector(self.repo, settings, self.clock)

        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[Any]] = []
        self._started_at: float | None = None
        self._last_evaluation: float | None = None

    # -- lifecycle -----------------------------------------------------------
    async def start(self) -> None:
        supervisor.resolve_mqtt(self.settings)
        self._started_at = self.clock.now()
        self.repo.add_event(
            Event(
                ts=self._started_at,
                source="mesh_sentinel",
                event_type=EVT_ADDON_START,
                network_id=NETWORK_ID,
                payload={"retention_days": self.settings.effective_retention_days},
            )
        )
        self._stop.clear()
        if self.settings.z2m_enabled:
            self._spawn(self.z2m.run(self._stop), "z2m-collector")
        if self.settings.ha_enabled:
            self._spawn(self.hass.run(self._stop), "hass-collector")
        self._spawn(self._evaluation_loop(), "evaluation")
        self._spawn(self._topology_loop(), "topology")
        self._spawn(self._coordinator_check_loop(), "coordinator-check")
        self._spawn(self._retention_loop(), "retention")
        _LOGGER.info("Mesh Sentinel started with %s background tasks", len(self._tasks))

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # shutdown is best effort
                _LOGGER.debug("Background task ended with an error", exc_info=True)
        self._tasks.clear()
        if self._db is not None:
            self._db.close()

    def _spawn(self, coro: Any, name: str) -> None:
        self._tasks.append(asyncio.create_task(coro, name=name))

    # -- the one synchronous detection pass ----------------------------------
    def evaluate_once(self, now: float | None = None) -> EvaluationResult:
        moment = self.clock.now() if now is None else now
        self.staleness.run(moment)
        self.degradation.run(moment)
        result = self.engine.evaluate(moment)
        self._last_evaluation = moment
        if result.created:
            # A fresh incident deserves a snapshot of the network as it is right
            # now, so the before/after view has an 'after' to show.
            self.take_topology_snapshot(moment, reason="incident")
        return result

    def take_topology_snapshot(self, now: float, reason: str = "scheduled") -> None:
        devices = self.repo.list_devices(NETWORK_ID)
        nodes = [
            {
                "device_id": d.id,
                "friendly_name": d.friendly_name,
                "device_type": d.device_type,
                "availability": d.availability,
                "linkquality": d.linkquality,
                "battery": d.battery,
                "parent_id": d.parent_id,
                "last_seen": d.last_seen,
            }
            for d in devices
        ]
        links = [
            {"child": d.id, "parent": d.parent_id, "linkquality": d.linkquality}
            for d in devices
            if d.parent_id
        ]
        self.repo.add_topology_snapshot(
            now, NETWORK_ID, {"nodes": nodes, "links": links}, kind="passive", reason=reason
        )
        for device in devices:
            self.repo.add_snapshot(
                Snapshot(
                    ts=now,
                    device_id=device.id,
                    availability=device.availability,
                    last_seen=device.last_seen,
                    linkquality=device.linkquality,
                    battery=device.battery,
                    parent_id=device.parent_id,
                    payload={"origin": "periodic"},
                )
            )

    # -- loops ---------------------------------------------------------------
    async def _evaluation_loop(self) -> None:
        interval = self.settings.evaluation_interval_seconds
        while not self._stop.is_set():
            try:
                await asyncio.get_running_loop().run_in_executor(None, self.evaluate_once)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Evaluation pass failed")
            await self._sleep(interval)

    async def _topology_loop(self) -> None:
        passive = max(1, self.settings.topology_snapshot_interval_minutes) * 60
        active = max(30, self.settings.topology_active_scan_interval_minutes) * 60
        last_active = 0.0
        while not self._stop.is_set():
            now = self.clock.now()
            try:
                self.take_topology_snapshot(now)
                if self.settings.topology_active_scan and now - last_active >= active:
                    # An active scan floods the mesh with route requests, so it is
                    # opt-in and rate-limited to its own, much longer interval.
                    if await self.z2m.request_networkmap():
                        last_active = now
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Topology snapshot failed")
            await self._sleep(passive)

    async def _coordinator_check_loop(self) -> None:
        interval = max(1, self.settings.coordinator_check_interval_minutes) * 60
        while not self._stop.is_set():
            await self._sleep(interval)
            if self._stop.is_set():
                break
            try:
                await self.z2m.request_health_check()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Coordinator health check failed")

    async def _retention_loop(self) -> None:
        interval = max(5, self.settings.retention_interval_minutes) * 60
        while not self._stop.is_set():
            try:
                retention.purge(self.repo, self.settings, self.clock.now())
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Retention pass failed")
            await self._sleep(interval)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    # -- status --------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "started_at": self._started_at,
            "last_evaluation": self._last_evaluation,
            "edition": self.settings.edition,
            "retention_days": self.settings.effective_retention_days,
            "sources": {
                "zigbee2mqtt": {
                    "enabled": self.settings.z2m_enabled,
                    "connected": self.z2m.connected,
                    "base_topic": self.settings.z2m_base_topic,
                    "broker": f"{self.settings.mqtt_host}:{self.settings.mqtt_port}",
                },
                "home_assistant": {
                    "enabled": self.settings.ha_enabled,
                    "connected": self.hass.connected,
                    "url": self.settings.ha_url,
                },
                "zha": {"enabled": False, "connected": False, "note": "Planned for 0.2.0"},
            },
        }
