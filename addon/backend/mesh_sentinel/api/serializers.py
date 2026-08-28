"""Domain object -> JSON. Kept out of the route bodies so the shapes stay stable."""

from __future__ import annotations

from typing import Any

from ..health import is_degraded
from ..models import Device, EvidenceItem, Event, Incident


def device_json(device: Device, linkquality_threshold: int) -> dict[str, Any]:
    return {
        "id": device.id,
        "name": device.friendly_name or device.ieee or device.id,
        "ieee": device.ieee,
        "vendor": device.vendor,
        "model": device.model,
        "integration": device.integration,
        "network_id": device.network_id,
        "device_type": device.device_type,
        "power_source": device.power_source,
        "availability": device.availability,
        "availability_since": device.availability_since,
        "last_seen": device.last_seen,
        "linkquality": device.linkquality,
        "battery": device.battery,
        "parent_id": device.parent_id,
        "is_critical": device.is_critical,
        "disabled": device.disabled,
        "supported": device.supported,
        "state": (
            "offline"
            if device.availability == "offline"
            else "degraded"
            if is_degraded(device, linkquality_threshold)
            else "healthy"
            if device.availability == "online"
            else "unknown"
        ),
    }


def event_json(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "ts": event.ts,
        "source": event.source,
        "event_type": event.event_type,
        "device_id": event.device_id,
        "network_id": event.network_id,
        "severity": event.severity,
        "payload": event.payload,
    }


def evidence_json(item: EvidenceItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "ts": item.ts,
        "kind": item.kind,
        "description": item.description,
        "device_id": item.device_id,
        "event_id": item.event_id,
        "payload": item.payload,
    }


def incident_json(
    incident: Incident, names: dict[str, str] | None = None
) -> dict[str, Any]:
    names = names or {}
    return {
        "id": incident.id,
        "kind": incident.kind,
        "status": incident.status,
        "severity": incident.severity,
        "title": incident.title,
        "conclusion": incident.conclusion,
        "recommended_action": incident.recommended_action,
        "confidence": incident.confidence,
        "started_at": incident.started_at,
        "updated_at": incident.updated_at,
        "resolved_at": incident.resolved_at,
        "cause_device_id": incident.cause_device_id,
        "cause_device_name": names.get(incident.cause_device_id or ""),
        "network_id": incident.network_id,
        "unknowns": incident.unknowns,
        "device_count": len(incident.affected_device_ids),
        "affected_devices": [
            {"id": device_id, "name": names.get(device_id, device_id)}
            for device_id in incident.affected_device_ids
        ],
    }
