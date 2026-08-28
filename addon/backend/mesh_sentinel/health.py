"""Health scoring and the overview payload.

The score is a summary, not a diagnosis - it exists so the top of the screen can
say "something is wrong" in one glance. Every point deducted is traceable to a
listed reason; there is no hidden weighting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Device, Incident
from .storage import Repository

INCIDENT_PENALTY = {"critical": 40, "error": 20, "warning": 8, "info": 2}
OFFLINE_PENALTY = 6
CRITICAL_OFFLINE_PENALTY = 15
DEGRADED_PENALTY = 2
MAX_DEVICE_PENALTY = 40


@dataclass
class HealthScore:
    score: int
    status: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"score": self.score, "status": self.status, "reasons": self.reasons}


def _status(score: int) -> str:
    if score >= 90:
        return "healthy"
    if score >= 60:
        return "degraded"
    return "critical"


def is_degraded(device: Device, linkquality_threshold: int) -> bool:
    if device.availability == "offline":
        return False
    if device.linkquality is not None and device.linkquality < linkquality_threshold:
        return True
    if device.is_battery and device.battery is not None and device.battery <= 15:
        return True
    return False


def compute_health(
    devices: list[Device], incidents: list[Incident], linkquality_threshold: int
) -> HealthScore:
    active = [d for d in devices if not d.disabled]
    offline = [d for d in active if d.availability == "offline"]
    degraded = [d for d in active if is_degraded(d, linkquality_threshold)]

    reasons: list[str] = []
    penalty = 0

    device_penalty = 0
    for device in offline:
        device_penalty += CRITICAL_OFFLINE_PENALTY if device.is_critical else OFFLINE_PENALTY
    device_penalty += DEGRADED_PENALTY * len(degraded)
    device_penalty = min(device_penalty, MAX_DEVICE_PENALTY)
    penalty += device_penalty

    if offline:
        critical_count = sum(1 for d in offline if d.is_critical)
        note = f"{len(offline)} device(s) offline"
        if critical_count:
            note += f", {critical_count} marked critical"
        reasons.append(note)
    if degraded:
        reasons.append(f"{len(degraded)} device(s) with a weak link or low battery")

    for incident in incidents:
        if incident.status != "open":
            continue
        penalty += INCIDENT_PENALTY.get(incident.severity, 5)
        reasons.append(f"Open incident: {incident.title}")

    score = max(0, min(100, 100 - penalty))
    if not active:
        return HealthScore(score=100, status="healthy", reasons=["No devices discovered yet"])
    return HealthScore(score=score, status=_status(score), reasons=reasons)


def network_summary(devices: list[Device], linkquality_threshold: int) -> dict[str, int]:
    active = [d for d in devices if not d.disabled]
    offline = [d for d in active if d.availability == "offline"]
    degraded = [d for d in active if is_degraded(d, linkquality_threshold)]
    return {
        "total": len(active),
        "offline": len(offline),
        "degraded": len(degraded),
        "healthy": len(active) - len(offline) - len(degraded),
        "routers": len([d for d in active if d.device_type == "router"]),
        "battery": len([d for d in active if d.is_battery]),
        "critical": len([d for d in active if d.is_critical]),
    }


def devices_needing_attention(
    repo: Repository, linkquality_threshold: int
) -> list[Device]:
    return [
        d
        for d in repo.list_devices()
        if not d.disabled and (d.availability == "offline" or is_degraded(d, linkquality_threshold))
    ]
