"""API contract: the three screens must be renderable from these payloads alone."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import Network
from mesh_sentinel.api import create_app


@pytest.fixture
def client(service, settings):
    app = create_app(settings, service, run_service=False)
    with TestClient(app) as test_client:
        yield test_client


def test_overview_is_enough_for_the_first_screen(client, small_network: Network):
    small_network.availability("Czujnik salon", "offline")
    small_network.advance(400)
    small_network.evaluate()

    body = client.get("/api/overview").json()
    assert body["health"]["score"] < 100
    assert body["health"]["status"] in ("healthy", "degraded", "critical")
    assert body["health"]["reasons"], "a score with no reasons is a magic number"
    network = body["networks"][0]
    assert network["label"] == "Zigbee2MQTT"
    assert network["total"] == 5 and network["offline"] == 1
    assert len(body["active_incidents"]) == 1
    assert body["active_incidents"][0]["conclusion"]
    assert body["active_incidents"][0]["recommended_action"]
    assert body["attention"][0]["name"] == "Czujnik salon"


def test_incident_detail_carries_timeline_evidence_and_before_after(client, small_network: Network):
    net = small_network
    net.availability("IKEA salon", "offline")
    net.advance(60)
    net.availability("Czujnik salon", "offline")
    net.availability("Czujnik kuchnia", "offline")
    net.advance(400)
    net.evaluate()

    incident_id = client.get("/api/incidents").json()["incidents"][0]["id"]
    body = client.get(f"/api/incidents/{incident_id}").json()

    assert body["incident"]["kind"] == "router_failure"
    assert body["incident"]["cause_device_name"] == "IKEA salon"
    assert body["incident"]["unknowns"]
    assert [e["description"] for e in body["evidence"]]
    assert body["timeline"], "the timeline is the product; it must never be empty"
    assert body["roles"][net.device_id("0xR1")] == "cause"
    assert "before" in body["before_after"] and "after" in body["before_after"]


def test_device_cockpit_payload(client, small_network: Network):
    net = small_network
    device_id = net.device_id("0xS1")
    body = client.get(f"/api/devices/{device_id}").json()

    assert body["device"]["name"] == "Czujnik salon"
    assert body["device"]["power_source"] == "battery"
    assert body["thresholds"]["stale_after_seconds"] == 24 * 3600
    assert "events" in body and "incidents" in body

    assert client.post(f"/api/devices/{device_id}/critical", json={"is_critical": True}).json()[
        "is_critical"
    ] is True
    assert client.get(f"/api/devices/{device_id}").json()["device"]["is_critical"] is True

    history = client.get(f"/api/devices/{device_id}/history?hours=24").json()
    assert "linkquality" in history and "availability" in history


def test_unknown_ids_return_404(client):
    assert client.get("/api/devices/z2m:0xdead").status_code == 404
    assert client.get("/api/incidents/999").status_code == 404


def test_evaluate_endpoint_reports_what_changed(client, small_network: Network):
    small_network.availability("Czujnik salon", "offline")
    small_network.advance(400)
    body = client.post("/api/evaluate").json()
    assert len(body["created"]) == 1
    assert body["created"][0]["kind"] == "device_offline"


def test_actions_are_honest_when_mqtt_is_down(client, small_network: Network):
    body = client.post("/api/actions/coordinator-check").json()
    assert body["requested"] is False
    assert "not connected" in body["detail"].lower()


def test_health_endpoint_exposes_source_status(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["sources"]["zigbee2mqtt"]["connected"] is False
    assert body["sources"]["zha"]["enabled"] is False
    assert body["retention_days"] == 7
