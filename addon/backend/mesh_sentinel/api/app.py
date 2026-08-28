"""FastAPI application: JSON API plus the static frontend behind HA Ingress.

Ingress serves the app under a generated path prefix, so every route here is
relative and the frontend resolves ``./api`` against its own location. Nothing
assumes it is mounted at the root.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import Settings
from ..health import compute_health, devices_needing_attention, network_summary
from ..service import MeshSentinelService
from .serializers import device_json, event_json, evidence_json, incident_json

_LOGGER = logging.getLogger(__name__)

def _find_frontend() -> Path | None:
    """Locate the built frontend.

    Three layouts have to work: the app image (/app/frontend), a source
    checkout (repo/frontend/dist), and an explicit override for development.
    """

    override = os.environ.get("MESH_SENTINEL_FRONTEND_DIR")
    candidates = [Path(override)] if override else []
    candidates.append(Path("/app/frontend"))
    here = Path(__file__).resolve()
    candidates.extend(parent / "frontend" / "dist" for parent in here.parents[:5])
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def create_app(
    settings: Settings, service: MeshSentinelService | None = None, run_service: bool = True
) -> FastAPI:
    service = service or MeshSentinelService(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if run_service:
            await service.start()
        try:
            yield
        finally:
            if run_service:
                await service.stop()

    app = FastAPI(
        title="Mesh Sentinel",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.service = service
    app.state.settings = settings
    app.include_router(_build_router(service, settings))

    frontend = _find_frontend()
    if frontend is not None:
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> Any:
            candidate = frontend / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend / "index.html")

    else:  # pragma: no cover - development without a built frontend

        @app.get("/", include_in_schema=False)
        async def missing_frontend() -> JSONResponse:
            return JSONResponse(
                {
                    "message": "Mesh Sentinel API is running, but the frontend build is missing.",
                    "hint": "Run 'npm ci && npm run build' in frontend/.",
                    "api": "./api/overview",
                },
                status_code=200,
            )

    return app


def _build_router(service: MeshSentinelService, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api")
    repo = service.repo
    lq = settings.linkquality_degraded

    def _names() -> dict[str, str]:
        return {d.id: (d.friendly_name or d.ieee or d.id) for d in repo.list_devices()}

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, **service.status()}

    @router.get("/overview")
    async def overview() -> dict[str, Any]:
        devices = repo.list_devices()
        open_incidents = repo.list_incidents(status="open", limit=50)
        recent = repo.list_incidents(limit=5)
        names = _names()
        score = compute_health(devices, open_incidents, lq)
        by_network: dict[str, list] = {}
        for device in devices:
            by_network.setdefault(device.network_id, []).append(device)

        return {
            "generated_at": service.clock.now(),
            "version": __version__,
            "health": score.as_dict(),
            "networks": [
                {
                    "id": network_id,
                    "label": "Zigbee2MQTT" if network_id == "z2m" else network_id,
                    **network_summary(items, lq),
                }
                for network_id, items in sorted(by_network.items())
            ],
            "attention": [device_json(d, lq) for d in devices_needing_attention(repo, lq)],
            "active_incidents": [incident_json(i, names) for i in open_incidents],
            "recent_incidents": [incident_json(i, names) for i in recent],
            "status": service.status(),
        }

    @router.get("/devices")
    async def devices(network_id: str | None = None) -> dict[str, Any]:
        items = repo.list_devices(network_id)
        return {
            "devices": [device_json(d, lq) for d in items],
            "summary": network_summary(items, lq),
        }

    @router.get("/devices/{device_id:path}/history")
    async def device_history(device_id: str, hours: int = Query(24, ge=1, le=2160)) -> dict[str, Any]:
        device = repo.get_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="Unknown device")
        now = service.clock.now()
        since = now - hours * 3600.0
        snapshots = repo.snapshots_for_device(device_id, since)
        return {
            "device_id": device_id,
            "since": since,
            "linkquality": [
                {"ts": s.ts, "value": s.linkquality} for s in snapshots if s.linkquality is not None
            ],
            "battery": [
                {"ts": s.ts, "value": s.battery} for s in snapshots if s.battery is not None
            ],
            "availability": [{"ts": s.ts, "value": s.availability} for s in snapshots],
        }

    @router.post("/devices/{device_id:path}/critical")
    async def set_critical(device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        value = bool(payload.get("is_critical", True))
        if not repo.set_critical(device_id, value):
            raise HTTPException(status_code=404, detail="Unknown device")
        return {"device_id": device_id, "is_critical": value}

    @router.get("/devices/{device_id:path}")
    async def device_detail(device_id: str) -> dict[str, Any]:
        device = repo.get_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="Unknown device")
        names = _names()
        parent = repo.get_device(device.parent_id) if device.parent_id else None
        children = [d for d in repo.list_devices() if d.parent_id == device.id]
        return {
            "device": device_json(device, lq),
            "parent": device_json(parent, lq) if parent else None,
            "children": [device_json(d, lq) for d in children],
            "incidents": [incident_json(i, names) for i in repo.incidents_for_device(device_id)],
            "events": [event_json(e) for e in repo.recent_events(limit=50, device_id=device_id)],
            "thresholds": {
                "stale_after_seconds": service.staleness.stale_after(device),
                "offline_grace_seconds": settings.offline_grace_seconds,
                "linkquality_degraded": lq,
            },
        }

    @router.get("/incidents")
    async def incidents(
        status: str | None = Query(None, pattern="^(open|resolved)$"),
        limit: int = Query(50, ge=1, le=500),
    ) -> dict[str, Any]:
        names = _names()
        items = repo.list_incidents(status=status, limit=limit)
        return {"incidents": [incident_json(i, names) for i in items]}

    @router.get("/incidents/{incident_id}")
    async def incident_detail(incident_id: int) -> dict[str, Any]:
        incident = repo.get_incident(incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Unknown incident")
        names = _names()
        evidence = repo.evidence_for(incident_id)
        roles = repo.incident_device_roles(incident_id)
        window_start = incident.started_at - 900.0
        window_end = incident.resolved_at or service.clock.now()

        events = repo.events_between(window_start, window_end + 60.0, limit=500)
        related = [
            e
            for e in events
            if e.device_id in roles
            or e.device_id is None
            or e.device_id == incident.cause_device_id
        ]

        return {
            "incident": incident_json(incident, names),
            "roles": roles,
            "evidence": [evidence_json(e) for e in evidence],
            "timeline": [event_json(e) for e in related],
            "before_after": {
                "before_ts": window_start,
                "after_ts": window_end,
                "before": {
                    "topology": repo.topology_at(window_start, incident.network_id or "z2m"),
                    "devices": repo.snapshot_at(window_start, incident.network_id or "z2m"),
                },
                "after": {
                    "topology": repo.topology_at(window_end, incident.network_id or "z2m"),
                    "devices": repo.snapshot_at(window_end, incident.network_id or "z2m"),
                },
            },
        }

    @router.get("/events")
    async def events(limit: int = Query(200, ge=1, le=2000)) -> dict[str, Any]:
        return {"events": [event_json(e) for e in repo.recent_events(limit=limit)]}

    @router.post("/evaluate")
    async def evaluate() -> dict[str, Any]:
        """Run a detection pass now instead of waiting for the next tick."""

        result = service.evaluate_once()
        names = _names()
        return {
            "created": [incident_json(i, names) for i in result.created],
            "updated": [incident_json(i, names) for i in result.updated],
            "resolved": [incident_json(i, names) for i in result.resolved],
        }

    @router.post("/actions/coordinator-check")
    async def coordinator_check() -> dict[str, Any]:
        sent = await service.z2m.request_health_check()
        return {
            "requested": sent,
            "detail": None
            if sent
            else "Not connected to MQTT, so the request could not be published.",
        }

    @router.post("/actions/network-map")
    async def network_map() -> dict[str, Any]:
        sent = await service.z2m.request_networkmap()
        return {
            "requested": sent,
            "detail": (
                "A network map scan asks every router for its routing table; it takes a "
                "minute and puts load on the mesh."
            )
            if sent
            else "Not connected to MQTT, so the request could not be published.",
        }

    @router.get("/stats")
    async def stats() -> dict[str, Any]:
        return {"counts": repo.counts(), "retention_days": settings.effective_retention_days}

    return router
