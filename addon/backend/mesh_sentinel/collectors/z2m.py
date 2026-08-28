"""Zigbee2MQTT collector.

Split in two on purpose:

* ``Z2MMessageHandler`` is pure message -> database. No sockets, no asyncio, so
  every parsing decision is testable from a recorded payload.
* ``Z2MCollector`` owns the MQTT connection and the periodic snapshot work.

Retained messages get special treatment. Zigbee2MQTT republishes the last state
of every device when we connect; treating that as proof of life would make a
device that has been dead for two days look healthy for another 90 minutes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

from ..clock import Clock
from ..config import Settings
from ..models import (
    EVT_BRIDGE_OFFLINE,
    EVT_BRIDGE_ONLINE,
    EVT_BRIDGE_RESTART,
    EVT_COORDINATOR_MISSING,
    EVT_COORDINATOR_OK,
    EVT_DEVICE_ERROR,
    EVT_DEVICE_JOINED,
    EVT_DEVICE_LEFT,
    EVT_DEVICE_OFFLINE,
    EVT_DEVICE_ONLINE,
    EVT_DEVICE_TIMEOUT,
    EVT_MQTT_CONNECTED,
    EVT_MQTT_DISCONNECTED,
    EVT_OTA_UPDATE,
    Device,
    Event,
    Snapshot,
)
from ..storage import Repository

_LOGGER = logging.getLogger(__name__)

NETWORK_ID = "z2m"

# Bridge log lines that mean "the adapter is not answering", as opposed to the
# ordinary "device X did not respond" noise.
_COORDINATOR_FAILURE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"failed to connect to the adapter",
        r"error while opening serial ?port",
        r"coordinator failed",
        r"adapter disconnected",
        r"failed to start zigbee",
        r"resolve.*serial.*port",
    )
]
_DEVICE_TIMEOUT_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"publish.*failed.*timeout",
        r"no response (?:from|received)",
        r"timed? ?out after",
        r"failed to (?:read|write|configure).*timeout",
    )
]
_QUOTED_PATTERN = re.compile(r"'([^']+)'")


def _parse_json(payload: str) -> Any:
    try:
        return json.loads(payload)
    except (TypeError, ValueError):
        return None


def _parse_last_seen(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Zigbee2MQTT emits epoch milliseconds when last_seen is set to epoch.
        return float(value) / 1000.0 if value > 1e11 else float(value)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _availability_state(payload: str) -> str | None:
    data = _parse_json(payload)
    if isinstance(data, dict):
        state = str(data.get("state", "")).lower()
    else:
        state = payload.strip().strip('"').lower()
    if state in ("online", "offline"):
        return state
    return None


def device_key(ieee: str | None, friendly_name: str | None) -> str:
    """Stable id. IEEE address if we have it, friendly name only as a fallback."""

    if ieee:
        return f"{NETWORK_ID}:{ieee.lower()}"
    return f"{NETWORK_ID}:name:{friendly_name}"


class Z2MMessageHandler:
    """Translates Zigbee2MQTT topics into normalised events and device rows."""

    def __init__(self, repo: Repository, settings: Settings) -> None:
        self._repo = repo
        self._settings = settings
        self._base = settings.z2m_base_topic.strip("/")
        # friendly_name -> device id, rebuilt from every bridge/devices message.
        self._names: dict[str, str] = {}
        self._bridge_online: bool | None = None

    # -- public --------------------------------------------------------------
    @property
    def subscriptions(self) -> list[str]:
        return [
            f"{self._base}/bridge/state",
            f"{self._base}/bridge/info",
            f"{self._base}/bridge/devices",
            f"{self._base}/bridge/event",
            f"{self._base}/bridge/logging",
            f"{self._base}/bridge/response/#",
            f"{self._base}/+/availability",
            f"{self._base}/+",
        ]

    def handle(self, topic: str, payload: str, now: float, retained: bool = False) -> list[Event]:
        topic = topic.strip("/")
        if not topic.startswith(f"{self._base}/"):
            return []
        rest = topic[len(self._base) + 1 :]

        if rest.startswith("bridge/"):
            return self._handle_bridge(rest[len("bridge/") :], payload, now, retained)
        if rest.endswith("/availability"):
            return self._handle_availability(
                rest[: -len("/availability")], payload, now, retained
            )
        if "/" in rest and not rest.endswith("/set") and not rest.endswith("/get"):
            # Nested friendly names ("kitchen/lamp") are legal in Zigbee2MQTT.
            return self._handle_device_state(rest, payload, now, retained)
        if rest.endswith("/set") or rest.endswith("/get"):
            return []
        return self._handle_device_state(rest, payload, now, retained)

    def resolve(self, friendly_name: str) -> str | None:
        return self._names.get(friendly_name)

    # -- bridge --------------------------------------------------------------
    def _handle_bridge(
        self, rest: str, payload: str, now: float, retained: bool
    ) -> list[Event]:
        if rest == "state":
            return self._handle_bridge_state(payload, now, retained)
        if rest == "devices":
            return self._handle_devices(payload, now)
        if rest == "event":
            return self._handle_bridge_event(payload, now)
        if rest == "logging":
            return self._handle_logging(payload, now)
        if rest == "info":
            return self._handle_info(payload, now)
        if rest.startswith("response/"):
            return self._handle_response(rest[len("response/") :], payload, now)
        return []

    def _handle_bridge_state(self, payload: str, now: float, retained: bool) -> list[Event]:
        state = _availability_state(payload)
        if state is None:
            return []
        previous = self._bridge_online
        self._bridge_online = state == "online"
        if previous == self._bridge_online:
            return []

        events: list[Event] = []
        if self._bridge_online:
            events.append(
                self._emit(
                    now,
                    EVT_BRIDGE_ONLINE,
                    severity="info",
                    payload={"retained": retained},
                )
            )
            # online after a known offline is a restart, not a first sighting
            if previous is False:
                events.append(
                    self._emit(
                        now,
                        EVT_BRIDGE_RESTART,
                        severity="warning",
                        payload={"detected_from": "bridge/state transition"},
                    )
                )
        else:
            events.append(self._emit(now, EVT_BRIDGE_OFFLINE, severity="critical"))
        return events

    def _handle_info(self, payload: str, now: float) -> list[Event]:
        data = _parse_json(payload)
        if not isinstance(data, dict):
            return []
        coordinator = data.get("coordinator") or {}
        version = data.get("version")
        ieee = coordinator.get("ieee_address") or coordinator.get("ieeeAddr")
        if ieee:
            self._repo.upsert_device(
                Device(
                    id=device_key(ieee, "Coordinator"),
                    network_id=NETWORK_ID,
                    source="z2m",
                    integration="zigbee2mqtt",
                    ieee=ieee,
                    friendly_name="Coordinator",
                    vendor=str(coordinator.get("type") or "") or None,
                    device_type="coordinator",
                    power_source="mains",
                    first_seen=now,
                    last_seen=now,
                    availability="online",
                    availability_since=now,
                )
            )
        # bridge/info is republished on every start, but a version string is not
        # proof of a restart - bridge/state transitions are. Nothing to emit here.
        _LOGGER.debug("Zigbee2MQTT version %s", version)
        return []

    def _handle_devices(self, payload: str, now: float) -> list[Event]:
        data = _parse_json(payload)
        if not isinstance(data, list):
            return []
        names: dict[str, str] = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            ieee = entry.get("ieee_address") or entry.get("ieeeAddr")
            friendly_name = entry.get("friendly_name") or ieee
            if not friendly_name:
                continue
            device_id = device_key(ieee, friendly_name)
            names[str(friendly_name)] = device_id
            definition = entry.get("definition") or {}
            device_type = str(entry.get("type") or "unknown").lower()
            if device_type == "enddevice":
                device_type = "end_device"
            if device_type == "greenpower":
                device_type = "end_device"
            power_source = str(entry.get("power_source") or "").lower()
            if "battery" in power_source:
                power_source = "battery"
            elif power_source in ("mains (single phase)", "dc source", "mains"):
                power_source = "mains"
            else:
                power_source = "unknown"
            self._repo.upsert_device(
                Device(
                    id=device_id,
                    network_id=NETWORK_ID,
                    source="z2m",
                    integration="zigbee2mqtt",
                    ieee=ieee,
                    friendly_name=str(friendly_name),
                    vendor=definition.get("vendor") or entry.get("manufacturer"),
                    model=definition.get("model") or entry.get("model_id"),
                    device_type=device_type if device_type in ("router", "end_device", "coordinator") else "unknown",
                    power_source=power_source,
                    supported=bool(entry.get("supported", True)),
                    first_seen=now,
                    last_seen=None,
                )
            )
            if entry.get("disabled"):
                self._repo.set_disabled(device_id, True)
        self._names = names
        return []

    def _handle_bridge_event(self, payload: str, now: float) -> list[Event]:
        data = _parse_json(payload)
        if not isinstance(data, dict):
            return []
        event_type = str(data.get("type") or "")
        info = data.get("data") or {}
        friendly_name = info.get("friendly_name")
        ieee = info.get("ieee_address")
        device_id = self._names.get(str(friendly_name)) or (
            device_key(ieee, friendly_name) if ieee else None
        )
        if event_type == "device_joined" or event_type == "device_interview":
            return [
                self._emit(
                    now,
                    EVT_DEVICE_JOINED,
                    device_id=device_id,
                    payload={"friendly_name": friendly_name, "stage": event_type},
                )
            ]
        if event_type in ("device_leave", "device_removed"):
            if device_id:
                self._repo.set_availability(device_id, "offline", now)
            return [
                self._emit(
                    now,
                    EVT_DEVICE_LEFT,
                    severity="warning",
                    device_id=device_id,
                    payload={"friendly_name": friendly_name},
                )
            ]
        return []

    def _handle_logging(self, payload: str, now: float) -> list[Event]:
        data = _parse_json(payload)
        if not isinstance(data, dict):
            return []
        level = str(data.get("level") or "").lower()
        message = str(data.get("message") or "")
        if level not in ("error", "warning") or not message:
            return []

        if any(p.search(message) for p in _COORDINATOR_FAILURE_PATTERNS):
            return [
                self._emit(
                    now,
                    EVT_COORDINATOR_MISSING,
                    severity="critical",
                    payload={"message": message[:500], "level": level},
                )
            ]

        if any(p.search(message) for p in _DEVICE_TIMEOUT_PATTERNS):
            # Log lines quote several things ("Publish 'set' 'state' to 'Lamp'
            # failed"), so take the quoted token that is actually a device.
            device_id = None
            for candidate in _QUOTED_PATTERN.findall(message):
                if candidate in self._names:
                    device_id = self._names[candidate]
                    break
            return [
                self._emit(
                    now,
                    EVT_DEVICE_TIMEOUT,
                    severity="warning",
                    device_id=device_id,
                    payload={"message": message[:500], "level": level},
                )
            ]

        if level == "error":
            return [
                self._emit(
                    now,
                    EVT_DEVICE_ERROR,
                    severity="warning",
                    payload={"message": message[:500], "level": level},
                )
            ]
        return []

    def _handle_response(self, rest: str, payload: str, now: float) -> list[Event]:
        data = _parse_json(payload)
        if not isinstance(data, dict):
            return []
        if rest == "health_check":
            healthy = bool((data.get("data") or {}).get("healthy"))
            ok = data.get("status") == "ok" and healthy
            return [
                self._emit(
                    now,
                    EVT_COORDINATOR_OK if ok else EVT_COORDINATOR_MISSING,
                    severity="info" if ok else "critical",
                    payload={"status": data.get("status"), "healthy": healthy},
                )
            ]
        if rest == "networkmap":
            return self._handle_networkmap(data, now)
        if rest.startswith("device/ota_update"):
            return [
                self._emit(
                    now,
                    EVT_OTA_UPDATE,
                    payload={"status": data.get("status"), "data": data.get("data")},
                )
            ]
        return []

    def _handle_networkmap(self, data: dict[str, Any], now: float) -> list[Event]:
        if data.get("status") != "ok":
            return []
        value = (data.get("data") or {}).get("value")
        if not isinstance(value, dict):
            return []
        nodes = value.get("nodes") or []
        links = value.get("links") or []

        by_ieee: dict[str, str] = {}
        payload_nodes = []
        for node in nodes:
            ieee = node.get("ieeeAddr")
            if not ieee:
                continue
            device_id = device_key(ieee, node.get("friendlyName"))
            by_ieee[ieee] = device_id
            payload_nodes.append(
                {
                    "device_id": device_id,
                    "friendly_name": node.get("friendlyName"),
                    "device_type": node.get("type", "unknown").lower(),
                }
            )

        # Strongest parent link per child, so the router rule has real topology.
        best: dict[str, tuple[int, str]] = {}
        payload_links = []
        for link in links:
            source = (link.get("source") or {}).get("ieeeAddr")
            target = (link.get("target") or {}).get("ieeeAddr")
            if not source or not target:
                continue
            lqi = _as_int(link.get("linkquality")) or 0
            child = by_ieee.get(source)
            parent = by_ieee.get(target)
            if not child or not parent or child == parent:
                continue
            payload_links.append({"child": child, "parent": parent, "linkquality": lqi})
            if child not in best or lqi > best[child][0]:
                best[child] = (lqi, parent)

        for child, (_, parent) in best.items():
            self._repo.set_parent(child, parent)

        self._repo.add_topology_snapshot(
            now,
            NETWORK_ID,
            {"nodes": payload_nodes, "links": payload_links},
            kind="active",
            reason="networkmap_response",
        )
        return [
            self._emit(
                now,
                EVT_COORDINATOR_OK,
                payload={"source": "networkmap", "nodes": len(payload_nodes)},
            )
        ]

    # -- devices -------------------------------------------------------------
    def _handle_availability(
        self, friendly_name: str, payload: str, now: float, retained: bool = False
    ) -> list[Event]:
        state = _availability_state(payload)
        device_id = self._names.get(friendly_name)
        if state is None or device_id is None:
            return []
        changed = self._repo.set_availability(device_id, state, now)
        if state == "online" and not retained:
            # A replayed retained message says what Zigbee2MQTT last believed,
            # not that the device spoke just now.
            self._repo.touch_device(device_id, now)
        if not changed:
            return []
        return [
            self._emit(
                now,
                EVT_DEVICE_ONLINE if state == "online" else EVT_DEVICE_OFFLINE,
                severity="info" if state == "online" else "warning",
                device_id=device_id,
                payload={"reason": "z2m_availability"},
            )
        ]

    def _handle_device_state(
        self, friendly_name: str, payload: str, now: float, retained: bool
    ) -> list[Event]:
        device_id = self._names.get(friendly_name)
        if device_id is None:
            return []
        data = _parse_json(payload)
        if not isinstance(data, dict):
            return []

        linkquality = _as_int(data.get("linkquality"))
        battery = _as_int(data.get("battery"))
        reported_last_seen = _parse_last_seen(data.get("last_seen"))

        # A retained message is Zigbee2MQTT replaying history at us. Only its own
        # last_seen field carries a timestamp we can trust.
        last_seen = reported_last_seen if retained else (reported_last_seen or now)
        events: list[Event] = []
        if last_seen is not None:
            self._repo.touch_device(device_id, last_seen, linkquality, battery)
            if not retained and self._repo.set_availability(device_id, "online", now):
                events.append(
                    self._emit(
                        now,
                        EVT_DEVICE_ONLINE,
                        device_id=device_id,
                        payload={"reason": "state_message"},
                    )
                )
        else:
            self._repo.touch_device(device_id, 0.0, linkquality, battery)

        self._repo.add_snapshot(
            Snapshot(
                ts=now,
                device_id=device_id,
                availability="online" if last_seen else "unknown",
                last_seen=last_seen,
                linkquality=linkquality,
                battery=battery,
                rssi=_as_int(data.get("rssi")),
                payload={"retained": retained},
            )
        )
        return events

    # -- helpers -------------------------------------------------------------
    def _emit(
        self,
        ts: float,
        event_type: str,
        severity: str = "info",
        device_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        return self._repo.add_event(
            Event(
                ts=ts,
                source="z2m",
                event_type=event_type,
                severity=severity,
                device_id=device_id,
                network_id=NETWORK_ID,
                payload=payload or {},
            )
        )


class Z2MCollector:
    """Owns the MQTT connection, reconnects, and the periodic snapshot jobs."""

    def __init__(
        self,
        repo: Repository,
        settings: Settings,
        clock: Clock,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._repo = repo
        self._settings = settings
        self._clock = clock
        self._handler = Z2MMessageHandler(repo, settings)
        self._on_change = on_change
        # None until we have made up our mind: at start-up the broker may simply
        # not be running yet, and a flap during boot is not worth an incident.
        self._connected: bool | None = None
        self._first_attempt_at: float | None = None
        self._client: Any = None

    @property
    def connected(self) -> bool:
        return self._connected is True

    @property
    def handler(self) -> Z2MMessageHandler:
        return self._handler

    async def run(self, stop: asyncio.Event) -> None:
        try:
            import aiomqtt
        except ImportError:  # pragma: no cover - only hit on a broken install
            _LOGGER.error("aiomqtt is not installed; the Zigbee2MQTT collector is disabled")
            return

        backoff = 2.0
        self._first_attempt_at = self._clock.now()
        while not stop.is_set():
            try:
                tls_params = aiomqtt.TLSParameters() if self._settings.mqtt_tls else None
                async with aiomqtt.Client(
                    hostname=self._settings.mqtt_host,
                    port=self._settings.mqtt_port,
                    username=self._settings.mqtt_username or None,
                    password=self._settings.mqtt_password or None,
                    identifier=self._settings.mqtt_client_id,
                    tls_params=tls_params,
                    keepalive=30,
                ) as client:
                    self._client = client
                    self._mark_connected(True)
                    backoff = 2.0
                    for topic in self._handler.subscriptions:
                        await client.subscribe(topic)
                    _LOGGER.info(
                        "Connected to MQTT at %s:%s, watching %s/#",
                        self._settings.mqtt_host,
                        self._settings.mqtt_port,
                        self._settings.z2m_base_topic,
                    )
                    async for message in client.messages:
                        if stop.is_set():
                            break
                        self._dispatch(message)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self._mark_connected(False, str(err))
                _LOGGER.warning("MQTT connection lost (%s); retrying in %.0fs", err, backoff)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60.0)
            finally:
                self._client = None
        self._mark_connected(False, "shutdown")

    def _dispatch(self, message: Any) -> None:
        try:
            payload = message.payload
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8", errors="replace")
            events = self._handler.handle(
                str(message.topic), payload, self._clock.now(), bool(message.retain)
            )
        except Exception:  # pragma: no cover - one bad payload must not kill the loop
            _LOGGER.exception("Failed to handle MQTT message on %s", message.topic)
            return
        if events and self._on_change:
            self._on_change()

    def _mark_connected(self, connected: bool, reason: str = "") -> None:
        if connected is self._connected:
            return
        if not connected and self._connected is None:
            # We have never been connected. Give the broker the same grace a
            # device gets before we call it a problem.
            started = self._first_attempt_at or self._clock.now()
            if self._clock.now() - started < self._settings.offline_grace_seconds:
                return
        self._connected = connected
        self._repo.add_event(
            Event(
                ts=self._clock.now(),
                source="mesh_sentinel",
                event_type=EVT_MQTT_CONNECTED if connected else EVT_MQTT_DISCONNECTED,
                severity="info" if connected else "error",
                network_id=NETWORK_ID,
                payload={"reason": reason} if reason else {},
            )
        )

    # -- outbound requests ---------------------------------------------------
    async def request_health_check(self) -> bool:
        return await self._publish("bridge/request/health_check", "")

    async def request_networkmap(self) -> bool:
        return await self._publish(
            "bridge/request/networkmap", json.dumps({"type": "raw", "routes": False})
        )

    async def _publish(self, topic: str, payload: str) -> bool:
        client = self._client
        if client is None:
            return False
        try:
            await client.publish(f"{self._settings.z2m_base_topic.strip('/')}/{topic}", payload)
            return True
        except Exception as err:  # pragma: no cover - transport failure
            _LOGGER.warning("Could not publish to %s: %s", topic, err)
            return False
