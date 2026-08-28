"""Shared fixtures.

Every test drives a real service against a real SQLite file with a fake clock,
and feeds it the exact MQTT payloads Zigbee2MQTT publishes. No mocks of our own
code: if a test passes, the parsing, the storage and the rules all agree.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "addon" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mesh_sentinel.clock import FakeClock  # noqa: E402
from mesh_sentinel.config import Settings  # noqa: E402
from mesh_sentinel.service import MeshSentinelService  # noqa: E402

T0 = 1_700_000_000.0


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(current=T0)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=str(tmp_path / "mesh_sentinel.db"),
        z2m_enabled=False,
        ha_enabled=False,
        offline_grace_seconds=180,
        recovery_confirm_seconds=120,
        mains_stale_minutes=90,
        battery_stale_hours=24,
    )


@pytest.fixture
def service(settings: Settings, clock: FakeClock) -> MeshSentinelService:
    return MeshSentinelService(settings, clock=clock)


class Network:
    """Small harness that speaks Zigbee2MQTT on behalf of a test."""

    def __init__(self, service: MeshSentinelService, clock: FakeClock) -> None:
        self.service = service
        self.clock = clock
        self.handler = service.z2m.handler
        self.base = service.settings.z2m_base_topic

    # -- inbound MQTT --------------------------------------------------------
    def publish(self, topic: str, payload, retained: bool = False):
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        return self.handler.handle(f"{self.base}/{topic}", payload, self.clock.now(), retained)

    def announce_devices(self, devices: list[dict]) -> None:
        self.publish("bridge/devices", devices)

    def bridge_state(self, state: str) -> None:
        self.publish("bridge/state", {"state": state})

    def availability(self, friendly_name: str, state: str) -> None:
        self.publish(f"{friendly_name}/availability", {"state": state})

    def report(self, friendly_name: str, **payload) -> None:
        self.publish(friendly_name, payload or {"linkquality": 90})

    def log(self, level: str, message: str) -> None:
        self.publish("bridge/logging", {"level": level, "message": message})

    def health_check(self, healthy: bool) -> None:
        self.publish(
            "bridge/response/health_check",
            {"status": "ok" if healthy else "error", "data": {"healthy": healthy}},
        )

    def networkmap(self, nodes: list[dict], links: list[dict]) -> None:
        self.publish(
            "bridge/response/networkmap",
            {"status": "ok", "data": {"value": {"nodes": nodes, "links": links}}},
        )

    # -- time and evaluation -------------------------------------------------
    def advance(self, seconds: float) -> float:
        return self.clock.advance(seconds)

    def evaluate(self):
        return self.service.evaluate_once()

    # -- assertions helpers --------------------------------------------------
    def incidents(self, status: str | None = None):
        return self.service.repo.list_incidents(status=status, limit=100)

    def open_incidents(self):
        return self.incidents(status="open")

    def device_id(self, ieee: str) -> str:
        return f"z2m:{ieee.lower()}"


@pytest.fixture
def net(service: MeshSentinelService, clock: FakeClock) -> Network:
    return Network(service, clock)


def device_entry(
    ieee: str,
    name: str,
    device_type: str = "EndDevice",
    power: str = "Battery",
    vendor: str = "IKEA",
    model: str = "E1525",
) -> dict:
    return {
        "ieee_address": ieee,
        "friendly_name": name,
        "type": device_type,
        "power_source": power,
        "supported": True,
        "definition": {"vendor": vendor, "model": model},
    }


def router_entry(ieee: str, name: str) -> dict:
    return device_entry(
        ieee, name, device_type="Router", power="Mains (single phase)", model="LED1836G9"
    )


@pytest.fixture
def small_network(net: Network) -> Network:
    """One router plus four battery sensors, all alive and reporting."""

    net.announce_devices(
        [
            router_entry("0xR1", "IKEA salon"),
            device_entry("0xS1", "Czujnik salon"),
            device_entry("0xS2", "Czujnik kuchnia"),
            device_entry("0xS3", "Czujnik sypialnia"),
            device_entry("0xS4", "Czujnik lazienka"),
        ]
    )
    net.bridge_state("online")
    for name in ("IKEA salon", "Czujnik salon", "Czujnik kuchnia", "Czujnik sypialnia", "Czujnik lazienka"):
        net.availability(name, "online")
        net.report(name, linkquality=90, battery=95)
    return net
