"""The ten MVP scenarios from the product definition.

Each test states the real-world event, drives it through the collector, and
asserts on the single conclusion a human is supposed to read. If a scenario
produces two incidents where a person would say "that is one problem", the test
fails - that is the whole point of the correlation layer.
"""

from __future__ import annotations

from conftest import Network, device_entry, router_entry


def _only(incidents, kind: str):
    matching = [i for i in incidents if i.kind == kind]
    assert matching, f"expected a {kind} incident, got {[i.kind for i in incidents]}"
    assert len(matching) == 1, f"expected exactly one {kind} incident, got {len(matching)}"
    return matching[0]


# --- 1. A single battery sensor stops reporting ------------------------------
def test_single_battery_sensor_goes_quiet(small_network: Network):
    net = small_network

    # It reports nothing for a day while everything else keeps talking.
    for _ in range(25):
        net.advance(3600)
        for name in ("IKEA salon", "Czujnik kuchnia", "Czujnik sypialnia", "Czujnik lazienka"):
            net.report(name, linkquality=88, battery=90)

    net.evaluate()  # marks it offline; too fresh to be an incident yet
    assert net.open_incidents() == []

    net.advance(200)
    net.evaluate()

    incident = _only(net.open_incidents(), "device_offline")
    assert incident.severity == "warning"
    assert incident.cause_device_id == net.device_id("0xS1")
    assert incident.affected_device_ids == [net.device_id("0xS1")]
    assert "battery" in incident.recommended_action.lower()
    assert incident.unknowns, "a single-device verdict must state what it cannot know"


def test_critical_device_raises_severity(small_network: Network):
    net = small_network
    net.service.repo.set_critical(net.device_id("0xS1"), True)

    net.availability("Czujnik salon", "offline")
    net.advance(400)
    net.evaluate()

    incident = _only(net.open_incidents(), "device_offline")
    assert incident.severity == "critical"


# --- 2. A router disappears and takes its branch with it ---------------------
def test_router_failure_groups_its_branch(small_network: Network):
    net = small_network

    net.availability("IKEA salon", "offline")
    net.advance(120)
    for name in ("Czujnik salon", "Czujnik kuchnia", "Czujnik sypialnia"):
        net.availability(name, "offline")
    net.advance(400)
    net.evaluate()

    incidents = net.open_incidents()
    incident = _only(incidents, "router_failure")
    assert len(incidents) == 1, "a router failure must not also raise per-device incidents"
    assert incident.cause_device_id == net.device_id("0xR1")
    roles = net.service.repo.incident_device_roles(incident.id)
    assert roles[net.device_id("0xR1")] == "cause"
    assert sorted(d for d, r in roles.items() if r == "affected") == [
        net.device_id("0xS1"),
        net.device_id("0xS2"),
        net.device_id("0xS3"),
    ]
    assert incident.severity == "error"
    # No routing table was scanned, so the verdict must admit the link is inferred.
    assert incident.confidence < 0.7
    assert any("routing table" in u.lower() for u in incident.unknowns)

    evidence = net.service.repo.evidence_for(incident.id)
    kinds = {e.kind for e in evidence}
    assert "router_missing" in kinds and "device_offline" in kinds
    assert "Home Assistant" in incident.conclusion  # says what it is NOT


def test_router_failure_is_more_confident_with_a_network_map(small_network: Network):
    net = small_network
    net.networkmap(
        nodes=[
            {"ieeeAddr": "0xR1", "friendlyName": "IKEA salon", "type": "Router"},
            {"ieeeAddr": "0xS1", "friendlyName": "Czujnik salon", "type": "EndDevice"},
            {"ieeeAddr": "0xS2", "friendlyName": "Czujnik kuchnia", "type": "EndDevice"},
        ],
        links=[
            {"source": {"ieeeAddr": "0xS1"}, "target": {"ieeeAddr": "0xR1"}, "linkquality": 80},
            {"source": {"ieeeAddr": "0xS2"}, "target": {"ieeeAddr": "0xR1"}, "linkquality": 75},
        ],
    )
    assert net.service.repo.get_device(net.device_id("0xS1")).parent_id == net.device_id("0xR1")

    net.availability("IKEA salon", "offline")
    net.availability("Czujnik salon", "offline")
    net.availability("Czujnik kuchnia", "offline")
    net.advance(400)
    net.evaluate()

    incident = _only(net.open_incidents(), "router_failure")
    assert incident.confidence >= 0.8
    assert not any("routing table" in u.lower() for u in incident.unknowns)


