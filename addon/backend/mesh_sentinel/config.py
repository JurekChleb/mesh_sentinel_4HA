"""Configuration.

Values come from the Home Assistant add-on options file (``/data/options.json``)
when running as an add-on, and from environment variables otherwise. Secrets
(MQTT password, HA token) are never persisted to the database or logged.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_OPTIONS_PATH = "/data/options.json"
DEFAULT_DB_PATH = "/data/mesh_sentinel.db"

# The Free edition keeps a week of history; Pro raises this cap. v0.1.0 ships
# Free only, but the cap lives here so the gate has exactly one home.
FREE_RETENTION_DAYS = 7


@dataclass
class Settings:
    # --- storage ---
    db_path: str = DEFAULT_DB_PATH
    retention_days: int = FREE_RETENTION_DAYS

    # --- MQTT / Zigbee2MQTT ---
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_tls: bool = False
    mqtt_client_id: str = "mesh-sentinel"
    mqtt_auto_discover: bool = True
    z2m_base_topic: str = "zigbee2mqtt"
    z2m_enabled: bool = True

    # --- Home Assistant ---
    ha_url: str = "http://supervisor/core"
    ha_token: str | None = None
    ha_enabled: bool = True

    # --- detection thresholds ---
    offline_grace_seconds: int = 180
    mains_stale_minutes: int = 90
    battery_stale_hours: int = 24
    evaluation_interval_seconds: int = 20
    recovery_confirm_seconds: int = 120
    restart_window_seconds: int = 600
    router_window_seconds: int = 300
    mass_outage_window_seconds: int = 600
    mass_outage_min_devices: int = 3
    linkquality_degraded: int = 20

    # --- topology ---
    topology_snapshot_interval_minutes: int = 15
    # An active networkmap scan floods the mesh with route requests. It stays
    # opt-in; the periodic snapshot is passive (cached device state) by default.
    topology_active_scan: bool = False
    topology_active_scan_interval_minutes: int = 360
    coordinator_check_interval_minutes: int = 5
    retention_interval_minutes: int = 60

    # --- runtime ---
    host: str = "0.0.0.0"
    port: int = 8099
    log_level: str = "INFO"
    edition: str = "free"

    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_retention_days(self) -> int:
        if self.edition == "free":
            return min(self.retention_days, FREE_RETENTION_DAYS)
        return self.retention_days


def _coerce(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(default, bool):
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return bool(raw)
    if isinstance(default, int):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
    if isinstance(default, str) or default is None:
        text = str(raw).strip()
        return text or default
    return raw


def load_settings(
    options_path: str | os.PathLike[str] = DEFAULT_OPTIONS_PATH,
    environ: dict[str, str] | None = None,
) -> Settings:
    """Build settings from the add-on options file, overlaid with env vars."""

    environ = dict(os.environ if environ is None else environ)
    settings = Settings()

    options: dict[str, Any] = {}
    path = Path(options_path)
    if path.is_file():
        try:
            options = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:  # pragma: no cover - defensive
            _LOGGER.warning("Could not read add-on options at %s: %s", path, err)

    known = {f for f in vars(settings)} - {"extra"}
    for key, value in options.items():
        if key in known:
            setattr(settings, key, _coerce(value, getattr(settings, key)))
        else:
            settings.extra[key] = value

    for key in known:
        env_key = f"MESH_SENTINEL_{key.upper()}"
        if env_key in environ:
            setattr(settings, key, _coerce(environ[env_key], getattr(settings, key)))

    # The Supervisor injects a scoped token for the add-on; prefer it over a
    # long-lived token pasted into the options.
    if not settings.ha_token:
        settings.ha_token = environ.get("SUPERVISOR_TOKEN") or environ.get("HASSIO_TOKEN")

    settings.retention_days = max(1, settings.retention_days)
    settings.evaluation_interval_seconds = max(5, settings.evaluation_interval_seconds)
    return settings
