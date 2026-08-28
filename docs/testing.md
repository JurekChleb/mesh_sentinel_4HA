# Test plan for a real installation

The automated suite (`python -m pytest`) covers the scenarios against simulated
Zigbee2MQTT payloads. This document is the other half: controlled, **reversible**
tests on a live Home Assistant install.

Run them one at a time, and write down all four columns. The number that matters
is not "did it detect something" — it is **false alarms** and **missing data**.

## Two ways to test

**Fault injection** (`scripts/simulate.py`) publishes the exact Zigbee2MQTT
messages a real failure produces. It covers every rule in minutes, including the
failures that are awkward to stage for real - losing the coordinator, or a whole
branch of the mesh at once - and it can check the results itself. Start here.

**Physical tests** (the table further down) are the ground truth. Injection
proves the rules fire on the right messages; only pulling a plug proves the
messages we expect are the messages Zigbee2MQTT actually sends. Do both, in that
order.

### Fault injection

The script publishes to a *separate* base topic, so it never touches your real
network. Point the app at that topic for the duration of the test:

1. App options: `z2m_base_topic: meshsentinel_test`, then restart the app.
   While this is set, your real network is not being watched. That is the trade
   for testing the real, installed app instead of a mock.
2. Optional but worth it: in the app's **Network** settings, map port `8099` so
   the script can verify results instead of you reading them off the screen.
3. Run it:

   ```bash
   pip install paho-mqtt
   python scripts/simulate.py --host <broker-ip> --api http://<ha-ip>:8099 all
   ```

   Add `--username` / `--password` if your broker needs them. One scenario at a
   time works too: `... simulate.py --host <broker-ip> router`.
4. Put `z2m_base_topic` back to `zigbee2mqtt` and restart the app.

Each scenario waits out the real grace and recovery windows, so a full run takes
around fifteen minutes. To make it quick, lower `offline_grace_seconds` to `20`
and `recovery_confirm_seconds` to `20` in the app options and pass
`--grace 20 --recovery 20` so the script's waits match. Put the defaults back
afterwards, and note in your results that the thresholds were changed - a
detection tuned to an unrealistic window proves nothing about the default.

With `--api` the script prints PASS/FAIL per scenario and checks more than the
incident kind: severity, how many devices were grouped, which device was blamed,
and that the conclusion, the recommended action and the unknowns are all
populated. Without it, it prints what to look for in the UI.

The scenarios map onto the catalogue in [incidents.md](incidents.md):
`single`, `router`, `restart`, `coordinator`, `mass`, `degraded`, `blip`,
`recover`. The one that matters most is `blip`: it must produce **nothing**.

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
