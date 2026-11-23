"""End-to-end monitoring pipeline: check -> state transition -> alert -> webhook -> recovery."""

import json
from datetime import timedelta

import httpx

from app.core.clock import utcnow
from app.services.checker import CheckOutcome, CheckSpec
from tests.conftest import WEBHOOK_URL

TARGET = "https://api.example.com/health"


async def create(client, payload) -> dict:
    response = await client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def check(client, endpoint_id) -> dict:
    response = await client.post(f"/api/v1/endpoints/{endpoint_id}/check")
    assert response.status_code == 200, response.text
    return response.json()


async def test_outage_alert_and_recovery(client, transport, endpoint_payload):
    endpoint = await create(client, endpoint_payload)
    eid = endpoint["id"]

    transport.script(TARGET, httpx.Response(200))
    assert (await check(client, eid))["is_success"]
    assert (await client.get(f"/api/v1/endpoints/{eid}")).json()["current_status"] == "up"

    # First failure: below the threshold of 2 -> still UP, no alert yet (anti-flapping).
    transport.script(TARGET, httpx.Response(500))
    first = await check(client, eid)
    assert not first["is_success"]
    assert first["error_type"] == "unexpected_status"
    state = (await client.get(f"/api/v1/endpoints/{eid}")).json()
    assert state["current_status"] == "up"
    assert state["consecutive_failures"] == 1
    assert (await client.get("/api/v1/alerts")).json()["total"] == 0

    # Second failure: DOWN + critical alert delivered to the webhook.
    await check(client, eid)
    assert (await client.get(f"/api/v1/endpoints/{eid}")).json()["current_status"] == "down"
    alerts = (await client.get("/api/v1/alerts", params={"unresolved": "true"})).json()["items"]
    assert [a["kind"] for a in alerts] == ["down"]
    assert alerts[0]["severity"] == "critical"
    assert alerts[0]["notified"] is True
    webhook_calls = transport.requests_to(WEBHOOK_URL)
    assert len(webhook_calls) == 1
    assert "DOWN" in json.loads(webhook_calls[0].content)["text"]

    # Further failures do not spam alerts.
    await check(client, eid)
    assert len(transport.requests_to(WEBHOOK_URL)) == 1

    # Recovery resolves the open DOWN alert and emits RECOVERED.
    transport.script(TARGET, httpx.Response(200))
    await check(client, eid)
    state = (await client.get(f"/api/v1/endpoints/{eid}")).json()
    assert state["current_status"] == "up"
    assert state["consecutive_failures"] == 0
    kinds = [a["kind"] for a in (await client.get("/api/v1/alerts")).json()["items"]]
    assert sorted(kinds) == ["down", "recovered"]
    assert (await client.get("/api/v1/alerts", params={"unresolved": "true"})).json()["total"] == 0

    # The outage shows up as exactly one incident of 3 failed checks.
    incidents = (await client.get(f"/api/v1/analytics/endpoints/{eid}/incidents")).json()
    assert len(incidents) == 1
    assert incidents[0]["failed_checks"] == 3
    assert incidents[0]["ongoing"] is False

    errors = (await client.get(f"/api/v1/analytics/endpoints/{eid}/errors")).json()
    assert errors == [{"error_type": "unexpected_status", "count": 3, "last_seen": errors[0]["last_seen"]}]


async def test_results_history_and_filters(client, transport, endpoint_payload):
    eid = (await create(client, endpoint_payload))["id"]
    transport.script(TARGET, httpx.Response(200), httpx.Response(503), httpx.Response(200))
    for _ in range(3):
        await check(client, eid)

    all_results = (await client.get(f"/api/v1/endpoints/{eid}/results")).json()
    assert all_results["total"] == 3
    failed = (await client.get(f"/api/v1/endpoints/{eid}/results", params={"success": "false"})).json()
    assert failed["total"] == 1
    assert failed["items"][0]["status_code"] == 503


