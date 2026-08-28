"""Incident lifecycle: open, update, resolve.

The engine is pure with respect to time - it never calls the clock itself, it is
handed ``now``. That is what makes the whole detection story reproducible in
tests and replayable against recorded events.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config import Settings
from ..models import (
    EVT_DEVICE_DEGRADED,
    EvidenceItem,
    Hypothesis,
    Incident,
)
from ..storage import Repository
from .rules import ALL_RULES, EvaluationContext, Rule, build_bridge_state

_LOGGER = logging.getLogger(__name__)

# How far back the engine looks when folding bridge state and reading events.
LOOKBACK_SECONDS = 6 * 3600.0

SOURCE_KINDS = {
    "data_source_unavailable": "mqtt",
    "coordinator_unavailable": "coordinator",
    "bridge_unavailable": "bridge",
}


@dataclass
class EvaluationResult:
    created: list[Incident] = field(default_factory=list)
    updated: list[Incident] = field(default_factory=list)
    resolved: list[Incident] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.resolved)


class CorrelationEngine:
    def __init__(
        self,
        repo: Repository,
        settings: Settings,
        network_id: str = "z2m",
        rules: list[Rule] | None = None,
    ) -> None:
        self._repo = repo
        self._settings = settings
        self._network_id = network_id
        self._rules = list(rules if rules is not None else ALL_RULES)

    # -- context -------------------------------------------------------------
    def build_context(self, now: float) -> EvaluationContext:
        devices = {d.id: d for d in self._repo.list_devices()}
        events = self._repo.events_between(now - LOOKBACK_SECONDS, now, limit=5000)
        bridge = build_bridge_state(events, now)

        grace = self._settings.offline_grace_seconds
        offline_ids: list[str] = []
        offline_since: dict[str, float] = {}
        for device in devices.values():
            if device.disabled or device.availability != "offline":
                continue
            since = device.availability_since if device.availability_since is not None else now
            # A device that has only just dropped is not an incident yet. This one
            # line is what keeps a 90-second blip from paging anybody.
            if now - since < grace:
                continue
            offline_ids.append(device.id)
            offline_since[device.id] = since

        open_keys = {
            incident.correlation_key for incident in self._repo.list_incidents(status="open", limit=200)
        }

        return EvaluationContext(
            now=now,
            settings=self._settings,
            network_id=self._network_id,
            devices=devices,
            events=events,
            bridge=bridge,
            offline_device_ids=offline_ids,
            offline_since=offline_since,
            open_incident_keys=open_keys,
        )

    # -- main entry point ----------------------------------------------------
    def evaluate(self, now: float) -> EvaluationResult:
        ctx = self.build_context(now)
        result = EvaluationResult()

        remaining = set(ctx.offline_device_ids)
        hypotheses: list[Hypothesis] = []
        for rule in self._rules:
            try:
                hypotheses.extend(rule(ctx, remaining))
            except Exception:  # pragma: no cover - a broken rule must not stop the rest
                _LOGGER.exception("Correlation rule %s failed", getattr(rule, "__name__", rule))

        seen_keys: set[str] = set()
        for hypothesis in hypotheses:
            if hypothesis.correlation_key in seen_keys:
                continue
            seen_keys.add(hypothesis.correlation_key)
            existing = self._repo.open_incident_by_key(hypothesis.correlation_key)
            if existing is None:
                incident = self._repo.create_incident(hypothesis, now)
                result.created.append(incident)
                _LOGGER.info(
                    "Incident #%s opened: %s (confidence %.0f%%)",
                    incident.id,
                    incident.title,
                    incident.confidence * 100,
                )
            else:
                self._repo.update_incident(existing.id, hypothesis, now)
                refreshed = self._repo.get_incident(existing.id)
                if refreshed is not None:
                    result.updated.append(refreshed)

        result.resolved = self._resolve_recovered(ctx, seen_keys)
        return result

    # -- recovery ------------------------------------------------------------
    def _resolve_recovered(
        self, ctx: EvaluationContext, active_keys: set[str]
    ) -> list[Incident]:
        resolved: list[Incident] = []
        confirm = self._settings.recovery_confirm_seconds
        for incident in self._repo.list_incidents(status="open", limit=200):
            if incident.correlation_key in active_keys:
                continue
            recovery = self._recovery_evidence(ctx, incident, confirm)
            if recovery is None:
                continue
            self._repo.add_evidence(incident.id, recovery)
            self._repo.resolve_incident(incident.id, ctx.now)
            refreshed = self._repo.get_incident(incident.id)
            if refreshed is not None:
                resolved.append(refreshed)
                _LOGGER.info("Incident #%s resolved: %s", incident.id, incident.title)
        return resolved

    def _recovery_evidence(
        self, ctx: EvaluationContext, incident: Incident, confirm: float
    ) -> EvidenceItem | None:
        """Return the closing evidence line, or None if it is too early to close."""

        source_kind = SOURCE_KINDS.get(incident.kind)
        if source_kind is not None:
            state_ok = {
                "mqtt": (ctx.bridge.mqtt_connected, ctx.bridge.mqtt_last_change),
                "coordinator": (ctx.bridge.coordinator_ok, ctx.bridge.coordinator_last_change),
                "bridge": (ctx.bridge.bridge_online, ctx.bridge.bridge_last_change),
            }[source_kind]
            ok, last_change = state_ok
            if not ok:
                return None
            since = last_change.ts if last_change else incident.started_at
            if ctx.now - since < confirm:
                return None
            return EvidenceItem(
                ts=ctx.now,
                kind="recovery",
                description="Data source is back and has stayed up",
                payload={"recovered_at": since},
            )

        if incident.kind == "device_degraded":
            device_id = incident.cause_device_id
            recent = [
                e
                for e in ctx.events
                if e.event_type == EVT_DEVICE_DEGRADED
                and e.device_id == device_id
                and e.ts >= ctx.now - 2 * 3600.0
            ]
            if recent:
                return None
            device = ctx.device(device_id) if device_id else None
            if device is not None and device.availability == "offline":
                return None
            return EvidenceItem(
                ts=ctx.now,
                kind="recovery",
                description="No further degradation signals in the last 2 hours",
                device_id=device_id,
            )

        device_ids = self._repo.incident_device_ids(incident.id)
        if not device_ids:
            return None
        recovered_at: list[float] = []
        for device_id in device_ids:
            device = ctx.device(device_id)
            if device is None or device.disabled:
                continue
            if device.availability != "online":
                return None
            since = device.availability_since if device.availability_since is not None else ctx.now
            if ctx.now - since < confirm:
                return None
            recovered_at.append(since)
        if not recovered_at:
            return None
        return EvidenceItem(
            ts=max(recovered_at),
            kind="recovery",
            description=f"All {len(recovered_at)} affected devices are reporting again",
            payload={"recovered_at": max(recovered_at)},
        )
