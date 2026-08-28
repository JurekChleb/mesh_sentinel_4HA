"""SQLite connection handling and schema migrations.

WAL mode lets the API read while collectors write. Everything is local to the
Home Assistant host; no row ever leaves the machine.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id                 TEXT PRIMARY KEY,
    network_id         TEXT NOT NULL,
    source             TEXT NOT NULL,
    integration        TEXT NOT NULL,
    ieee               TEXT,
    friendly_name      TEXT,
    vendor             TEXT,
    model              TEXT,
    device_type        TEXT NOT NULL DEFAULT 'unknown',
    power_source       TEXT NOT NULL DEFAULT 'unknown',
    is_critical        INTEGER NOT NULL DEFAULT 0,
    disabled           INTEGER NOT NULL DEFAULT 0,
    supported          INTEGER NOT NULL DEFAULT 1,
    first_seen         REAL,
    last_seen          REAL,
    last_message_at    REAL,
    availability       TEXT NOT NULL DEFAULT 'unknown',
    availability_since REAL,
    parent_id          TEXT,
    linkquality        INTEGER,
    battery            INTEGER
);
CREATE INDEX IF NOT EXISTS idx_devices_network ON devices(network_id);
CREATE INDEX IF NOT EXISTS idx_devices_availability ON devices(availability);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL NOT NULL,
    source       TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    device_id    TEXT,
    network_id   TEXT,
    severity     TEXT NOT NULL DEFAULT 'info',
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_device_ts ON events(device_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(event_type, ts);

CREATE TABLE IF NOT EXISTS device_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL NOT NULL,
    device_id    TEXT NOT NULL,
    availability TEXT NOT NULL,
    last_seen    REAL,
    linkquality  INTEGER,
    battery      INTEGER,
    rssi         INTEGER,
    parent_id    TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_snapshots_device_ts ON device_snapshots(device_id, ts);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON device_snapshots(ts);

CREATE TABLE IF NOT EXISTS incidents (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    kind               TEXT NOT NULL,
    correlation_key    TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'open',
    severity           TEXT NOT NULL DEFAULT 'warning',
    title              TEXT NOT NULL,
    conclusion         TEXT NOT NULL DEFAULT '',
    recommended_action TEXT NOT NULL DEFAULT '',
    confidence         REAL NOT NULL DEFAULT 0.0,
    started_at         REAL NOT NULL,
    updated_at         REAL NOT NULL,
    resolved_at        REAL,
    cause_device_id    TEXT,
    network_id         TEXT,
    unknowns_json      TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status, started_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_incidents_open_key
    ON incidents(correlation_key) WHERE status = 'open';

CREATE TABLE IF NOT EXISTS incident_devices (
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    device_id   TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'affected',
    PRIMARY KEY (incident_id, device_id)
);

CREATE TABLE IF NOT EXISTS incident_evidence (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id  INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    ts           REAL NOT NULL,
    kind         TEXT NOT NULL,
    description  TEXT NOT NULL,
    device_id    TEXT,
    event_id     INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_evidence_incident ON incident_evidence(incident_id, ts);
CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_dedupe
    ON incident_evidence(incident_id, kind, ts, IFNULL(device_id, ''));

CREATE TABLE IF NOT EXISTS topology_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL NOT NULL,
    network_id   TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'passive',
    reason       TEXT NOT NULL DEFAULT 'scheduled',
    device_count INTEGER NOT NULL DEFAULT 0,
    router_count INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_topology_ts ON topology_snapshots(network_id, ts);
"""


class Database:
    """Thin wrapper around a serialised sqlite3 connection."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=15.0)
        self._conn.row_factory = sqlite3.Row
        self._configure()
        self.migrate()

    def _configure(self) -> None:
        cur = self._conn.cursor()
        if self.path != ":memory:":
            cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=15000")
        self._conn.commit()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def migrate(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            current = int(row["value"]) if row else 0
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema v{current} is newer than this build "
                    f"(v{SCHEMA_VERSION}); downgrade is not supported."
                )
            if current != SCHEMA_VERSION:
                self._conn.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(SCHEMA_VERSION),),
                )
                _LOGGER.info("Database schema at v%s", SCHEMA_VERSION)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.commit()
            self._conn.close()
