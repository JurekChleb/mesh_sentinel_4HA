"""Home Assistant WebSocket collector.

v0.1.0 keeps this deliberately small: it records Home Assistant restarts so an
incident timeline can say "everything went quiet because HA restarted, not
because your mesh broke". ZHA device correlation is the next step and lands on
top of this connection.

The connection is optional. If the token or the URL is wrong, Mesh Sentinel logs
it once and keeps doing its Zigbee2MQTT job.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ..clock import Clock
from ..config import Settings
from ..models import EVT_HA_RESTART, Event
from ..storage import Repository

_LOGGER = logging.getLogger(__name__)


def _ws_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :] + "/api/websocket"
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :] + "/api/websocket"
    return url + "/api/websocket"


class HomeAssistantCollector:
    def __init__(self, repo: Repository, settings: Settings, clock: Clock) -> None:
        self._repo = repo
        self._settings = settings
        self._clock = clock
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def run(self, stop: asyncio.Event) -> None:
        if not self._settings.ha_enabled:
            return
        if not self._settings.ha_token:
            _LOGGER.info(
                "No Home Assistant token available; skipping the Home Assistant collector"
            )
            return
        try:
            import websockets
        except ImportError:  # pragma: no cover
            _LOGGER.error("websockets is not installed; Home Assistant collector disabled")
            return

        url = _ws_url(self._settings.ha_url)
        backoff = 2.0
        while not stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=30, max_size=4_000_000) as ws:
                    await self._authenticate(ws)
                    self._connected = True
                    backoff = 2.0
                    _LOGGER.info("Connected to Home Assistant at %s", url)
                    await self._subscribe(ws)
                    while not stop.is_set():
                        raw = await ws.recv()
                        self._handle(raw)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self._connected = False
                _LOGGER.warning(
                    "Home Assistant connection lost (%s); retrying in %.0fs", err, backoff
                )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 120.0)
        self._connected = False

    async def _authenticate(self, ws: Any) -> None:
        greeting = json.loads(await ws.recv())
        if greeting.get("type") != "auth_required":
            raise RuntimeError(f"Unexpected greeting from Home Assistant: {greeting.get('type')}")
        await ws.send(json.dumps({"type": "auth", "access_token": self._settings.ha_token}))
        result = json.loads(await ws.recv())
        if result.get("type") != "auth_ok":
            raise RuntimeError("Home Assistant rejected the token")

    async def _subscribe(self, ws: Any) -> None:
        await ws.send(
            json.dumps({"id": 1, "type": "subscribe_events", "event_type": "homeassistant_start"})
        )
        await ws.send(
            json.dumps({"id": 2, "type": "subscribe_events", "event_type": "homeassistant_stop"})
        )

    def _handle(self, raw: str | bytes) -> None:
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            return
        if message.get("type") != "event":
            return
        event = message.get("event") or {}
        event_type = event.get("event_type")
        if event_type not in ("homeassistant_start", "homeassistant_stop"):
            return
        self._repo.add_event(
            Event(
                ts=self._clock.now(),
                source="home_assistant",
                event_type=EVT_HA_RESTART,
                severity="info",
                network_id="home_assistant",
                payload={"phase": "start" if event_type == "homeassistant_start" else "stop"},
            )
        )
