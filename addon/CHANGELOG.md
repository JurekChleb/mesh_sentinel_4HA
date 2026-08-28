# Changelog

## 0.1.1

Fixes found by running the fault-injection scenarios against a live broker.

- **A Zigbee2MQTT restart that already recovered no longer claims later
  failures.** It used to absorb devices that dropped minutes afterwards, filing a
  genuine outage as "restart, no action needed" — a false negative hiding a real
  problem. Once every device is back, that restart episode is closed.
- **One root cause now produces one incident even when detection is staggered.**
  A router is confirmed offline before the devices behind it are, so a
  single-device incident legitimately opens first. It is now closed as
  *Superseded by #N* when the router failure becomes visible, instead of sitting
  next to it and contradicting it.
- **A device that drops entirely supersedes its own degradation incident.**
- Added `scripts/simulate.py`, which injects real Zigbee2MQTT failure sequences
  on a separate MQTT topic so every rule can be tested without unplugging
  anything. See `docs/testing.md`.
- Port 8099 can now be opened in the app's Network settings to reach the API
  directly. It stays closed by default; Ingress needs none of it.
- Fixed the image build (`ARG BUILD_FROM` scope, a `COPY` path outside the build
  context) and moved to the current `3.13-alpine3.22` base image.
- The app no longer vanishes from the store: `image: null` in the manifest failed
  the Supervisor's validation, which skips the app silently.

## 0.1.0

First release. Zigbee2MQTT only.

- Continuous collection of device and network health signals into local SQLite.
- Deterministic correlation: six rules in priority order, so one root cause
  produces one incident with a conclusion, its evidence, what could not be
  determined, and a recommended action.
- Three screens: overview, incidents with timeline and before/after, and a
  device cockpit.
- Diagnoses and warns only. No resets, no re-pairing, no channel changes.
