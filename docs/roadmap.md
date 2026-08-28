# Roadmap

## 0.1.0 — shipped

Zigbee2MQTT only. Events, SQLite storage, three screens, six correlation rules,
and a test suite covering the MVP scenarios. Diagnose and warn; change nothing.

## 0.2.0 — ZHA

ZHA is added with its data level labelled honestly, because it is not the same
as Zigbee2MQTT's:

* device availability and entity state;
* Home Assistant events and restarts;
* unavailability history;
* device-level diagnostics.

Full ZHA routing analysis waits until there is a stable, supported source for it.
The product will not be built on private Home Assistant APIs that break on an
update — a correlation that silently stops working is worse than one that was
never promised.

## 0.3.0 — alerting

Escalation, recovery notifications, grouping, quiet hours and priorities. Free
keeps one basic "device offline" alert.

## Later

* Z-Wave, then Thread/Matter — added only when their diagnostic telemetry is
  uniform enough to correlate rather than guess at.
* Weekly report, PDF/HTML incident export.
* Custom thresholds, critical device lists, exclusions.

## Pro edition and licensing

Pro is added **after** the Free edition passes the live test plan, not before.

* A local licence key.
* Periodic, non-invasive online verification.
* 14 days of full operation offline after the last successful verification.
* Free keeps working when a licence lapses. Only Pro history, reports and the
  extended correlation go away.
* **Critical alerts never depend on the licence server.**

The gate already has exactly one home in the code
(`Settings.effective_retention_days`), so adding Pro does not mean scattering
edition checks through the detection layer.

## Release order

1. Private repository, tested on one real install.
2. Public Free beta through a custom Home Assistant app repository.
3. Install documentation, screenshots, published test scenarios.
4. Announce it where app users actually look: the Home Assistant community
   forum and r/homeassistant.
5. Pro distributed through its own app repository with licensing.

**Not HACS.** The original plan had a "submit to HACS" step, which does not apply
here: HACS distributes custom integrations, dashboard plugins and themes — code
that runs *inside* Home Assistant. Mesh Sentinel is an app, a container that
runs *alongside* it, and apps are distributed only through app repositories
added in the Supervisor's own store. There is no HACS listing to
apply for.

Users add the repository under **Settings → Apps → App store → ⋮ →
Repositories**, which is a different dialog from HACS's "Custom repositories".
This also means the app requires Home Assistant OS or Supervised; it cannot
run on Home Assistant Container or Core installs.
