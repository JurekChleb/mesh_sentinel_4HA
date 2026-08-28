"""Home Assistant Supervisor integration.

The app declares ``services: mqtt:need``, so the Supervisor hands us the
broker's address and credentials. Asking for them beats making the user retype
what Home Assistant already knows - and it keeps the password out of the app
options entirely.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from .config import Settings

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_URL = "http://supervisor"
TIMEOUT = 10.0


def _get(path: str, token: str) -> dict[str, Any] | None:
    request = urllib.request.Request(
        f"{SUPERVISOR_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as err:
        _LOGGER.debug("Supervisor request %s failed: %s", path, err)
        return None
    if body.get("result") != "ok":
        return None
    data = body.get("data")
    return data if isinstance(data, dict) else None


def discover_mqtt(settings: Settings, environ: dict[str, str] | None = None) -> bool:
    """Fill in MQTT settings from the Supervisor. Returns True if anything changed.

    Explicit options always win: if the user typed a broker address, we use it.
    """

    if not settings.mqtt_auto_discover or settings.mqtt_host:
        return False
    env = dict(os.environ if environ is None else environ)
    token = env.get("SUPERVISOR_TOKEN") or env.get("HASSIO_TOKEN")
    if not token:
        return False

    data = _get("/services/mqtt", token)
    if not data or not data.get("host"):
        return False

    settings.mqtt_host = str(data["host"])
    settings.mqtt_port = int(data.get("port") or 1883)
    settings.mqtt_username = data.get("username") or None
    settings.mqtt_password = data.get("password") or None
    settings.mqtt_tls = bool(data.get("ssl"))
    _LOGGER.info(
        "Discovered the MQTT broker through the Supervisor: %s:%s",
        settings.mqtt_host,
        settings.mqtt_port,
    )
    return True


def resolve_mqtt(settings: Settings, environ: dict[str, str] | None = None) -> None:
    """Settle on a broker: explicit option, then Supervisor, then the default."""

    discover_mqtt(settings, environ)
    if not settings.mqtt_host:
        settings.mqtt_host = "core-mosquitto"
        _LOGGER.info(
            "No broker configured and none offered by the Supervisor; "
            "falling back to core-mosquitto:1883"
        )
