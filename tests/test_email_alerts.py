"""Per-endpoint email alerts delivered through the Brevo HTTPS API (network mocked)."""

import json

import httpx
import pytest
from pydantic import SecretStr

from app.services.notifier import BrevoSender

TARGET = "https://api.example.com/health"
BREVO = BrevoSender.URL


@pytest.fixture
def settings(settings):
    settings.email_provider = "brevo"
    settings.brevo_api_key = SecretStr("xkeysib-test")
    settings.email_from = "alerts@sentinel.dev"
    return settings


def brevo_calls(transport) -> list[dict]:
    return [json.loads(r.content) for r in transport.requests_to(BREVO)]


async def create(client, payload) -> dict:
    response = await client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_down_and_recovery_emails_go_to_endpoint_contacts(client, transport, endpoint_payload):
    transport.script(BREVO, httpx.Response(201, json={"messageId": "<1@brevo>"}))
    eid = (await create(client, {**endpoint_payload, "alert_emails": ["Ravi@Example.com"]}))["id"]

    transport.script(TARGET, httpx.Response(503))
    await client.post(f"/api/v1/endpoints/{eid}/check")
    assert brevo_calls(transport) == []  # one failure: no alert yet
    await client.post(f"/api/v1/endpoints/{eid}/check")

    calls = brevo_calls(transport)
    assert len(calls) == 1
    assert calls[0]["to"] == [{"email": "ravi@example.com"}]
    assert calls[0]["sender"]["email"] == "alerts@sentinel.dev"
    assert calls[0]["subject"] == "🔴 DOWN: payments"
    assert "got 503" in calls[0]["htmlContent"]
    assert transport.requests_to(BREVO)[0].headers["api-key"] == "xkeysib-test"

    alert = (await client.get("/api/v1/alerts")).json()["items"][0]
    assert alert["notified"] is True

    transport.script(TARGET, httpx.Response(200))
    await client.post(f"/api/v1/endpoints/{eid}/check")
    calls = brevo_calls(transport)
    assert len(calls) == 2
    assert calls[1]["subject"].startswith("🟢 RECOVERED")


async def test_global_alert_address_is_added(app, client, transport, endpoint_payload):
    app.state.email_notifier._always_to = ["ops@team.dev"]
    transport.script(BREVO, httpx.Response(201))
    eid = (await create(client, {**endpoint_payload, "alert_emails": ["ravi@example.com"]}))["id"]
    response = await client.post(f"/api/v1/endpoints/{eid}/test-alert")
    assert response.status_code == 200
    assert response.json()["sent_to"] == ["ravi@example.com", "ops@team.dev"]


async def test_send_test_alert(client, transport, endpoint_payload):
    transport.script(BREVO, httpx.Response(201))
    eid = (await create(client, {**endpoint_payload, "alert_emails": ["ravi@example.com"]}))["id"]
    response = await client.post(f"/api/v1/endpoints/{eid}/test-alert")
    assert response.status_code == 200
    call = brevo_calls(transport)[0]
    assert call["subject"].startswith("[TEST]")
    assert "your email alerts are working" in call["htmlContent"]


async def test_test_alert_requires_contacts(client, endpoint_payload):
    eid = (await create(client, endpoint_payload))["id"]
    response = await client.post(f"/api/v1/endpoints/{eid}/test-alert")
    assert response.status_code == 400
    assert "no alert emails" in response.json()["detail"]


async def test_provider_failure_is_reported(client, transport, endpoint_payload):
    transport.script(BREVO, httpx.Response(401, json={"message": "Key not found"}))
    eid = (await create(client, {**endpoint_payload, "alert_emails": ["ravi@example.com"]}))["id"]

    assert (await client.post(f"/api/v1/endpoints/{eid}/test-alert")).status_code == 502

    transport.script(TARGET, httpx.Response(500))
    await client.post(f"/api/v1/endpoints/{eid}/check")
    await client.post(f"/api/v1/endpoints/{eid}/check")
    alert = (await client.get("/api/v1/alerts")).json()["items"][0]
    assert alert["kind"] == "down"
    assert alert["notified"] is False  # recorded, but delivery failure is visible


async def test_alert_emails_are_validated_and_normalised(client, endpoint_payload):
    bad = await client.post("/api/v1/endpoints", json={**endpoint_payload, "alert_emails": ["not-an-email"]})
    assert bad.status_code == 422

    created = await create(
        client, {**endpoint_payload, "alert_emails": [" A@B.com ", "a@b.com", "c@d.io"]}
    )
    assert created["alert_emails"] == ["a@b.com", "c@d.io"]

    updated = await client.patch(f"/api/v1/endpoints/{created['id']}", json={"alert_emails": []})
    assert updated.json()["alert_emails"] == []


async def test_meta_reports_email(client):
    meta = (await client.get("/api/v1/meta")).json()
    assert meta["email_enabled"] is True
    assert meta["email_provider"] == "brevo"
