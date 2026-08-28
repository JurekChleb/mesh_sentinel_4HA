"""Normalised domain objects shared by collectors, detectors and the API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Source = Literal["z2m", "zha", "home_assistant", "mesh_sentinel"]
Severity = Literal["info", "warning", "error", "critical"]
Availability = Literal["online", "offline", "unknown"]

# --- event types -------------------------------------------------------------
# Collectors only ever emit these. Detectors and the correlation engine match on
# them, so adding a vendor-specific string anywhere else is a bug.
EVT_DEVICE_ONLINE = "device_online"
EVT_DEVICE_OFFLINE = "device_offline"
EVT_DEVICE_SEEN = "device_seen"
EVT_DEVICE_JOINED = "device_joined"
EVT_DEVICE_LEFT = "device_left"
EVT_DEVICE_TIMEOUT = "device_timeout"
EVT_DEVICE_ERROR = "device_error"
EVT_DEVICE_LOW_BATTERY = "device_low_battery"
EVT_DEVICE_DEGRADED = "device_degraded"
EVT_ROUTER_MISSING = "router_missing"
EVT_BRIDGE_ONLINE = "bridge_online"
EVT_BRIDGE_OFFLINE = "bridge_offline"
EVT_BRIDGE_RESTART = "bridge_restart"
EVT_COORDINATOR_OK = "coordinator_ok"
EVT_COORDINATOR_MISSING = "coordinator_missing"
EVT_MQTT_CONNECTED = "mqtt_connected"
EVT_MQTT_DISCONNECTED = "mqtt_disconnected"
EVT_HA_RESTART = "home_assistant_restart"
EVT_OTA_UPDATE = "ota_update"
EVT_ADDON_START = "addon_start"
EVT_TOPOLOGY_SNAPSHOT = "topology_snapshot"


@dataclass(slots=True)
class Event:
    ts: float
    source: str
    event_type: str
    severity: str = "info"
    device_id: str | None = None
    network_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass(slots=True)
class Device:
    id: str
    network_id: str
    source: str
    integration: str
    ieee: str | None = None
    friendly_name: str | None = None
    vendor: str | None = None
    model: str | None = None
    device_type: str = "unknown"  # coordinator | router | end_device | unknown
    power_source: str = "unknown"  # battery | mains | unknown
    is_critical: bool = False
    disabled: bool = False
    first_seen: float | None = None
    last_seen: float | None = None
    last_message_at: float | None = None
    availability: str = "unknown"
    availability_since: float | None = None
    parent_id: str | None = None
    linkquality: int | None = None
    battery: int | None = None
    supported: bool = True

    @property
    def is_router(self) -> bool:
        return self.device_type in ("router", "coordinator")

    @property
    def is_battery(self) -> bool:
        return self.power_source == "battery"


@dataclass(slots=True)
class Snapshot:
    ts: float
    device_id: str
    availability: str
    last_seen: float | None = None
    linkquality: int | None = None
    battery: int | None = None
    rssi: int | None = None
    parent_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass(slots=True)
class EvidenceItem:
    """One line of the 'why we think so' list attached to an incident."""

    ts: float
    kind: str
    description: str
    device_id: str | None = None
    event_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass(slots=True)
class Hypothesis:
    """A rule's verdict: what happened, how sure we are, and what we do not know."""

    kind: str
    correlation_key: str
    title: str
    conclusion: str
    recommended_action: str
    confidence: float
    severity: str
    started_at: float
    evidence: list[EvidenceItem] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    cause_device_id: str | None = None
    affected_device_ids: list[str] = field(default_factory=list)
    network_id: str | None = None


@dataclass(slots=True)
class Incident:
    id: int
    kind: str
    correlation_key: str
    status: str  # open | resolved
    severity: str
    title: str
    conclusion: str
    recommended_action: str
    confidence: float
    started_at: float
    updated_at: float
    resolved_at: float | None = None
    cause_device_id: str | None = None
    network_id: str | None = None
    unknowns: list[str] = field(default_factory=list)
    affected_device_ids: list[str] = field(default_factory=list)