async def test_latency_anomaly_raises_one_alert_within_cooldown(app, client, endpoint_payload):
    eid = (await create(client, endpoint_payload))["id"]
    monitor = app.state.monitor
    spec = CheckSpec(endpoint_id=eid, name="payments", url=TARGET)
    base = utcnow() - timedelta(minutes=30)

    def outcome(minutes: int, latency: float) -> CheckOutcome:
        return CheckOutcome(
            checked_at=base + timedelta(minutes=minutes),
            is_success=True,
            status_code=200,
            response_time_ms=latency,
        )

    for i in range(15):  # stable ~100 ms baseline
        await monitor.record(spec, outcome(i, 100 + (i % 3)))

    spike = await monitor.record(spec, outcome(16, 900))
    assert spike.is_anomaly
    assert spike.anomaly_score > 3.5

    await monitor.record(spec, outcome(17, 950))  # still anomalous, but inside cooldown

    alerts = (await client.get("/api/v1/alerts", params={"kind": "latency_anomaly"})).json()
    assert alerts["total"] == 1
    assert alerts["items"][0]["severity"] == "warning"
    anomalies = (
        await client.get(f"/api/v1/endpoints/{eid}/results", params={"anomalies_only": "true"})
    ).json()
    assert anomalies["total"] == 2


async def test_scheduler_claims_only_due_active_endpoints(app, client, transport, endpoint_payload):
    due = (await create(client, endpoint_payload))["id"]
    await create(client, {**endpoint_payload, "name": "paused", "is_active": False})
    transport.script(TARGET, httpx.Response(200))

    scheduler = app.state.scheduler
    assert await scheduler.run_once() == 1
    await scheduler.drain()

    state = (await client.get(f"/api/v1/endpoints/{due}")).json()
    assert state["current_status"] == "up"
    assert state["last_checked_at"] is not None

    # Leased: next_check_at moved forward by the interval, so the next tick claims nothing.
    assert await scheduler.run_once() == 0


async def test_retention_purges_old_results(app, client, endpoint_payload):
    eid = (await create(client, endpoint_payload))["id"]
    monitor = app.state.monitor
    spec = CheckSpec(endpoint_id=eid, name="payments", url=TARGET)
    old = CheckOutcome(
        checked_at=utcnow() - timedelta(days=45), is_success=True, status_code=200, response_time_ms=50
    )
    new = CheckOutcome(checked_at=utcnow(), is_success=True, status_code=200, response_time_ms=50)
    await monitor.record(spec, old)
    await monitor.record(spec, new)

    assert await monitor.purge_old_results() == 1
    results = (await client.get(f"/api/v1/endpoints/{eid}/results", params={"hours": 24 * 90})).json()
    assert results["total"] == 1


async def test_deleting_endpoint_cascades(client, transport, endpoint_payload):
    eid = (await create(client, endpoint_payload))["id"]
    transport.script(TARGET, httpx.Response(500))
    await check(client, eid)
    await check(client, eid)  # -> DOWN alert
    assert (await client.delete(f"/api/v1/endpoints/{eid}")).status_code == 204
    assert (await client.get("/api/v1/alerts")).json()["total"] == 0


async def test_anomaly_alert_auto_resolves_when_latency_normalises(app, client, endpoint_payload):
    eid = (await create(client, endpoint_payload))["id"]
    monitor = app.state.monitor
    spec = CheckSpec(endpoint_id=eid, name="payments", url=TARGET)
    base = utcnow() - timedelta(minutes=30)

    def outcome(minutes: int, latency: float) -> CheckOutcome:
        return CheckOutcome(
            checked_at=base + timedelta(minutes=minutes), is_success=True, status_code=200, response_time_ms=latency
        )

    for i in range(15):
        await monitor.record(spec, outcome(i, 100 + (i % 3)))
    await monitor.record(spec, outcome(16, 900))
    assert (await client.get("/api/v1/alerts", params={"unresolved": "true"})).json()["total"] == 1

    await monitor.record(spec, outcome(17, 102))  # back to normal
    assert (await client.get("/api/v1/alerts", params={"unresolved": "true"})).json()["total"] == 0
    alert = (await client.get("/api/v1/alerts")).json()["items"][0]
    assert alert["kind"] == "latency_anomaly"
    assert alert["resolved_at"] is not None
