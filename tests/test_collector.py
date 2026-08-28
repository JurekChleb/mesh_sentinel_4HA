"""Zigbee2MQTT payload parsing - the layer where a wrong assumption is silent."""

from __future__ import annotations

from conftest import Network, device_entry, router_entry
from mesh_sentinel.collectors.z2m import _parse_last_seen
from mesh_sentinel.models import (
    EVT_BRIDGE_RESTART,
    EVT_COORDINATOR_MISSING,
    EVT_DEVICE_LEFT,
    EVT_DEVICE_TIMEOUT,
)


def test_devices_message_populates_the_inventory(net: Network):
    net.announce_devices([router_entry("0xR1", "IKEA salon"), device_entry("0xS1", "Czujnik")])

    router = net.service.repo.get_device(net.device_id("0xR1"))
    sensor = net.service.repo.get_device(net.device_id("0xS1"))
    assert router.device_type == "router" and router.power_source == "mains"
    assert sensor.device_type == "end_device" and sensor.power_source == "battery"
    assert sensor.vendor == "IKEA" and sensor.model == "E1525"
    assert sensor.last_seen is None, "an inventory entry is not proof of life"


def test_retained_state_does_not_fake_a_last_seen(net: Network):
    net.announce_devices([device_entry("0xS1", "Czujnik")])
    net.advance(10_000)

    # Zigbee2MQTT replays the last state on connect. Receipt time means nothing.
    net.publish("Czujnik", {"linkquality": 60, "battery": 80}, retained=True)
    assert net.service.repo.get_device(net.device_id("0xS1")).last_seen in (None, 0.0)

    # A live message does count.
    net.publish("Czujnik", {"linkquality": 60})
    assert net.service.repo.get_device(net.device_id("0xS1")).last_seen == net.clock.now()


def test_retained_state_uses_its_own_last_seen_field(net: Network):
    net.announce_devices([device_entry("0xS1", "Czujnik")])
    net.advance(9_000)  # so "now" and the reported timestamp cannot be confused
    net.publish(
        "Czujnik",
        {"linkquality": 60, "last_seen": "2023-11-14T22:13:20+00:00"},
        retained=True,
    )
    device = net.service.repo.get_device(net.device_id("0xS1"))
    assert device.last_seen == 1_700_000_000.0


def test_last_seen_accepts_the_three_zigbee2mqtt_formats():
    assert _parse_last_seen(1_700_000_000_000) == 1_700_000_000.0  # epoch millis
    assert _parse_last_seen(1_700_000_000) == 1_700_000_000.0  # epoch seconds
    assert _parse_last_seen("2023-11-14T22:13:20Z") == 1_700_000_000.0  # ISO 8601
    assert _parse_last_seen("not a date") is None
    assert _parse_last_seen(None) is None


def test_nested_friendly_names_are_handled(net: Network):
    net.announce_devices([device_entry("0xS1", "kuchnia/czujnik")])
    net.publish("kuchnia/czujnik", {"linkquality": 44})
    assert net.service.repo.get_device(net.device_id("0xS1")).linkquality == 44


def test_set_and_get_topics_are_ignored(net: Network):
    net.announce_devices([device_entry("0xS1", "Czujnik")])
    assert net.publish("Czujnik/set", {"state": "ON"}) == []
    assert net.publish("Czujnik/get", {"state": ""}) == []
    assert net.service.repo.get_device(net.device_id("0xS1")).last_seen is None


def test_bridge_offline_then_online_is_a_restart(net: Network):
    net.bridge_state("online")
    net.bridge_state("offline")
    events = net.bridge_state("online") or []
    types = [e.event_type for e in net.service.repo.recent_events(limit=10)]
    assert EVT_BRIDGE_RESTART in types


def test_coordinator_failure_is_told_apart_from_device_noise(net: Network):
    net.announce_devices([device_entry("0xS1", "Czujnik")])
    net.log("error", "Failed to connect to the adapter (/dev/ttyUSB0)")
    net.log("error", "Publish 'set' 'state' to 'Czujnik' failed: Error: timed out after 10000ms")

    types = [e.event_type for e in net.service.repo.recent_events(limit=10)]
    assert EVT_COORDINATOR_MISSING in types
    assert EVT_DEVICE_TIMEOUT in types
    timeout = [e for e in net.service.repo.recent_events(limit=10) if e.event_type == EVT_DEVICE_TIMEOUT][0]
    assert timeout.device_id == net.device_id("0xS1")


