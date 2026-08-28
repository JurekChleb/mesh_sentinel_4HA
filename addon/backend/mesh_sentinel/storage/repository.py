"""All SQL lives here. Everything above this layer speaks in domain objects."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Sequence

from ..models import Device, EvidenceItem, Event, Hypothesis, Incident, Snapshot
from .db import Database


def _loads(raw: Any, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def _device_from_row(row: sqlite3.Row) -> Device:
    return Device(
        id=row["id"],
        network_id=row["network_id"],
        source=row["source"],
        integration=row["integration"],
        ieee=row["ieee"],
        friendly_name=row["friendly_name"],
        vendor=row["vendor"],
        model=row["model"],
        device_type=row["device_type"],
        power_source=row["power_source"],
        is_critical=bool(row["is_critical"]),
        disabled=bool(row["disabled"]),
        supported=bool(row["supported"]),
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        last_message_at=row["last_message_at"],
        availability=row["availability"],
        availability_since=row["availability_since"],
        parent_id=row["parent_id"],
        linkquality=row["linkquality"],
        battery=row["battery"],
    )


def _event_from_row(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        ts=row["ts"],
        source=row["source"],
        event_type=row["event_type"],
        device_id=row["device_id"],
        network_id=row["network_id"],
        severity=row["severity"],
        payload=_loads(row["payload_json"], {}),
    )


def _incident_from_row(row: sqlite3.Row) -> Incident:
    return Incident(
        id=row["id"],
        kind=row["kind"],
        correlation_key=row["correlation_key"],
        status=row["status"],
        severity=row["severity"],
        title=row["title"],
        conclusion=row["conclusion"],
        recommended_action=row["recommended_action"],
        confidence=row["confidence"],
        started_at=row["started_at"],
        updated_at=row["updated_at"],
        resolved_at=row["resolved_at"],
        cause_device_id=row["cause_device_id"],
        network_id=row["network_id"],
        superseded_by=row["superseded_by"],
        unknowns=_loads(row["unknowns_json"], []),
    )


class Repository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- helpers -------------------------------------------------------------
    @property
    def _conn(self) -> sqlite3.Connection:
        return self._db.connection

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._db.lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._db.lock:
            return list(self._conn.execute(sql, params).fetchall())

    # -- events --------------------------------------------------------------
    def add_event(self, event: Event) -> Event:
        cur = self._execute(
            "INSERT INTO events(ts, source, event_type, device_id, network_id, severity, payload_json)"
            " VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                event.ts,
                event.source,
                event.event_type,
                event.device_id,
                event.network_id,
                event.severity,
                json.dumps(event.payload, default=str),
            ),
        )
        event.id = int(cur.lastrowid or 0)
        return event

    def events_between(
        self,
        start: float,
        end: float,
        event_types: Iterable[str] | None = None,
        device_id: str | None = None,
        limit: int = 2000,
    ) -> list[Event]:
        sql = "SELECT * FROM events WHERE ts >= ? AND ts <= ?"
        params: list[Any] = [start, end]
        types = list(event_types or [])
        if types:
            sql += f" AND event_type IN ({','.join('?' * len(types))})"
            params.extend(types)
        if device_id:
            sql += " AND device_id = ?"
            params.append(device_id)
        sql += " ORDER BY ts ASC, id ASC LIMIT ?"
        params.append(limit)
        return [_event_from_row(r) for r in self._query(sql, params)]

    def recent_events(self, limit: int = 100, device_id: str | None = None) -> list[Event]:
        sql = "SELECT * FROM events"
        params: list[Any] = []
        if device_id:
            sql += " WHERE device_id = ?"
            params.append(device_id)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        params.append(limit)
        return [_event_from_row(r) for r in self._query(sql, params)]

    def last_event(self, event_type: str, network_id: str | None = None) -> Event | None:
        sql = "SELECT * FROM events WHERE event_type = ?"
        params: list[Any] = [event_type]
        if network_id:
            sql += " AND network_id = ?"
            params.append(network_id)
        sql += " ORDER BY ts DESC, id DESC LIMIT 1"
        rows = self._query(sql, params)
        return _event_from_row(rows[0]) if rows else None

    # -- devices -------------------------------------------------------------
    def upsert_device(self, device: Device) -> None:
        self._execute(
            """
            INSERT INTO devices(id, network_id, source, integration, ieee, friendly_name,
                                vendor, model, device_type, power_source, supported,
                                first_seen, last_seen, last_message_at, availability,
                                availability_since, parent_id, linkquality, battery)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                network_id      = excluded.network_id,
                integration     = excluded.integration,
                ieee            = COALESCE(excluded.ieee, devices.ieee),
                friendly_name   = COALESCE(excluded.friendly_name, devices.friendly_name),
                vendor          = COALESCE(excluded.vendor, devices.vendor),
                model           = COALESCE(excluded.model, devices.model),
                device_type     = CASE WHEN excluded.device_type = 'unknown'
                                       THEN devices.device_type ELSE excluded.device_type END,
                power_source    = CASE WHEN excluded.power_source = 'unknown'
                                       THEN devices.power_source ELSE excluded.power_source END,
                supported       = excluded.supported,
                first_seen      = COALESCE(devices.first_seen, excluded.first_seen),
                last_seen       = MAX(COALESCE(devices.last_seen, 0), COALESCE(excluded.last_seen, 0)),
                parent_id       = COALESCE(excluded.parent_id, devices.parent_id)
            """,
            (
                device.id,
                device.network_id,
                device.source,
                device.integration,
                device.ieee,
                device.friendly_name,
                device.vendor,
                device.model,
                device.device_type,
                device.power_source,
                int(device.supported),
                device.first_seen,
                device.last_seen,
                device.last_message_at,
                device.availability,
                device.availability_since,
                device.parent_id,
                device.linkquality,
                device.battery,
            ),
        )

    def get_device(self, device_id: str) -> Device | None:
        rows = self._query("SELECT * FROM devices WHERE id = ?", (device_id,))
        return _device_from_row(rows[0]) if rows else None

    def list_devices(self, network_id: str | None = None) -> list[Device]:
        sql = "SELECT * FROM devices"
        params: list[Any] = []
        if network_id:
            sql += " WHERE network_id = ?"
            params.append(network_id)
        sql += " ORDER BY COALESCE(friendly_name, id) COLLATE NOCASE ASC"
        return [_device_from_row(r) for r in self._query(sql, params)]

    def set_availability(self, device_id: str, availability: str, ts: float) -> bool:
        """Return True when the availability actually changed."""

        with self._db.lock:
            row = self._conn.execute(
                "SELECT availability FROM devices WHERE id = ?", (device_id,)
            ).fetchone()
            if row is None:
                return False
            changed = row["availability"] != availability
            self._conn.execute(
                "UPDATE devices SET availability = ?, availability_since = "
                "CASE WHEN availability = ? THEN COALESCE(availability_since, ?) ELSE ? END"
                " WHERE id = ?",
                (availability, availability, ts, ts, device_id),
            )
            self._conn.commit()
            return changed

    def touch_device(
        self,
        device_id: str,
        ts: float,
        linkquality: int | None = None,
        battery: int | None = None,
    ) -> None:
        self._execute(
            "UPDATE devices SET last_seen = MAX(COALESCE(last_seen, 0), ?),"
            " last_message_at = MAX(COALESCE(last_message_at, 0), ?),"
            " linkquality = COALESCE(?, linkquality),"
            " battery = COALESCE(?, battery)"
            " WHERE id = ?",
            (ts, ts, linkquality, battery, device_id),
        )

    def set_critical(self, device_id: str, is_critical: bool) -> bool:
        cur = self._execute(
            "UPDATE devices SET is_critical = ? WHERE id = ?",
            (int(is_critical), device_id),
        )
        return cur.rowcount > 0

    def set_disabled(self, device_id: str, disabled: bool) -> bool:
        cur = self._execute(
            "UPDATE devices SET disabled = ? WHERE id = ?", (int(disabled), device_id)
        )
        return cur.rowcount > 0

    def set_parent(self, device_id: str, parent_id: str | None) -> None:
        self._execute(
            "UPDATE devices SET parent_id = ? WHERE id = ?", (parent_id, device_id)
        )

    # -- snapshots -----------------------------------------------------------
    def add_snapshot(self, snapshot: Snapshot) -> None:
        self._execute(
            "INSERT INTO device_snapshots(ts, device_id, availability, last_seen,"
            " linkquality, battery, rssi, parent_id, payload_json)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot.ts,
                snapshot.device_id,
                snapshot.availability,
                snapshot.last_seen,
                snapshot.linkquality,
                snapshot.battery,
                snapshot.rssi,
                snapshot.parent_id,
                json.dumps(snapshot.payload, default=str),
            ),
        )

    def snapshots_for_device(
        self, device_id: str, since: float, limit: int = 500
    ) -> list[Snapshot]:
        rows = self._query(
            "SELECT * FROM device_snapshots WHERE device_id = ? AND ts >= ?"
            " ORDER BY ts ASC LIMIT ?",
            (device_id, since, limit),
        )
        return [
            Snapshot(
                id=r["id"],
                ts=r["ts"],
                device_id=r["device_id"],
                availability=r["availability"],
                last_seen=r["last_seen"],
                linkquality=r["linkquality"],
                battery=r["battery"],
                rssi=r["rssi"],
                parent_id=r["parent_id"],
                payload=_loads(r["payload_json"], {}),
            )
            for r in rows
        ]

    def snapshot_at(self, ts: float, network_id: str | None = None) -> list[dict[str, Any]]:
        """State of every device as of ``ts`` - the 'before' half of before/after."""

        sql = (
            "SELECT s.* FROM device_snapshots s"
            " JOIN (SELECT device_id, MAX(ts) AS ts FROM device_snapshots"
            "       WHERE ts <= ? GROUP BY device_id) latest"
            "   ON s.device_id = latest.device_id AND s.ts = latest.ts"
        )
        params: list[Any] = [ts]
        if network_id:
            sql += (
                " JOIN devices d ON d.id = s.device_id AND d.network_id = ?"
            )
            params.append(network_id)
        return [dict(r) for r in self._query(sql, params)]

    # -- topology ------------------------------------------------------------
    def add_topology_snapshot(
        self,
        ts: float,
        network_id: str,
        payload: dict[str, Any],
        kind: str = "passive",
        reason: str = "scheduled",
    ) -> None:
        nodes = payload.get("nodes", [])
        routers = [n for n in nodes if n.get("device_type") in ("router", "coordinator")]
        self._execute(
            "INSERT INTO topology_snapshots(ts, network_id, kind, reason, device_count,"
            " router_count, payload_json) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                ts,
                network_id,
                kind,
                reason,
                len(nodes),
                len(routers),
                json.dumps(payload, default=str),
            ),
        )

    def topology_at(self, ts: float, network_id: str) -> dict[str, Any] | None:
        rows = self._query(
            "SELECT * FROM topology_snapshots WHERE network_id = ? AND ts <= ?"
            " ORDER BY ts DESC LIMIT 1",
            (network_id, ts),
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "ts": row["ts"],
            "kind": row["kind"],
            "reason": row["reason"],
            "device_count": row["device_count"],
            "router_count": row["router_count"],
            **_loads(row["payload_json"], {}),
        }

    def last_topology_snapshot_ts(self, network_id: str, kind: str | None = None) -> float | None:
        sql = "SELECT MAX(ts) AS ts FROM topology_snapshots WHERE network_id = ?"
        params: list[Any] = [network_id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        rows = self._query(sql, params)
        return rows[0]["ts"] if rows and rows[0]["ts"] is not None else None

    # -- incidents -----------------------------------------------------------
    def open_incident_by_key(self, correlation_key: str) -> Incident | None:
        rows = self._query(
            "SELECT * FROM incidents WHERE correlation_key = ? AND status = 'open'",
            (correlation_key,),
        )
        if not rows:
            return None
        incident = _incident_from_row(rows[0])
        incident.affected_device_ids = self.incident_device_ids(incident.id)
        return incident

    def create_incident(self, hypothesis: Hypothesis, now: float) -> Incident:
        cur = self._execute(
            "INSERT INTO incidents(kind, correlation_key, status, severity, title,"
            " conclusion, recommended_action, confidence, started_at, updated_at,"
            " cause_device_id, network_id, unknowns_json)"
            " VALUES(?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                hypothesis.kind,
                hypothesis.correlation_key,
                hypothesis.severity,
                hypothesis.title,
                hypothesis.conclusion,
                hypothesis.recommended_action,
                hypothesis.confidence,
                hypothesis.started_at,
                now,
                hypothesis.cause_device_id,
                hypothesis.network_id,
                json.dumps(hypothesis.unknowns),
            ),
        )
        incident_id = int(cur.lastrowid or 0)
        if hypothesis.cause_device_id:
            self.link_device(incident_id, hypothesis.cause_device_id, "cause")
        for device_id in hypothesis.affected_device_ids:
            self.link_device(incident_id, device_id, "affected")
        for item in hypothesis.evidence:
            self.add_evidence(incident_id, item)
        incident = self.get_incident(incident_id)
        assert incident is not None
        return incident

    def update_incident(self, incident_id: int, hypothesis: Hypothesis, now: float) -> None:
        self._execute(
            "UPDATE incidents SET severity = ?, title = ?, conclusion = ?,"
            " recommended_action = ?, confidence = ?, updated_at = ?,"
            " cause_device_id = COALESCE(?, cause_device_id), unknowns_json = ?"
            " WHERE id = ?",
            (
                hypothesis.severity,
                hypothesis.title,
                hypothesis.conclusion,
                hypothesis.recommended_action,
                hypothesis.confidence,
                now,
                hypothesis.cause_device_id,
                json.dumps(hypothesis.unknowns),
                incident_id,
            ),
        )
        if hypothesis.cause_device_id:
            self.link_device(incident_id, hypothesis.cause_device_id, "cause")
        for device_id in hypothesis.affected_device_ids:
            self.link_device(incident_id, device_id, "affected")
        for item in hypothesis.evidence:
            self.add_evidence(incident_id, item)

    def resolve_incident(self, incident_id: int, now: float) -> None:
        self._execute(
            "UPDATE incidents SET status = 'resolved', resolved_at = ?, updated_at = ?"
            " WHERE id = ? AND status = 'open'",
            (now, now, incident_id),
        )

    def supersede_incident(self, incident_id: int, superseded_by: int, now: float) -> None:
        """Close an incident because a better explanation now covers its devices."""

        self._execute(
            "UPDATE incidents SET status = 'resolved', resolved_at = ?, updated_at = ?,"
            " superseded_by = ? WHERE id = ? AND status = 'open'",
            (now, now, superseded_by, incident_id),
        )

    def get_incident(self, incident_id: int) -> Incident | None:
        rows = self._query("SELECT * FROM incidents WHERE id = ?", (incident_id,))
        if not rows:
            return None
        incident = _incident_from_row(rows[0])
        incident.affected_device_ids = self.incident_device_ids(incident.id)
        return incident

    def list_incidents(
        self, status: str | None = None, since: float | None = None, limit: int = 50
    ) -> list[Incident]:
        sql = "SELECT * FROM incidents WHERE 1 = 1"
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if since is not None:
            sql += " AND started_at >= ?"
            params.append(since)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        incidents = [_incident_from_row(r) for r in self._query(sql, params)]
        for incident in incidents:
            incident.affected_device_ids = self.incident_device_ids(incident.id)
        return incidents

    def incidents_for_device(self, device_id: str, limit: int = 20) -> list[Incident]:
        rows = self._query(
            "SELECT i.* FROM incidents i JOIN incident_devices d ON d.incident_id = i.id"
            " WHERE d.device_id = ? ORDER BY i.started_at DESC LIMIT ?",
            (device_id, limit),
        )
        return [_incident_from_row(r) for r in rows]

    def link_device(self, incident_id: int, device_id: str, role: str) -> None:
        self._execute(
            "INSERT INTO incident_devices(incident_id, device_id, role) VALUES(?, ?, ?)"
            " ON CONFLICT(incident_id, device_id) DO UPDATE SET role ="
            " CASE WHEN incident_devices.role = 'cause' THEN 'cause' ELSE excluded.role END",
            (incident_id, device_id, role),
        )

    def incident_device_ids(self, incident_id: int, role: str | None = None) -> list[str]:
        sql = "SELECT device_id FROM incident_devices WHERE incident_id = ?"
        params: list[Any] = [incident_id]
        if role:
            sql += " AND role = ?"
            params.append(role)
        return [r["device_id"] for r in self._query(sql, params)]

    def incident_device_roles(self, incident_id: int) -> dict[str, str]:
        rows = self._query(
            "SELECT device_id, role FROM incident_devices WHERE incident_id = ?",
            (incident_id,),
        )
        return {r["device_id"]: r["role"] for r in rows}

    def add_evidence(self, incident_id: int, item: EvidenceItem) -> None:
        # The dedupe index keeps repeated evaluations from stacking identical lines.
        self._execute(
            "INSERT OR IGNORE INTO incident_evidence(incident_id, ts, kind, description,"
            " device_id, event_id, payload_json) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                incident_id,
                item.ts,
                item.kind,
                item.description,
                item.device_id,
                item.event_id,
                json.dumps(item.payload, default=str),
            ),
        )

    def evidence_for(self, incident_id: int) -> list[EvidenceItem]:
        rows = self._query(
            "SELECT * FROM incident_evidence WHERE incident_id = ? ORDER BY ts ASC, id ASC",
            (incident_id,),
        )
        return [
            EvidenceItem(
                id=r["id"],
                ts=r["ts"],
                kind=r["kind"],
                description=r["description"],
                device_id=r["device_id"],
                event_id=r["event_id"],
                payload=_loads(r["payload_json"], {}),
            )
            for r in rows
        ]

    # -- retention -----------------------------------------------------------
    def purge_before(self, cutoff: float) -> dict[str, int]:
        deleted = {}
        with self._db.lock:
            cur = self._conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
            deleted["events"] = cur.rowcount
            cur = self._conn.execute("DELETE FROM device_snapshots WHERE ts < ?", (cutoff,))
            deleted["device_snapshots"] = cur.rowcount
            cur = self._conn.execute(
                "DELETE FROM topology_snapshots WHERE ts < ?", (cutoff,)
            )
            deleted["topology_snapshots"] = cur.rowcount
            cur = self._conn.execute(
                "DELETE FROM incidents WHERE status = 'resolved' AND"
                " COALESCE(resolved_at, updated_at) < ?",
                (cutoff,),
            )
            deleted["incidents"] = cur.rowcount
            # incident_evidence / incident_devices cascade via foreign keys.
            self._conn.commit()
        return deleted

    def counts(self) -> dict[str, int]:
        tables = ["events", "devices", "device_snapshots", "incidents", "topology_snapshots"]
        out: dict[str, int] = {}
        for table in tables:
            rows = self._query(f"SELECT COUNT(*) AS c FROM {table}")
            out[table] = int(rows[0]["c"])
        return out
