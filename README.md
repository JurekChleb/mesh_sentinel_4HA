# Mesh Sentinel for Home Assistant

A local flight recorder and diagnostician for your device network.

Most tools tell you a device is `unavailable`. Mesh Sentinel tells you **what
happened, why those events belong together, and what to check first** — and it
does it without ever touching your network.

```
Incident: devices unavailable in part of the flat
10:11  router "IKEA salon" stopped responding
10:13  five devices timed out / stopped reporting
10:16  Zigbee2MQTT is still running, the coordinator answers
Conclusion: probably the router or its power. Not Home Assistant, not the coordinator.
Next step: check power at the router, then run a coordinator check.
```

**Version 0.1.0 — Zigbee2MQTT only.** ZHA, Z-Wave and Thread/Matter come later,
once the core is trustworthy. Their diagnostic telemetry is far less uniform, and
guessing on top of thin data is exactly what this product exists to avoid.

## What it does, and what it deliberately does not

It **does**: collect device and network health signals continuously, store them
locally, detect incidents, build a readable timeline, and name a probable cause
with the evidence behind it.

It **does not**: reset anything, re-pair anything, change a Zigbee channel, or
make any other change to your network. v0.1.0 diagnoses and warns. Nothing else.

Your data never leaves Home Assistant. There is no telemetry, no account, and no
cloud dependency. The Home Assistant token stays in the app's own secret
storage.

## Install

Mesh Sentinel is a Home Assistant **app** — a container the Supervisor runs
alongside Home Assistant. (Home Assistant 2026.2 renamed add-ons to apps; it is
the same thing, and the manifest files still use the old `addon` names.) It is
not a HACS integration, so it needs Home Assistant OS or Supervised; Container
and Core installs have no app store.

1. In Home Assistant: **Settings → Apps → ⋮ → Repositories**
   (this is the Supervisor's own dialog, not HACS's "Custom repositories").
2. Add `https://github.com/JurekChleb/mesh_sentinel_4HA`. The repository must be
   public — the Supervisor clones it without credentials.
3. Install **Mesh Sentinel**, then start it.
4. Open it from the sidebar (it is served through Ingress — no port to expose).

To try it without publishing the repository, copy the contents of `addon/` into
`/addons/mesh_sentinel/` on the host (the Samba share app exposes that folder)
and use **⋮ → Check for updates**; it appears under *Local apps*.

If the Mosquitto app is installed, the broker address and credentials are
taken from the Supervisor automatically. To use an external broker, fill in
`mqtt_host` in the app options; an explicit value always wins over discovery.

### Options

| Option | Default | What it changes |
| --- | --- | --- |
| `mqtt_host` / `mqtt_port` | discovered | Broker. Leave empty to use the Supervisor's MQTT service |
| `mqtt_username` / `mqtt_password` | discovered | Broker credentials |
| `z2m_base_topic` | `zigbee2mqtt` | Must match the Zigbee2MQTT `mqtt.base_topic` setting |
| `offline_grace_seconds` | `180` | How long a device must stay away before it can become an incident |
| `mains_stale_minutes` | `90` | Silence budget for a mains-powered device |
| `battery_stale_hours` | `24` | Silence budget for a battery device |
| `topology_snapshot_interval_minutes` | `15` | How often the passive network snapshot is written |
| `topology_active_scan` | `false` | Opt in to periodic **active** network map scans (see below) |
| `coordinator_check_interval_minutes` | `5` | How often the coordinator is asked whether it is alive |
| `retention_days` | `7` | History window (the Free edition caps this at 7) |

**About the network map.** An active scan asks every router for its routing
table and puts real load on the mesh, so the periodic snapshot is *passive* by
default: it records the state Zigbee2MQTT already publishes. Turn on
`topology_active_scan` (or press **Network map** in the UI) to record actual
parent/child links — the router rule states a higher confidence when it has them,
and says so explicitly when it does not.

## The three screens

* **Overview** — health score with the reasons behind it, per-integration device
  counts, active incidents, and the devices that need attention.
* **Incidents** — cards with a timeline. Opening one shows *what happened*,
  *why we link these events together*, *what we could not determine*, and
  *what to do* — plus a before/after comparison of the network 15 minutes
  before the incident against the state after it.
* **Device cockpit** — last seen, link quality trend, battery, routing parent,
  related incidents and raw events, and a **mark as critical** switch that
  raises the severity of anything involving that device.

## Free vs Pro

v0.1.0 ships the Free edition only; the gate exists in code
(`Settings.effective_retention_days`) but nothing is withheld yet.

| Area | Free | Pro (later) |
| --- | --- | --- |
| Zigbee2MQTT | Full support | Full support |
| ZHA | Device status and basic events (0.2.0) | Extended correlation and history |
| Z-Wave / Thread | — | Later releases |
| History | 7 days | 90 days, or unlimited locally |
| Incidents | List, timeline, cause and evidence | Grouping across integrations, richer correlation |
| Alerts | One basic "device offline" alert | Escalation, recovery, grouping, quiet hours, priorities |
| Reports | Manual view | Weekly report, PDF/HTML incident export |
| Configuration | Default rules | Custom thresholds, critical devices, exclusions |

Critical alerts will never depend on a licence server, and losing a licence will
never disable the Free behaviour.

## Development

```bash
# backend
cd addon/backend
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m mesh_sentinel          # http://127.0.0.1:8099

# frontend (proxies /api to the backend above)
cd addon/frontend && npm ci && npm run dev

# tests
python -m pytest
```

Configuration comes from `/data/options.json` when running as an app, and
from `MESH_SENTINEL_*` environment variables otherwise
(`MESH_SENTINEL_DB_PATH`, `MESH_SENTINEL_MQTT_HOST`, …).

## Repository layout

```
addon/                 app build context (the Supervisor builds from here)
  config.yaml          app manifest, options and schema
  Dockerfile           two stages: build the frontend, then the runtime image
  backend/             Python: collectors, detectors, correlation, storage, API
  frontend/            React + TypeScript UI served through Ingress
docs/                  architecture, incident catalogue, test plan, roadmap
tests/                 the incident scenarios, collector parsing, API contract
```

`backend/` and `frontend/` live inside `addon/` because the Supervisor builds an
app with its own directory as the Docker build context.

## Documentation

* [Incident catalogue](docs/incidents.md) — the ten scenarios and which rules cover them
* [Architecture](docs/architecture.md) — data model and event flow
* [Test plan](docs/testing.md) — the controlled, reversible tests to run on a real install
* [Roadmap](docs/roadmap.md) — what 0.2.0 and Pro add
* [Szybki start (PL)](docs/pl/szybki-start.md)

## Licence

MIT — see [LICENSE](LICENSE).