def test_device_leave_marks_it_offline(net: Network):
    net.announce_devices([device_entry("0xS1", "Czujnik")])
    net.availability("Czujnik", "online")
    net.publish("bridge/event", {"type": "device_leave", "data": {"friendly_name": "Czujnik"}})

    device = net.service.repo.get_device(net.device_id("0xS1"))
    assert device.availability == "offline"
    types = [e.event_type for e in net.service.repo.recent_events(limit=5)]
    assert EVT_DEVICE_LEFT in types


def test_networkmap_records_topology_and_parents(net: Network):
    net.announce_devices([router_entry("0xR1", "Router"), device_entry("0xS1", "Czujnik")])
    net.networkmap(
        nodes=[
            {"ieeeAddr": "0xR1", "friendlyName": "Router", "type": "Router"},
            {"ieeeAddr": "0xS1", "friendlyName": "Czujnik", "type": "EndDevice"},
        ],
        links=[
            {"source": {"ieeeAddr": "0xS1"}, "target": {"ieeeAddr": "0xR1"}, "linkquality": 30},
            {"source": {"ieeeAddr": "0xS1"}, "target": {"ieeeAddr": "0xR1"}, "linkquality": 90},
        ],
    )
    assert net.service.repo.get_device(net.device_id("0xS1")).parent_id == net.device_id("0xR1")
    snapshot = net.service.repo.topology_at(net.clock.now(), "z2m")
    assert snapshot["kind"] == "active" and snapshot["device_count"] == 2


def test_unknown_device_messages_are_dropped_until_the_inventory_arrives(net: Network):
    assert net.publish("Ghost", {"linkquality": 10}) == []
    assert net.service.repo.list_devices() == []


def test_availability_change_is_only_reported_once(net: Network):
    net.announce_devices([device_entry("0xS1", "Czujnik")])
    first = net.availability("Czujnik", "offline")
    net.advance(5)
    second = net.availability("Czujnik", "offline")
    assert len(net.service.repo.recent_events(limit=10, device_id=net.device_id("0xS1"))) == 1


def test_retained_availability_does_not_count_as_proof_of_life(net: Network):
    net.announce_devices([device_entry("0xS1", "Czujnik")])
    net.advance(5_000)
    net.publish("Czujnik/availability", {"state": "online"}, retained=True)

    device = net.service.repo.get_device(net.device_id("0xS1"))
    assert device.availability == "online", "the retained state still tells us what Z2M believes"
    assert device.last_seen in (None, 0.0), "but it is not a fresh report"


def test_a_device_timeout_does_not_look_like_a_dead_coordinator(net: Network):
    net.announce_devices([device_entry("0xS1", "Czujnik")])
    net.log("error", "Zigbee2MQTT:error SRSP - ZDO - nodeDescReq after 10000ms")

    types = [e.event_type for e in net.service.repo.recent_events(limit=10)]
    assert EVT_COORDINATOR_MISSING not in types


def test_a_broker_that_is_slow_to_start_is_not_an_incident(net: Network):
    from mesh_sentinel.models import EVT_MQTT_DISCONNECTED

    collector = net.service.z2m
    collector._first_attempt_at = net.clock.now()

    collector._mark_connected(False, "connection refused")
    net.advance(60)
    collector._mark_connected(False, "connection refused")
    types = [e.event_type for e in net.service.repo.recent_events(limit=10)]
    assert EVT_MQTT_DISCONNECTED not in types, "a broker still booting is not a fault"

    # Past the grace window it is a real problem and must be recorded.
    net.advance(200)
    collector._mark_connected(False, "connection refused")
    types = [e.event_type for e in net.service.repo.recent_events(limit=10)]
    assert EVT_MQTT_DISCONNECTED in types
    assert collector.connected is False
