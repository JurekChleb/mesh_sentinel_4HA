#!/usr/bin/env python3
"""Fault injector for Mesh Sentinel.

Publishes the exact Zigbee2MQTT messages a real failure would produce, so every
detection rule can be exercised on a live install without unplugging anything -
including the failures that are awkward to stage for real, like losing the
coordinator or a whole branch of the mesh at once.

It publishes to a SEPARATE base topic (default: meshsentinel_test), so it never
touches your real Zigbee network. Point Mesh Sentinel at that topic for the
duration of the test:

    App options -> z2m_base_topic: meshsentinel_test   (restart the app)
    ... run the scenarios ...
    App options -> z2m_base_topic: zigbee2mqtt         (restart the app)

While the test topic is active, your real network is not being watched. That is
the trade for testing against the real, installed app rather than a mock.

Usage:
    pip install paho-mqtt
    python simulate.py --host 192.168.1.10 all
    python simulate.py --host 192.168.1.10 --username u --password p router
    python simulate.py --host 192.168.1.10 --api http://192.168.1.10:8099 all

With --api the script checks the result itself and prints PASS/FAIL. That needs
the optional port opened in the app's Network settings; without it, the script
tells you what to look for in the UI instead.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - user-facing guidance
    sys.exit("paho-mqtt is missing. Install it with:  pip install paho-mqtt")

REAL_TOPICS = {"zigbee2mqtt", "zigbee2mqtt2", "z2m"}

ROUTER = ("0x00124b0022aa01", "Test router salon")
SENSORS = [
    ("0x00158d0001bb02", "Test czujnik salon"),
    ("0x00158d0001bb03", "Test czujnik kuchnia"),
    ("0x00158d0001bb04", "Test czujnik sypialnia"),
    ("0x00158d0001bb05", "Test czujnik lazienka"),
]


def device_id(ieee: str) -> str:
    return f"z2m:{ieee.lower()}"


@dataclass
class Expectation:
    """What the run should produce, so the script can check it rather than you."""

    kind: str | None
    severity: str | None = None
    min_devices: int = 0
    cause_ieee: str | None = None
    expect_none: bool = False
    notes: list[str] = field(default_factory=list)


class Injector:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.base = args.topic.strip("/")
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id="mesh-sentinel-simulator"
        )
        if args.username:
            self.client.username_pw_set(args.username, args.password or None)

    # -- transport -----------------------------------------------------------
    def connect(self) -> None:
        self.client.connect(self.args.host, self.args.port, keepalive=30)
        self.client.loop_start()
        self.say(f"connected to {self.args.host}:{self.args.port}, base topic '{self.base}'")

    def disconnect(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, topic: str, payload, retain: bool = False) -> None:
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        self.client.publish(f"{self.base}/{topic}", payload, qos=1, retain=retain).wait_for_publish()

    def say(self, message: str) -> None:
        print(f"  {time.strftime('%H:%M:%S')}  {message}", flush=True)

    def wait(self, seconds: float, why: str) -> None:
        self.say(f"waiting {round(seconds)}s - {why}")
        time.sleep(seconds)

    # -- building blocks -----------------------------------------------------
    def seed(self) -> None:
        """Announce a small fake network and bring every device online."""

        self.say("announcing the test network (1 router + 4 battery sensors)")
        self.publish("bridge/state", {"state": "online"}, retain=True)
        devices = [
            {
                "ieee_address": ROUTER[0],
                "friendly_name": ROUTER[1],
                "type": "Router",
                "power_source": "Mains (single phase)",
                "supported": True,
                "definition": {"vendor": "IKEA", "model": "LED1836G9"},
            }
        ] + [
            {
                "ieee_address": ieee,
                "friendly_name": name,
                "type": "EndDevice",
                "power_source": "Battery",
                "supported": True,
                "definition": {"vendor": "Aqara", "model": "WSDCGQ11LM"},
            }
            for ieee, name in SENSORS
        ]
        self.publish("bridge/devices", devices, retain=True)
        time.sleep(1)
        for _, name in [ROUTER] + SENSORS:
            self.online(name)
        self.say("all devices online and reporting")

    def online(self, name: str, linkquality: int = 92, battery: int = 88) -> None:
        self.publish(f"{name}/availability", {"state": "online"})
        self.publish(name, {"linkquality": linkquality, "battery": battery})

    def offline(self, name: str) -> None:
        self.publish(f"{name}/availability", {"state": "offline"})
        self.say(f"{name} -> offline")

    def log(self, level: str, message: str) -> None:
        self.publish("bridge/logging", {"level": level, "message": message})

    def bridge(self, state: str) -> None:
        self.publish("bridge/state", {"state": state}, retain=True)
        self.say(f"Zigbee2MQTT bridge -> {state}")

    def settle(self) -> float:
        """Long enough for the grace window plus one detection pass."""

        return self.args.grace + 30

    # -- scenarios -----------------------------------------------------------
    def scenario_single(self) -> Expectation:
        """A single battery sensor stops reporting while the mesh is fine."""

        ieee, name = SENSORS[0]
        self.offline(name)
        self.wait(self.settle(), "the grace window must pass before this is an incident")
        return Expectation(
            kind="device_offline",
            severity="warning",
            min_devices=1,
            cause_ieee=ieee,
            notes=["The advice should mention the battery, since this is a battery device."],
        )

    def scenario_router(self) -> Expectation:
        """A router dies and the devices behind it follow a minute later."""

        self.offline(ROUTER[1])
        self.wait(self.settle(), "the router alone is confirmed offline first")
        for _, name in SENSORS[:3]:
            self.offline(name)
        self.wait(self.settle(), "its children are confirmed offline next")
        return Expectation(
            kind="router_failure",
            severity="error",
            min_devices=3,
            cause_ieee=ROUTER[0],
            notes=[
                "The single-device incident raised first must show as Superseded, not Active.",
                "Confidence is ~55% without a network map; that is honest, not a bug.",
            ],
        )

    def scenario_restart(self) -> Expectation:
        """Zigbee2MQTT restarts; devices blink out and come back."""

        self.bridge("offline")
        time.sleep(2)
        for _, name in SENSORS:
            self.offline(name)
        time.sleep(3)
        self.bridge("online")
        self.wait(self.settle(), "the devices stay away past the grace window")
        return Expectation(
            kind="service_restart",
            severity="warning",
            min_devices=2,
            notes=["Severity must be warning. A clean restart is not a critical outage."],
        )

    def scenario_coordinator(self) -> Expectation:
        """The USB adapter is gone - a host problem, not a mesh failure."""

        self.log("error", "Error: Failed to connect to the adapter (/dev/ttyUSB0)")
        self.say("bridge logged an adapter failure")
        time.sleep(2)
        for _, name in [ROUTER] + SENSORS:
            self.offline(name)
        self.wait(self.settle(), "every device is confirmed offline")
        return Expectation(
            kind="coordinator_unavailable",
            severity="critical",
            notes=[
                "This must be ONE incident, not one per device.",
                "The advice must point at the host and USB, not at the Zigbee network.",
            ],
        )

    def scenario_mass(self) -> Expectation:
        """Several devices drop with no single cause to blame."""

        for _, name in SENSORS:
            self.offline(name)
        self.wait(self.settle(), "the drops are confirmed")
        self.online(ROUTER[1])  # the router keeps reporting, so it is not the cause
        self.say(f"{ROUTER[1]} keeps reporting - no router hypothesis is available")
        return Expectation(
            kind="mass_outage",
            severity="error",
            min_devices=3,
            notes=["Confidence should be low (~50%). A guess must look like a guess."],
        )

    def scenario_degraded(self) -> Expectation:
        """One device times out repeatedly while the rest of the mesh is healthy."""

        _, name = SENSORS[1]
        for index in range(6):
            self.log(
                "error",
                f"Publish 'set' 'state' to '{name}' failed: Error: timed out after 10000ms",
            )
            self.say(f"timeout {index + 1}/6 for {name}")
            time.sleep(2)
        self.wait(40, "one detection pass")
        return Expectation(
            kind="device_degraded",
            severity="warning",
            cause_ieee=SENSORS[1][0],
            notes=["The device stays online; this is degradation, not an outage."],
        )

    def scenario_blip(self) -> Expectation:
        """The one that must produce nothing at all."""

        _, name = SENSORS[0]
        self.offline(name)
        # Comfortably inside the grace window whatever it is set to. A gap that
        # exceeds it is a real outage, and the app is right to report one.
        gap = max(3.0, self.args.grace * 0.4)
        self.wait(gap, f"staying offline for less than the {self.args.grace}s grace window")
        self.online(name)
        self.say(f"{name} -> online again")
        self.wait(60, "a detection pass runs and finds nothing to report")
        return Expectation(
            kind=None,
            expect_none=True,
            notes=["Any new incident here is a false alarm and a bug."],
        )

    def scenario_recover(self) -> Expectation:
        """Bring everything back and let the open incidents close themselves."""

        self.bridge("online")
        self.publish(
            "bridge/response/health_check", {"status": "ok", "data": {"healthy": True}}
        )
        for _, name in [ROUTER] + SENSORS:
            self.online(name)
        self.say("everything is reporting again")
        self.wait(
            self.args.recovery + 40,
            "recovery has to hold before an incident is closed",
        )
        return Expectation(kind=None, expect_none=True, notes=["Health should be back at 100."])

    # -- verification --------------------------------------------------------
    def incidents(self) -> list[dict] | None:
        if not self.args.api:
            return None
        url = f"{self.args.api.rstrip('/')}/api/incidents?limit=50"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return json.loads(response.read())["incidents"]
        except (urllib.error.URLError, OSError, ValueError, KeyError) as err:
            print(f"  could not read the API at {url}: {err}")
            return None

    def check(self, expectation: Expectation, before: list[dict] | None) -> bool | None:
        after = self.incidents()
        if after is None or before is None:
            print("\n  What to look for in the UI:")
            if expectation.expect_none:
                print("    - NO new incident")
            else:
                print(f"    - one new '{expectation.kind}' incident", end="")
                print(f", severity {expectation.severity}" if expectation.severity else "")
            for note in expectation.notes:
                print(f"    - {note}")
            return None

        known = {incident["id"] for incident in before}
        fresh = [incident for incident in after if incident["id"] not in known]

        if expectation.expect_none:
            if fresh:
                self.fail(f"expected no new incident, got {[i['title'] for i in fresh]}")
                return False
            self.ok("no incident raised, as intended")
            return True

        matching = [incident for incident in fresh if incident["kind"] == expectation.kind]
        if not matching:
            self.fail(
                f"expected a '{expectation.kind}' incident, got "
                f"{[i['kind'] for i in fresh] or 'nothing'}"
            )
            return False

        incident = matching[0]
        problems = []
        if expectation.severity and incident["severity"] != expectation.severity:
            problems.append(f"severity {incident['severity']}, expected {expectation.severity}")
        if incident["device_count"] < expectation.min_devices:
            problems.append(
                f"{incident['device_count']} devices, expected at least {expectation.min_devices}"
            )
        if expectation.cause_ieee and incident["cause_device_id"] != device_id(
            expectation.cause_ieee
        ):
            problems.append(f"cause is {incident['cause_device_id']}")
        for field_name in ("conclusion", "recommended_action"):
            if not incident.get(field_name):
                problems.append(f"{field_name} is empty")
        if not incident.get("unknowns"):
            problems.append("no unknowns listed")

        if problems:
            self.fail(f"{incident['title']}: " + "; ".join(problems))
            return False

        self.ok(f"{incident['title']} ({incident['severity']}, "
                f"{round(incident['confidence'] * 100)}% confidence, "
                f"{incident['device_count']} devices)")
        superseded = [i for i in fresh if i.get("superseded_by")]
        for item in superseded:
            print(f"       superseded: {item['title']} -> #{item['superseded_by']}")
        for note in expectation.notes:
            print(f"       note: {note}")
        return True

    @staticmethod
    def ok(message: str) -> None:
        print(f"  PASS  {message}")

    @staticmethod
    def fail(message: str) -> None:
        print(f"  FAIL  {message}")


SCENARIOS = {
    "single": ("A single battery sensor stops reporting", "scenario_single"),
    "router": ("A router dies and takes its branch with it", "scenario_router"),
    "restart": ("Zigbee2MQTT restarts and comes back", "scenario_restart"),
    "coordinator": ("The USB coordinator disappears", "scenario_coordinator"),
    "mass": ("Several devices drop with no identifiable cause", "scenario_mass"),
    "degraded": ("One device times out repeatedly, mesh healthy", "scenario_degraded"),
    "blip": ("A short outage that must NOT raise an incident", "scenario_blip"),
    "recover": ("Everything comes back and incidents close", "scenario_recover"),
}
ORDER = ["blip", "single", "recover", "router", "recover", "restart", "recover",
         "coordinator", "recover", "mass", "recover", "degraded", "recover"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inject Zigbee2MQTT failures so Mesh Sentinel can be tested end to end.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Scenarios:\n"
        + "\n".join(f"  {key:<12} {text}" for key, (text, _) in SCENARIOS.items())
        + "\n  all          every scenario in order, with recovery in between",
    )
    parser.add_argument("scenario", choices=[*SCENARIOS, "all", "seed"])
    parser.add_argument("--host", required=True, help="MQTT broker address")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument(
        "--topic",
        default="meshsentinel_test",
        help="base topic to publish to (default: meshsentinel_test)",
    )
    parser.add_argument(
        "--api",
        help="Mesh Sentinel API base URL, e.g. http://192.168.1.10:8099, to check results",
    )
    parser.add_argument(
        "--grace",
        type=int,
        default=180,
        help="the app's offline_grace_seconds, so waits match it (default: 180)",
    )
    parser.add_argument(
        "--recovery",
        type=int,
        default=120,
        help="the app's recovery_confirm_seconds (default: 120)",
    )
    parser.add_argument(
        "--no-seed", action="store_true", help="skip announcing the test network first"
    )
    parser.add_argument(
        "--yes-really-use-a-real-topic",
        action="store_true",
        help="allow publishing to a real Zigbee2MQTT topic (do not)",
    )
    args = parser.parse_args()

    if args.topic.strip("/") in REAL_TOPICS and not args.yes_really_use_a_real_topic:
        return fail_real_topic(args.topic)

    injector = Injector(args)
    injector.connect()
    failures = 0
    try:
        if not args.no_seed:
            injector.seed()
            injector.wait(20, "the app builds its inventory")

        if args.scenario == "seed":
            print("\nTest network is up. Run a scenario next.")
            return 0

        steps = ORDER if args.scenario == "all" else [args.scenario]
        for step in steps:
            title, method = SCENARIOS[step]
            print(f"\n=== {step}: {title} ===", flush=True)
            before = injector.incidents()
            expectation = getattr(injector, method)()
            result = injector.check(expectation, before)
            if result is False:
                failures += 1
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130
    finally:
        injector.disconnect()

    print("\n" + "-" * 68)
    if args.api:
        print(f"finished with {failures} failure(s)")
    else:
        print("finished; check the results in the Mesh Sentinel UI")
    print("Remember to set z2m_base_topic back to zigbee2mqtt and restart the app.")
    return 1 if failures else 0


def fail_real_topic(topic: str) -> int:
    print(
        f"Refusing to publish to '{topic}': that is a real Zigbee2MQTT base topic.\n"
        "Fake availability messages there would leave retained state on your actual\n"
        "devices and confuse Home Assistant's MQTT entities.\n\n"
        "Use a separate topic instead and point the app at it for the test:\n"
        "  python simulate.py --host <broker> --topic meshsentinel_test all",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
