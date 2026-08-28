# Architecture

```
Zigbee2MQTT ──MQTT──┐
                    ├── collectors ──► normalised events ──► SQLite (WAL)
Home Assistant ─WS──┘                                            │
                                                                 ▼
                                          detectors (staleness, degradation)
                                                                 │
                                                                 ▼
                                     correlation engine (deterministic rules)
                                                                 │
                                                                 ▼
                                             incidents + evidence ──► FastAPI ──► React UI (Ingress)
```

## Principles

**No model decides anything.** The correlation core is deterministic and
inspectable. Every incident can be replayed from the stored events, and every
rule is a small function that either claims a set of devices or does not.

**Time is injected, never read.** The engine is handed `now`; it never calls the
clock. That is what makes the whole detection story reproducible in tests — the
scenario suite simulates 25 hours in milliseconds.

**Collectors are split from transports.** `Z2MMessageHandler` is pure
message-to-database with no sockets, so every parsing decision is testable from a
recorded payload. `Z2MCollector` owns only the connection and the retry loop.

## Data model

All timestamps are unix epoch seconds, UTC.

| Table | Purpose |
| --- | --- |
| `events` | Every normalised signal: `ts, source, event_type, device_id, network_id, severity, payload_json` |
| `devices` | Inventory: identity, type (router / end device / coordinator), power source, availability, parent, critical flag |
| `device_snapshots` | Periodic per-device state: last seen, link quality, battery, availability — the raw material for trends and for before/after |
| `incidents` | Correlated problems with conclusion, recommended action, confidence and unknowns |
| `incident_evidence` | The individual "why we link these" lines behind one incident |
| `incident_devices` | Which devices an incident involves, and in which role (`cause` / `affected`) |
| `topology_snapshots` | Periodic map of the network, passive or from an active scan |

A partial unique index on `incidents(correlation_key) WHERE status = 'open'`
guarantees one open incident per root cause; re-evaluating updates it instead of
creating a second one. A unique index on the evidence table stops repeated
evaluations from stacking identical lines.

SQLite runs in WAL mode so the API reads while collectors write.

## Event types

Collectors only ever emit the constants in `mesh_sentinel/models.py`. Anything
else is a bug: the rules match on these names, so a vendor-specific string
leaking upward would silently break correlation.

`device_online` · `device_offline` · `device_seen` · `device_joined` ·
`device_left` · `device_timeout` · `device_error` · `device_low_battery` ·
`device_degraded` · `router_missing` · `bridge_online` · `bridge_offline` ·
`bridge_restart` · `coordinator_ok` · `coordinator_missing` · `mqtt_connected` ·
`mqtt_disconnected` · `home_assistant_restart` · `ota_update` · `addon_start`

## Zigbee2MQTT topics consumed

| Topic | Used for |
| --- | --- |
| `<base>/bridge/state` | Bridge up/down; an offline→online transition is recorded as a restart |
| `<base>/bridge/info` | Coordinator identity and version |
| `<base>/bridge/devices` | The inventory: type, power source, vendor, model, disabled flag |
| `<base>/bridge/event` | Joins, interviews, leaves |
| `<base>/bridge/logging` | Coordinator failures told apart from ordinary per-device timeouts |
| `<base>/bridge/response/health_check` | Coordinator check results |
| `<base>/bridge/response/networkmap` | Routing topology and parent links |
| `<base>/bridge/response/device/ota_update/*` | OTA activity |
| `<base>/+/availability` | Per-device availability |
| `<base>/+` | Device state: `last_seen`, `linkquality`, `battery` |

## Background jobs

| Job | Interval | Notes |
| --- | --- | --- |
| Detection pass | 20s | staleness → degradation → correlation |
| Passive topology snapshot | 15 min | Free; no mesh traffic. An extra one is taken right after a new incident so before/after has an "after" |
| Active network map scan | opt-in, ≥6h | Real load on the mesh; off by default |
| Coordinator health check | 5 min | One request to the bridge |
| Retention | 60 min | Drops events, snapshots and *resolved* incidents past the window. Open incidents are never aged out |

## Home Assistant integration

The app runs behind Ingress, so nothing is exposed on the network. The
frontend resolves `./api` relative to wherever Ingress mounted it; no path is
hardcoded. MQTT credentials come from the Supervisor's `mqtt:need` service, so
the broker password need not be typed into the app options at all.

The Home Assistant WebSocket connection is deliberately small in 0.1.0: it
records HA restarts, so a timeline can say "everything went quiet because Home
Assistant restarted". ZHA correlation builds on that connection in 0.2.0 —
against documented APIs only, not private ones that break on an update.
