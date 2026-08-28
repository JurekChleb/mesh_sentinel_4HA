# Test plan for a real installation

The automated suite (`python -m pytest`) covers the scenarios against simulated
Zigbee2MQTT payloads. This document is the other half: controlled, **reversible**
tests on a live Home Assistant install.

Run them one at a time, and write down all four columns. The number that matters
is not "did it detect something" — it is **false alarms** and **missing data**.

## Before you start

* Note the app version and the Zigbee2MQTT version.
* Confirm Zigbee2MQTT has `availability` enabled — without it, offline detection
  falls back to silence budgets and is slower by design.
* Press **Network map** once so routing parents are recorded. The router rule is
  measurably more confident with them, and the difference is worth seeing.

## The tests

| # | Test | How to do it | Expected conclusion |
| --- | --- | --- | --- |
| 1 | Restart Zigbee2MQTT | Restart the Z2M app | One `service_restart` incident, **warning** severity, resolving itself when devices return |
| 2 | Restart Mesh Sentinel | Restart this app | No new incident. History and open incidents survive |
| 3 | Unplug one Zigbee router | Pull power from a mains router with devices behind it | One `router_failure` incident naming that router, with the affected devices listed |
| 4 | Remove one battery sensor's battery | Take the battery out | After the silence budget (24h by default), one `device_offline` incident for that device only |
| 5 | Detach the USB coordinator | Detach it from the VM after a host restart | One `coordinator_unavailable` incident pointing at the host/USB — **not** a Zigbee failure, and **not** one incident per device |
| 6 | Timeout and recovery | Move a device out of range, then back | `device_degraded`, then recovery |
| 7 | Brief restart | Restart Z2M and let it return within ~2 minutes | **No incident at all** |

## What to record

| Test | What actually happened | What the app concluded | False alarms | Missing data |
| --- | --- | --- | --- | --- |
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |
| 6 | | | | |
| 7 | | | | |

## Pass criteria

1. Every test produces **one** conclusion a person can act on, not a log dump.
2. Test 7 produces **zero** incidents.
3. Test 5 produces **one** incident, not one per device.
4. No incident claims a cause the evidence does not support — if the network map
   is stale, the router hypothesis must say so in its unknowns.

## Speeding up test 4

Waiting 24 hours is not practical for a first pass. Lower `battery_stale_hours`
to `1` in the app options, run the test, then set it back. Note in your
results that the threshold was changed — a detection tuned to an unrealistic
budget proves nothing about the default.

## If something is wrong

The raw evidence is in the database at `/data/mesh_sentinel.db` (SQLite, WAL).
`GET /api/events?limit=2000` returns the same stream as JSON through Ingress.
Every incident can be replayed from those events, because the correlation engine
is a pure function of the event stream and a timestamp.
