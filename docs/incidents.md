# Incident catalogue

The MVP is defined by the incidents it must recognise — not by "everything about
Zigbee". Each one has a success criterion: **after the event, a person reads one
understandable conclusion, not a raw log.**

## Implemented in 0.1.0

| # | Scenario | Rule | Incident kind | Severity | Confidence |
| --- | --- | --- | --- | --- | --- |
| 1 | A single battery sensor stops reporting | `rule_single_device` | `device_offline` | warning (critical if the device is marked critical) | 0.70 |
| 2 | A router disappears, devices behind it follow | `rule_router_failure` | `router_failure` | error | 0.85 with a network map, 0.55 without |
| 3 | Zigbee2MQTT restarts and comes back | `rule_service_restart` | `service_restart` | warning | 0.80 |
| 4 | The USB coordinator is gone after a host restart | `rule_data_source` | `coordinator_unavailable` | critical | 0.90 |
| 5 | One device with rising timeouts or a falling link | `rule_device_degraded` | `device_degraded` | warning | 0.60 |
| 6 | A device is briefly offline | — (grace window) | *no incident* | — | — |
| 7 | Many devices drop with no identifiable cause | `rule_mass_outage` | `mass_outage` | error | 0.50 |
| 8 | The MQTT broker becomes unreachable | `rule_data_source` | `data_source_unavailable` | error | 0.95 |
| 9 | The Zigbee2MQTT bridge reports itself offline | `rule_data_source` | `bridge_unavailable` | critical | 0.90 |

## Planned

| # | Scenario | Needs | Target |
| --- | --- | --- | --- |
| 10 | Thread and Zigbee on potentially colliding channels | Thread/Matter channel data | after ZHA lands |

Scenario 10 will *suggest a radio check*. It will never change a channel by itself.

## Rule precedence

Rules run in order, and a device claimed by an earlier rule is not offered to a
later one. That is what turns one root cause into one incident instead of five:

```
1. rule_data_source     MQTT / bridge / coordinator down -> claims everything
2. rule_service_restart devices that dropped around a bridge restart
3. rule_router_failure  a router plus the devices behind or right after it
4. rule_mass_outage     3+ devices in one 10-minute window, cause unknown
5. rule_single_device   whatever is left, one incident each
6. rule_device_degraded still reachable, but getting worse
```

## Superseding: detection is staggered

Devices are not confirmed offline at the same instant. A router is usually past
its grace window a minute or two before the devices behind it are, so a
`device_offline` incident for the router legitimately opens *first* — and then
the router failure becomes visible.

Leaving both open would mean one root cause producing several incidents, which is
the exact failure this layer exists to prevent. So when a better explanation
covers all of a weaker incident's devices, the weaker one is closed with
`superseded_by` pointing at the new incident and an evidence line naming it. The
UI shows it as *Superseded by #N* rather than *Resolved*, because nothing
actually got better.

Ranking, best explanation first:

```
0  data_source_unavailable / coordinator_unavailable / bridge_unavailable
1  service_restart
2  router_failure
3  mass_outage
4  device_offline
5  device_degraded
```

A device that drops entirely supersedes its own `device_degraded` incident for
the same reason.

## What every hypothesis must carry

A rule that cannot state its unknowns is not ready to ship. Each incident stores:

* **conclusion** — what we believe happened, in plain language;
* **evidence** — the specific events that led there, with timestamps;
* **unknowns** — what the data could not settle;
* **recommended action** — the next thing a human should check;
* **confidence** — a number that must look like a guess when it is one.

## Why the timing rules look the way they do

* **`offline_grace_seconds` (180s).** A device is not an incident the moment it
  goes quiet. Scenario 6 exists to make sure a blip never pages anybody, and this
  single threshold is what enforces it.
* **Different silence budgets.** A mains device that says nothing for 90 minutes
  is suspicious; a battery sensor doing the same is normal. Budgets follow the
  power source, which Zigbee2MQTT reports in `bridge/devices`.
* **A restart is a warning, not an outage.** Scenario 3 must not read as a
  catastrophe, because it is not one — the incident exists so the timeline
  explains the gap, and it resolves itself when devices come back.
* **Retained MQTT messages are not proof of life.** Zigbee2MQTT replays each
  device's last state when we connect. Treating that as a fresh report would make
  a device that died two days ago look healthy for another 90 minutes, so a
  retained message only counts if it carries its own `last_seen`.

Every row above is covered by a test in `tests/test_scenarios.py`.