# --- 3. Zigbee2MQTT restarts and comes back ----------------------------------
def test_z2m_restart_is_a_warning_not_an_outage(small_network: Network):
    net = small_network

    net.bridge_state("offline")
    net.advance(10)
    for name in ("Czujnik salon", "Czujnik kuchnia", "Czujnik sypialnia", "Czujnik lazienka"):
        net.availability(name, "offline")
    net.advance(20)
    net.bridge_state("online")  # back up -> this transition is the restart

    net.advance(400)
    net.evaluate()

    incident = _only(net.open_incidents(), "service_restart")
    assert incident.severity == "warning", "a clean restart must not read as a critical outage"
    assert incident.confidence >= 0.7
    assert len(incident.affected_device_ids) == 4

    # Devices come back and stay back.
    for name in ("Czujnik salon", "Czujnik kuchnia", "Czujnik sypialnia", "Czujnik lazienka"):
        net.availability(name, "online")
    net.advance(200)
    result = net.evaluate()

    assert [i.kind for i in result.resolved] == ["service_restart"]
    assert net.open_incidents() == []
    evidence = net.service.repo.evidence_for(incident.id)
    assert any(e.kind == "recovery" for e in evidence)


# --- 4. The USB coordinator does not come back after a host restart ----------
def test_missing_coordinator_blames_the_host_not_the_mesh(small_network: Network):
    net = small_network

    net.log("error", "Error: Failed to connect to the adapter (/dev/ttyUSB0)")
    net.advance(10)
    for name in ("IKEA salon", "Czujnik salon", "Czujnik kuchnia", "Czujnik sypialnia"):
        net.availability(name, "offline")
    net.advance(400)
    net.evaluate()

    incidents = net.open_incidents()
    assert len(incidents) == 1, "one host problem is one incident"
    incident = _only(incidents, "coordinator_unavailable")
    assert incident.severity == "critical"
    assert "USB" in incident.recommended_action
    assert "not a failure of the mesh" in incident.conclusion

    # And it clears once the adapter answers again.
    net.health_check(healthy=True)
    for name in ("IKEA salon", "Czujnik salon", "Czujnik kuchnia", "Czujnik sypialnia"):
        net.availability(name, "online")
    net.advance(200)
    result = net.evaluate()
    assert [i.kind for i in result.resolved] == ["coordinator_unavailable"]


def test_broker_loss_is_reported_as_our_blind_spot(small_network: Network):
    net = small_network
    repo = net.service.repo
    from mesh_sentinel.models import EVT_MQTT_DISCONNECTED, Event

    repo.add_event(
        Event(
            ts=net.clock.now(),
            source="mesh_sentinel",
            event_type=EVT_MQTT_DISCONNECTED,
            severity="error",
            network_id="z2m",
        )
    )
    net.availability("Czujnik salon", "offline")
    net.advance(400)
    net.evaluate()

    incident = _only(net.open_incidents(), "data_source_unavailable")
    assert "says nothing about the Zigbee network" in incident.conclusion
    assert incident.severity == "error"


# --- 5. One device with a rising error rate, healthy mesh --------------------
def test_rising_timeouts_on_one_device_stay_local(small_network: Network):
    net = small_network

    for _ in range(6):
        net.advance(60)
        net.log("error", "Publish 'set' 'state' to 'Czujnik kuchnia' failed: Error: timed out after 10000ms")

    net.advance(60)
    net.evaluate()

    incident = _only(net.open_incidents(), "device_degraded")
    assert incident.cause_device_id == net.device_id("0xS2")
    assert incident.severity == "warning"
    assert "error_rate" in incident.conclusion
    assert net.service.repo.get_device(net.device_id("0xS2")).availability != "offline"


def test_degradation_is_not_raised_while_the_mesh_is_unhealthy(small_network: Network):
    net = small_network
    for name in ("IKEA salon", "Czujnik salon", "Czujnik sypialnia", "Czujnik lazienka"):
        net.availability(name, "offline")
    for _ in range(6):
        net.advance(60)
        net.log("error", "Publish 'set' 'state' to 'Czujnik kuchnia' failed: Error: timed out after 10000ms")
    net.advance(400)
    net.evaluate()

    assert not [i for i in net.open_incidents() if i.kind == "device_degraded"]


