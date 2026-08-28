"""Storage, retention and configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import Network, device_entry
from mesh_sentinel import retention
from mesh_sentinel.config import FREE_RETENTION_DAYS, Settings, load_settings
from mesh_sentinel.models import Event
from mesh_sentinel.storage import Database, Repository


def test_schema_survives_a_restart(tmp_path: Path):
    path = str(tmp_path / "db.sqlite")
    first = Database(path)
    Repository(first).add_event(Event(ts=1.0, source="z2m", event_type="device_offline"))
    first.close()

    second = Database(path)
    assert len(Repository(second).recent_events()) == 1
    second.close()


def test_wal_is_enabled(tmp_path: Path):
    db = Database(str(tmp_path / "db.sqlite"))
    mode = db.connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    db.close()


def test_retention_drops_old_rows_but_keeps_open_incidents(small_network: Network):
    net = small_network
    net.availability("Czujnik salon", "offline")
    net.advance(400)
    net.evaluate()
    assert len(net.open_incidents()) == 1

    net.advance(30 * 86400)
    deleted = retention.purge(net.service.repo, net.service.settings, net.clock.now())

    assert deleted["events"] > 0
    assert len(net.open_incidents()) == 1, "an unresolved incident must never be aged out"


def test_retention_drops_resolved_incidents_past_the_window(small_network: Network):
    net = small_network
    net.availability("Czujnik salon", "offline")
    net.advance(400)
    net.evaluate()
    net.availability("Czujnik salon", "online")
    net.advance(200)
    net.evaluate()
    assert net.incidents(status="resolved")

    net.advance(30 * 86400)
    retention.purge(net.service.repo, net.service.settings, net.clock.now())
    assert net.incidents() == []


def test_evidence_is_removed_with_its_incident(small_network: Network):
    net = small_network
    net.availability("Czujnik salon", "offline")
    net.advance(400)
    net.evaluate()
    incident_id = net.open_incidents()[0].id
    net.availability("Czujnik salon", "online")
    net.advance(200)
    net.evaluate()

    net.advance(30 * 86400)
    retention.purge(net.service.repo, net.service.settings, net.clock.now())
    assert net.service.repo.evidence_for(incident_id) == []


def test_free_edition_caps_retention():
    settings = Settings(edition="free", retention_days=365)
    assert settings.effective_retention_days == FREE_RETENTION_DAYS
    pro = Settings(edition="pro", retention_days=90)
    assert pro.effective_retention_days == 90


def test_options_file_and_env_are_both_read(tmp_path: Path):
    options = tmp_path / "options.json"
    options.write_text(
        '{"mqtt_host": "broker.local", "mqtt_port": 8883, "mqtt_tls": true, '
        '"offline_grace_seconds": 42, "unknown_key": 1}'
    )
    settings = load_settings(options, environ={"MESH_SENTINEL_LOG_LEVEL": "DEBUG"})

    assert settings.mqtt_host == "broker.local"
    assert settings.mqtt_port == 8883 and settings.mqtt_tls is True
    assert settings.offline_grace_seconds == 42
    assert settings.log_level == "DEBUG"
    assert settings.extra["unknown_key"] == 1


def test_supervisor_token_is_picked_up(tmp_path: Path):
    settings = load_settings(tmp_path / "missing.json", environ={"SUPERVISOR_TOKEN": "abc"})
    assert settings.ha_token == "abc"


def test_missing_options_file_is_not_fatal(tmp_path: Path):
    settings = load_settings(tmp_path / "nope.json", environ={})
    assert settings.mqtt_host == ""  # unset means "ask the Supervisor"


def test_broker_falls_back_when_no_supervisor_is_present():
    from mesh_sentinel import supervisor

    settings = Settings()
    supervisor.resolve_mqtt(settings, environ={})
    assert settings.mqtt_host == "core-mosquitto"


def test_an_explicit_broker_is_never_overridden_by_discovery():
    from mesh_sentinel import supervisor

    settings = Settings(mqtt_host="broker.local", mqtt_port=8883)
    assert supervisor.discover_mqtt(settings, environ={"SUPERVISOR_TOKEN": "x"}) is False
    assert settings.mqtt_host == "broker.local" and settings.mqtt_port == 8883
