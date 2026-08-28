"""Deterministic correlation rules.

No model, no scoring soup: each rule is a small function over a snapshot of the
network, and it either claims a set of offline devices or it does not. Rules run
in priority order and a device claimed by a higher rule is not offered to a
lower one, so one root cause produces one incident instead of five.

Every hypothesis carries four things on purpose: a conclusion, the evidence it
rests on, what we could NOT determine, and the next step for a human. A rule
that cannot state its unknowns is not ready to ship.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..config import Settings
from ..models import (
    EVT_BRIDGE_OFFLINE,
    EVT_BRIDGE_ONLINE,
    EVT_BRIDGE_RESTART,
    EVT_COORDINATOR_MISSING,
    EVT_COORDINATOR_OK,
    EVT_DEVICE_DEGRADED,
    EVT_MQTT_CONNECTED,
    EVT_MQTT_DISCONNECTED,
    Device,
    EvidenceItem,
    Event,
    Hypothesis,
)


def _name(device: Device | None) -> str:
    if device is None:
        return "unknown device"
    return device.friendly_name or device.ieee or device.id


@dataclass
class BridgeState:
    """What we currently believe about the data source itself."""

    mqtt_connected: bool = True
    mqtt_last_change: Event | None = None
    bridge_online: bool = True
    bridge_last_change: Event | None = None
    coordinator_ok: bool = True
    coordinator_last_change: Event | None = None
    last_restart: Event | None = None


@dataclass
class EvaluationContext:
    now: float
    settings: Settings
    network_id: str
    devices: dict[str, Device]
    events: list[Event]
    bridge: BridgeState
    offline_device_ids: list[str] = field(default_factory=list)
    offline_since: dict[str, float] = field(default_factory=dict)
    open_incident_keys: set[str] = field(default_factory=set)

    def device(self, device_id: str) -> Device | None:
        return self.devices.get(device_id)

    def went_offline_at(self, device_id: str) -> float:
        return self.offline_since.get(device_id, self.now)

    def healthy_ratio(self) -> float:
        candidates = [d for d in self.devices.values() if not d.disabled]
        if not candidates:
            return 1.0
        healthy = [d for d in candidates if d.availability != "offline"]
        return len(healthy) / len(candidates)


Rule = Callable[[EvaluationContext, set[str]], list[Hypothesis]]


# --- R1: the data source itself is down --------------------------------------
def rule_data_source(ctx: EvaluationContext, remaining: set[str]) -> list[Hypothesis]:
    """MQTT, the Z2M bridge or the coordinator is gone.

    This is the rule that stops Mesh Sentinel from crying 'Zigbee failure' when
    the real story is a USB stick that did not come back after a host restart.
    """

    if ctx.bridge.mqtt_connected and ctx.bridge.bridge_online and ctx.bridge.coordinator_ok:
        return []

    affected = sorted(remaining)
    evidence: list[EvidenceItem] = []

    if not ctx.bridge.mqtt_connected:
        kind = "data_source_unavailable"
        key = f"{ctx.network_id}:mqtt"
        title = "MQTT broker unreachable"
        conclusion = (
            "Mesh Sentinel lost its connection to the MQTT broker. Device states "
            "below are the last known ones, not live. This says nothing about the "
            "Zigbee network itself."
        )
        action = "Check that the MQTT broker add-on is running, then check the credentials in Mesh Sentinel options."
        unknowns = [
            "Whether the Zigbee devices are actually reachable - we cannot observe them without MQTT.",
            "Whether Zigbee2MQTT is still running.",
        ]
        severity = "error"
        confidence = 0.95
        source_event = ctx.bridge.mqtt_last_change
    elif not ctx.bridge.coordinator_ok:
        kind = "coordinator_unavailable"
        key = f"{ctx.network_id}:coordinator"
        title = "Zigbee coordinator not responding"
        conclusion = (
            "Zigbee2MQTT is running but the coordinator is not answering. That is a "
            "host or USB problem (adapter detached, port renamed, VM passthrough lost), "
            "not a failure of the mesh or of Home Assistant."
        )
        action = (
            "Check that the coordinator USB adapter is attached to the host and to the VM, "
            "verify the serial port path, then restart Zigbee2MQTT."
        )
        unknowns = [
            "Whether the adapter is faulty or merely detached.",
            "The state of individual devices - nothing can be polled while the coordinator is silent.",
        ]
        severity = "critical"
        confidence = 0.9
        source_event = ctx.bridge.coordinator_last_change
    else:
        kind = "bridge_unavailable"
        key = f"{ctx.network_id}:bridge"
        title = "Zigbee2MQTT is offline"
        conclusion = (
            "The Zigbee2MQTT bridge reports itself offline. Every device behind it is "
            "unreachable for as long as that lasts - this is one failure, not many."
        )
        action = "Check the Zigbee2MQTT add-on log and restart it if it has stopped."
        unknowns = [
            "Whether the bridge stopped on its own or was stopped.",
            "The state of individual devices while the bridge is down.",
        ]
        severity = "critical"
        confidence = 0.9
        source_event = ctx.bridge.bridge_last_change

    if source_event is not None:
        evidence.append(
            EvidenceItem(
                ts=source_event.ts,
                kind="source_state",
                description=title,
                event_id=source_event.id,
                payload=source_event.payload,
            )
        )
    for device_id in affected[:20]:
        device = ctx.device(device_id)
        evidence.append(
            EvidenceItem(
                ts=ctx.went_offline_at(device_id),
                kind="device_offline",
                description=f"{_name(device)} became unavailable",
                device_id=device_id,
            )
        )

    started = min(
        [source_event.ts] if source_event else [],
        default=ctx.now,
    )
    if affected:
        started = min(started, min(ctx.went_offline_at(d) for d in affected))

    remaining.clear()
    return [
        Hypothesis(
            kind=kind,
            correlation_key=key,
            title=title,
            conclusion=conclusion,
            recommended_action=action,
            confidence=confidence,
            severity=severity,
            started_at=started,
            evidence=evidence,
            unknowns=unknowns,
            affected_device_ids=affected,
            network_id=ctx.network_id,
        )
    ]


# --- R2: the bridge restarted -------------------------------------------------
def rule_service_restart(ctx: EvaluationContext, remaining: set[str]) -> list[Hypothesis]:
    """A Z2M restart makes many devices blink out at once. It is not an outage."""

    restart = ctx.bridge.last_restart
    if restart is None or not remaining:
        return []
    window = ctx.settings.restart_window_seconds
    if ctx.now - restart.ts > window:
        return []

    # Only devices that dropped around the restart belong to it.
    claimed = {
        device_id
        for device_id in remaining
        if restart.ts - 60 <= ctx.went_offline_at(device_id) <= restart.ts + window
    }
    if len(claimed) < 2:
        return []

    evidence = [
        EvidenceItem(
            ts=restart.ts,
            kind="service_restart",
            description="Zigbee2MQTT restarted",
            event_id=restart.id,
            payload=restart.payload,
        )
    ]
    for device_id in sorted(claimed)[:20]:
        evidence.append(
            EvidenceItem(
                ts=ctx.went_offline_at(device_id),
                kind="device_offline",
                description=f"{_name(ctx.device(device_id))} dropped after the restart",
                device_id=device_id,
            )
        )

    remaining -= claimed
    return [
        Hypothesis(
            kind="service_restart",
            correlation_key=f"{ctx.network_id}:restart:{int(restart.ts)}",
            title="Devices dropped after a Zigbee2MQTT restart",
            conclusion=(
                f"Zigbee2MQTT restarted and {len(claimed)} devices went unavailable "
                "within the restart window. Battery devices usually reappear on their "
                "next report, which can take a while - this is expected, not an outage."
            ),
            recommended_action=(
                "No action yet. If devices are still missing 30 minutes after the "
                "restart, open the Zigbee2MQTT log and check for coordinator errors."
            ),
            confidence=0.8,
            severity="warning",
            started_at=restart.ts,
            evidence=evidence,
            unknowns=[
                "Why Zigbee2MQTT restarted - the add-on log holds that, we only see the event.",
                "Whether every device will re-report; battery devices report on their own schedule.",
            ],
            affected_device_ids=sorted(claimed),
            network_id=ctx.network_id,
        )
    ]


# --- R3: a router died and took its branch with it ---------------------------
def rule_router_failure(ctx: EvaluationContext, remaining: set[str]) -> list[Hypothesis]:
    """A mains router going quiet, followed by devices around it."""

    hypotheses: list[Hypothesis] = []
    routers = [
        ctx.devices[d]
        for d in sorted(remaining)
        if d in ctx.devices and ctx.devices[d].device_type == "router"
    ]
    for router in routers:
        if router.id not in remaining:
            continue
        router_ts = ctx.went_offline_at(router.id)
        window = ctx.settings.router_window_seconds

        children = {
            d
            for d in remaining
            if d != router.id and ctx.devices[d].parent_id == router.id
        }
        # Without an active networkmap scan we have no parent links, so fall back
        # to "went dark right after the router did" - and say so in the output.
        followers = {
            d
            for d in remaining
            if d != router.id
            and d not in children
            and router_ts - 30 <= ctx.went_offline_at(d) <= router_ts + window
        }

        topology_known = bool(children)
        claimed = {router.id} | children | followers
        dependents = children | followers
        if len(dependents) < 2:
            continue

        confidence = 0.85 if topology_known else 0.55
        evidence = [
            EvidenceItem(
                ts=router_ts,
                kind="router_missing",
                description=f"Router {_name(router)} stopped responding",
                device_id=router.id,
            )
        ]
        for device_id in sorted(dependents)[:20]:
            device = ctx.device(device_id)
            relation = "routed through it" if device_id in children else "went dark right after"
            evidence.append(
                EvidenceItem(
                    ts=ctx.went_offline_at(device_id),
                    kind="device_offline",
                    description=f"{_name(device)} unavailable ({relation})",
                    device_id=device_id,
                )
            )

        unknowns = [
            "Whether the router lost power, failed, or was simply unplugged.",
        ]
        if not topology_known:
            unknowns.append(
                "The routing table - no recent network map, so the link between these "
                "devices and this router is inferred from timing only."
            )

        remaining -= claimed
        hypotheses.append(
            Hypothesis(
                kind="router_failure",
                correlation_key=f"{ctx.network_id}:router:{router.id}",
                title=f"Probable router failure: {_name(router)}",
                conclusion=(
                    f"Router {_name(router)} went missing and {len(dependents)} devices "
                    "behind it followed. Zigbee2MQTT and the coordinator kept working, so "
                    "the problem is that router or its power, not Home Assistant and not "
                    "the coordinator."
                ),
                recommended_action=(
                    f"Check power at {_name(router)} first. If it is powered, power-cycle it, "
                    "then run a coordinator check and let the mesh re-route."
                ),
                confidence=confidence,
                severity="error",
                started_at=router_ts,
                evidence=evidence,
                unknowns=unknowns,
                cause_device_id=router.id,
                affected_device_ids=sorted(dependents),
                network_id=ctx.network_id,
            )
        )
    return hypotheses


# --- R4: many devices, no identified cause -----------------------------------
def rule_mass_outage(ctx: EvaluationContext, remaining: set[str]) -> list[Hypothesis]:
    key = f"{ctx.network_id}:mass"
    # While an unexplained outage is already open, a device that drops a few
    # minutes late belongs to it. Spawning a separate warning per straggler is
    # exactly the alert spam this layer exists to prevent.
    ongoing = key in ctx.open_incident_keys
    if not remaining or (not ongoing and len(remaining) < ctx.settings.mass_outage_min_devices):
        return []
    window = ctx.settings.mass_outage_window_seconds
    times = sorted((ctx.went_offline_at(d), d) for d in remaining)
    if ongoing:
        best = times
    else:
        # Largest cluster of drops inside one window.
        best = []
        for i, (start_ts, _) in enumerate(times):
            cluster = [t for t in times[i:] if t[0] - start_ts <= window]
            if len(cluster) > len(best):
                best = cluster
        if len(best) < ctx.settings.mass_outage_min_devices:
            return []

    claimed = {device_id for _, device_id in best}
    started = best[0][0]
    evidence = [
        EvidenceItem(
            ts=ts,
            kind="device_offline",
            description=f"{_name(ctx.device(device_id))} became unavailable",
            device_id=device_id,
        )
        for ts, device_id in best[:20]
    ]
    remaining -= claimed
    return [
        Hypothesis(
            kind="mass_outage",
            correlation_key=key,
            title=f"{len(claimed)} devices unavailable in one window",
            conclusion=(
                f"{len(claimed)} devices went unavailable within "
                f"{round(window / 60)} minutes with no bridge restart, no coordinator "
                "fault and no single router that explains all of them. A shared cause "
                "is likely - power, interference, or a router we do not have topology for."
            ),
            recommended_action=(
                "Check whether the affected devices share a circuit or a room. "
                "Then run a coordinator check and, if it is clean, a network map scan."
            ),
            confidence=0.5,
            severity="error",
            started_at=started,
            evidence=evidence,
            unknowns=[
                "The shared cause - the evidence shows correlation in time, nothing more.",
                "Routing topology, unless a recent network map scan exists.",
            ],
            affected_device_ids=sorted(claimed),
            network_id=ctx.network_id,
        )
    ]


# --- R5: one device, mesh healthy --------------------------------------------
def rule_single_device(ctx: EvaluationContext, remaining: set[str]) -> list[Hypothesis]:
    hypotheses: list[Hypothesis] = []
    for device_id in sorted(remaining):
        device = ctx.device(device_id)
        if device is None:
            continue
        started = ctx.went_offline_at(device_id)
        battery_hint = (
            f" Last reported battery level: {device.battery}%." if device.battery is not None else ""
        )
        if device.is_battery:
            conclusion = (
                f"{_name(device)} stopped reporting while the rest of the mesh is healthy. "
                "For a battery device the usual causes are a flat battery, a dropped "
                f"pairing, or the device being moved out of range.{battery_hint}"
            )
            action = (
                f"Replace or reseat the battery in {_name(device)}, then press its pairing "
                "button once to make it report. Re-pair only if that does not help."
            )
        else:
            conclusion = (
                f"{_name(device)} stopped responding while the rest of the mesh is healthy. "
                "A mains device going quiet on its own points at power or the device itself."
            )
            action = f"Check power at {_name(device)}, then power-cycle it."

        severity = "critical" if device.is_critical else "warning"
        healthy_ratio = ctx.healthy_ratio()
        mesh_note = (
            f"{round(healthy_ratio * 100)}% of devices are still reachable, so this is "
            "local to the device"
            if healthy_ratio >= 0.8
            else f"only {round(healthy_ratio * 100)}% of devices are reachable, so a shared "
            "cause may still emerge"
        )
        hypotheses.append(
            Hypothesis(
                kind="device_offline",
                correlation_key=f"{ctx.network_id}:device:{device_id}",
                title=f"{_name(device)} is unavailable",
                conclusion=conclusion,
                recommended_action=action,
                confidence=0.7,
                severity=severity,
                started_at=started,
                evidence=[
                    EvidenceItem(
                        ts=started,
                        kind="device_offline",
                        description=f"{_name(device)} became unavailable",
                        device_id=device_id,
                    ),
                    EvidenceItem(ts=ctx.now, kind="mesh_state", description=mesh_note),
                ],
                unknowns=[
                    "Whether the device is out of battery, out of range, or has lost its pairing.",
                ],
                cause_device_id=device_id,
                affected_device_ids=[device_id],
                network_id=ctx.network_id,
            )
        )
    remaining.clear()
    return hypotheses


# --- R6: degraded but still alive --------------------------------------------
def rule_device_degraded(ctx: EvaluationContext, remaining: set[str]) -> list[Hypothesis]:
    """Rising error rate or falling link quality on one device in a healthy mesh."""

    if ctx.healthy_ratio() < 0.8:
        # A struggling mesh explains bad numbers everywhere; do not blame devices.
        return []

    hypotheses: list[Hypothesis] = []
    window = ctx.now - 2 * 3600.0
    seen: set[str] = set()
    for event in ctx.events:
        if event.event_type != EVT_DEVICE_DEGRADED or event.ts < window:
            continue
        device_id = event.device_id
        if not device_id or device_id in seen:
            continue
        seen.add(device_id)
        device = ctx.device(device_id)
        if device is None or device.availability == "offline":
            # An offline device already has an incident of its own.
            continue
        reasons = event.payload.get("reasons", [])
        signals = ", ".join(str(r.get("signal")) for r in reasons) or "unknown"
        hypotheses.append(
            Hypothesis(
                kind="device_degraded",
                correlation_key=f"{ctx.network_id}:degraded:{device_id}",
                title=f"{_name(device)} is degrading",
                conclusion=(
                    f"{_name(device)} is still reachable but its link is getting worse "
                    f"({signals}), while the rest of the mesh is healthy. This is a local "
                    "problem: distance from its router, a new obstacle, or interference at "
                    "its position."
                ),
                recommended_action=(
                    f"Move {_name(device)} closer to a mains-powered router, or add a router "
                    "between them. Check for a new appliance or metal object near it."
                ),
                confidence=0.6,
                severity="warning",
                started_at=event.ts,
                evidence=[
                    EvidenceItem(
                        ts=event.ts,
                        kind="degradation",
                        description=f"Degradation signals: {signals}",
                        device_id=device_id,
                        event_id=event.id,
                        payload=event.payload,
                    )
                ],
                unknowns=[
                    "Whether the cause is the device, its router, or the radio environment.",
                    "Absolute RSSI - Zigbee2MQTT reports link quality, which is not a dBm figure.",
                ],
                cause_device_id=device_id,
                affected_device_ids=[device_id],
                network_id=ctx.network_id,
            )
        )
    return hypotheses


# How good an explanation each kind is. Devices are detected as offline over
# seconds or minutes, so a router failure often becomes visible only after a
# single-device incident has already opened for the router itself. A lower rank
# supersedes a higher one covering the same devices - otherwise one root cause
# still ends up as several incidents, which is the thing this layer exists to
# prevent.
RULE_RANK: dict[str, int] = {
    "data_source_unavailable": 0,
    "coordinator_unavailable": 0,
    "bridge_unavailable": 0,
    "service_restart": 1,
    "router_failure": 2,
    "mass_outage": 3,
    "device_offline": 4,
    "device_degraded": 5,
}


# Order matters: the first rule that claims a device owns it.
ALL_RULES: list[Rule] = [
    rule_data_source,
    rule_service_restart,
    rule_router_failure,
    rule_mass_outage,
    rule_single_device,
    rule_device_degraded,
]


def build_bridge_state(events: list[Event], now: float) -> BridgeState:
    """Fold the event stream into the current state of the data source."""

    state = BridgeState()
    for event in events:
        if event.event_type == EVT_MQTT_DISCONNECTED:
            state.mqtt_connected = False
            state.mqtt_last_change = event
        elif event.event_type == EVT_MQTT_CONNECTED:
            state.mqtt_connected = True
            state.mqtt_last_change = event
        elif event.event_type == EVT_BRIDGE_OFFLINE:
            state.bridge_online = False
            state.bridge_last_change = event
        elif event.event_type == EVT_BRIDGE_ONLINE:
            state.bridge_online = True
            state.bridge_last_change = event
        elif event.event_type == EVT_COORDINATOR_MISSING:
            state.coordinator_ok = False
            state.coordinator_last_change = event
        elif event.event_type == EVT_COORDINATOR_OK:
            state.coordinator_ok = True
            state.coordinator_last_change = event
        elif event.event_type == EVT_BRIDGE_RESTART:
            state.last_restart = event
    return state


__all__ = [
    "ALL_RULES",
    "RULE_RANK",
    "BridgeState",
    "EvaluationContext",
    "build_bridge_state",
    "rule_data_source",
    "rule_device_degraded",
    "rule_mass_outage",
    "rule_router_failure",
    "rule_service_restart",
    "rule_single_device",
]