# --- 6. A short blip must not page anybody -----------------------------------
def test_short_offline_does_not_create_an_incident(small_network: Network):
    net = small_network

    net.availability("Czujnik salon", "offline")
    net.advance(90)  # under the 180s grace
    net.evaluate()
    assert net.open_incidents() == []

    net.availability("Czujnik salon", "online")
    net.advance(90)
    net.evaluate()
    assert net.incidents() == [], "a 90 second blip must leave no trace as an incident"


def test_mass_outage_when_no_single_cause_explains_it(small_network: Network):
    net = small_network
    # Four end devices drop; the router keeps reporting, so no router hypothesis.
    for name in ("Czujnik salon", "Czujnik kuchnia", "Czujnik sypialnia", "Czujnik lazienka"):
        net.availability(name, "offline")
    net.advance(400)
    net.report("IKEA salon", linkquality=90)
    net.evaluate()

    incident = _only(net.open_incidents(), "mass_outage")
    assert len(incident.affected_device_ids) == 4
    assert incident.confidence <= 0.5, "a guess must look like a guess"
    assert incident.unknowns


def test_one_incident_is_updated_not_duplicated(small_network: Network):
    net = small_network
    net.availability("Czujnik salon", "offline")
    net.advance(400)
    net.evaluate()
    net.advance(60)
    net.evaluate()
    net.advance(60)
    result = net.evaluate()

    assert len(net.open_incidents()) == 1
    assert len(result.created) == 0 and len(result.updated) == 1
    evidence = net.service.repo.evidence_for(net.open_incidents()[0].id)
    offline_lines = [e for e in evidence if e.kind == "device_offline"]
    assert len(offline_lines) == 1, "repeated passes must not stack identical evidence"


def test_mass_outage_is_one_incident_even_as_it_grows(small_network: Network):
    net = small_network
    for name in ("Czujnik salon", "Czujnik kuchnia", "Czujnik sypialnia"):
        net.availability(name, "offline")
    net.advance(400)
    net.report("IKEA salon", linkquality=90)
    net.evaluate()
    first = _only(net.open_incidents(), "mass_outage")

    # A fourth device joins the outage later; the cluster start moves.
    net.advance(300)
    net.availability("Czujnik lazienka", "offline")
    net.advance(400)
    net.report("IKEA salon", linkquality=90)
    net.evaluate()

    incidents = net.open_incidents()
    assert len(incidents) == 1, "a growing outage must stay one incident"
    assert incidents[0].id == first.id
    assert len(incidents[0].affected_device_ids) == 4


def test_a_degrading_device_that_drops_gets_one_incident(small_network: Network):
    net = small_network
    for _ in range(6):
        net.advance(60)
        net.log("error", "Publish 'set' 'state' to 'Czujnik kuchnia' failed: Error: timed out after 10000ms")
    net.advance(60)
    net.evaluate()
    assert len(net.open_incidents()) == 1

    degraded = _only(net.open_incidents(), "device_degraded")

    # It then drops entirely. "It is unavailable" is the better explanation, so
    # the degradation incident is superseded rather than left open alongside it.
    net.availability("Czujnik kuchnia", "offline")
    net.advance(400)
    result = net.evaluate()

    assert [i.id for i in result.superseded] == [degraded.id]
    offline = _only(net.open_incidents(), "device_offline")
    assert len(net.open_incidents()) == 1
    assert net.service.repo.get_incident(degraded.id).superseded_by == offline.id
    assert any(
        e.kind == "superseded" for e in net.service.repo.evidence_for(degraded.id)
    ), "a superseded incident must say what replaced it"


def test_a_router_incident_absorbs_the_single_device_one_detected_first(small_network: Network):
    """Real detection is staggered: the router is confirmed offline before its
    children are, so a single-device incident opens first. The router failure
    must absorb it, not sit next to it."""

    net = small_network
    net.availability("IKEA salon", "offline")
    net.advance(200)  # past the grace window for the router only
    first = net.evaluate()

    assert [i.kind for i in first.created] == ["device_offline"]
    early = first.created[0]

    # Its children are confirmed offline a couple of minutes later.
    net.availability("Czujnik salon", "offline")
    net.availability("Czujnik kuchnia", "offline")
    net.availability("Czujnik sypialnia", "offline")
    net.advance(200)
    result = net.evaluate()

    incidents = net.open_incidents()
    assert len(incidents) == 1, "one router failure is one incident"
    router = _only(incidents, "router_failure")
    assert [i.id for i in result.superseded] == [early.id]
    assert net.service.repo.get_incident(early.id).superseded_by == router.id
