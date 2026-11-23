"""Real-time events, maintenance windows, TLS expiry alerts, SSRF guard, demo API and SPA routing."""

from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.clock import utcnow
from app.db.session import normalize_database_url
from app.main import create_app

TARGET = "https://api.example.com/health"


async def create(client, payload) -> dict:
    response = await client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def check(client, endpoint_id) -> dict:
    response = await client.post(f"/api/v1/endpoints/{endpoint_id}/check")
    assert response.status_code == 200, response.text
    return response.json()


def drain(queue) -> list[dict]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


# ---------------------------------------------------------------- live events


async def test_checks_publish_live_events(app, client, transport, endpoint_payload):
    queue = app.state.events.subscribe()
    eid = (await create(client, endpoint_payload))["id"]
    created = drain(queue)
    assert created[0]["type"] == "endpoint"
    assert created[0]["data"]["action"] == "created"

    transport.script(TARGET, httpx.Response(500))
    await check(client, eid)
    await check(client, eid)

    events = drain(queue)
    types = [e["type"] for e in events]
    assert types.count("check") == 2
    assert "status_changed" in types
    alert = next(e for e in events if e["type"] == "alert")
    assert alert["data"]["kind"] == "down"
    assert alert["data"]["endpoint_name"] == "payments"
    check_event = next(e for e in events if e["type"] == "check")
    assert check_event["data"]["result"]["status_code"] == 500
    app.state.events.unsubscribe(queue)


def test_websocket_handshake(settings):
    with TestClient(create_app(settings)) as test_client:
        with test_client.websocket_connect("/ws") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            assert "version" in hello["data"]


def test_event_bus_drops_oldest_for_slow_consumers():
    from app.services.events import EventBus

    bus = EventBus(queue_size=2)
    queue = bus.subscribe()
    for i in range(5):
        bus.publish("check", {"i": i})
    assert [queue.get_nowait()["data"]["i"] for _ in range(2)] == [3, 4]


# ---------------------------------------------------------------- maintenance


async def test_maintenance_mutes_alerts_until_it_ends(client, transport, endpoint_payload):
    eid = (await create(client, endpoint_payload))["id"]
    response = await client.post(
        f"/api/v1/endpoints/{eid}/maintenance", json={"minutes": 30, "reason": "db upgrade"}
    )
    assert response.status_code == 200
    assert response.json()["maintenance_reason"] == "db upgrade"

    transport.script(TARGET, httpx.Response(503))
    first = await check(client, eid)
    await check(client, eid)
    assert first["in_maintenance"] is True
    assert (await client.get(f"/api/v1/endpoints/{eid}")).json()["current_status"] == "down"
    assert (await client.get("/api/v1/alerts")).json()["total"] == 0  # muted

    # Maintenance over but still failing -> the DOWN alert fires on the next check.
    assert (await client.delete(f"/api/v1/endpoints/{eid}/maintenance")).status_code == 200
    await check(client, eid)
    alerts = (await client.get("/api/v1/alerts")).json()["items"]
    assert [a["kind"] for a in alerts] == ["down"]


async def test_maintenance_validation(client, endpoint_payload):
    eid = (await create(client, endpoint_payload))["id"]
    assert (await client.post(f"/api/v1/endpoints/{eid}/maintenance", json={"minutes": 1})).status_code == 422


# ---------------------------------------------------------------- TLS expiry


async def test_ssl_expiry_alert(app, client, transport, endpoint_payload):
    monitor = app.state.monitor
    app.state.settings.ssl_checks_enabled = True
    probed: list[tuple[str, int]] = []

    async def fake_probe(host: str, port: int):
        probed.append((host, port))
        return utcnow() + timedelta(days=5)

    monitor._ssl_probe = fake_probe
    try:
        eid = (await create(client, endpoint_payload))["id"]
        transport.script(TARGET, httpx.Response(200))
        await check(client, eid)
        await check(client, eid)  # within ssl_check_interval -> not probed again
    finally:
        app.state.settings.ssl_checks_enabled = False

    assert probed == [("api.example.com", 443)]
    endpoint = (await client.get(f"/api/v1/endpoints/{eid}")).json()
    assert endpoint["ssl_expires_at"] is not None
    alerts = (await client.get("/api/v1/alerts", params={"kind": "ssl_expiring"})).json()["items"]
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "warning"
    assert "expires in" in alerts[0]["message"]


async def test_ssl_probe_failure_is_recorded_not_fatal(app, client, transport, endpoint_payload):
    monitor = app.state.monitor
    app.state.settings.ssl_checks_enabled = True

    async def broken_probe(host: str, port: int):
        raise OSError("handshake failed")

    monitor._ssl_probe = broken_probe
    try:
        eid = (await create(client, endpoint_payload))["id"]
        transport.script(TARGET, httpx.Response(200))
        assert (await check(client, eid))["is_success"]
    finally:
        app.state.settings.ssl_checks_enabled = False
    assert "handshake failed" in (await client.get(f"/api/v1/endpoints/{eid}")).json()["ssl_error"]


# ---------------------------------------------------------------- security


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:5432/", "http://localhost:8000/", "http://169.254.169.254/latest/meta-data/"],
)
async def test_ssrf_guard_blocks_private_targets(app, client, endpoint_payload, url):
    app.state.settings.block_private_targets = True
    try:
        response = await client.post("/api/v1/endpoints", json={**endpoint_payload, "url": url})
    finally:
        app.state.settings.block_private_targets = False
    assert response.status_code == 422
    assert "unsafe target" in response.json()["detail"]


async def test_meta_and_auth_verify(app, client):
    meta = (await client.get("/api/v1/meta")).json()
    assert meta["auth_required"] is False
    assert meta["demo_enabled"] is True

    app.state.settings.api_key = SecretStr("k3y")
    try:
        assert (await client.get("/api/v1/meta")).json()["auth_required"] is True
        assert (await client.get("/api/v1/auth/verify")).status_code == 401
        ok = await client.get("/api/v1/auth/verify", headers={"X-API-Key": "k3y"})
        assert ok.status_code == 200
        # chaos controls are admin-only on a protected deployment
        assert (await client.post("/demo/chaos/down")).status_code == 401
    finally:
        app.state.settings.api_key = None


# ---------------------------------------------------------------- demo API, SPA, analytics


async def test_embedded_demo_api(client):
    assert (await client.get("/demo/ok")).json() == {"status": "ok"}
    assert (await client.post("/demo/chaos/down")).json() == {"mode": "down"}
    assert (await client.get("/demo/orders")).status_code == 503
    assert (await client.post("/demo/chaos/healthy")).json() == {"mode": "healthy"}
    assert (await client.get("/demo/orders")).status_code == 200


async def test_spa_fallback_does_not_swallow_api_routes(client):
    page = await client.get("/endpoints/42")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    missing = await client.get("/api/v1/does-not-exist")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/json")


async def test_recent_checks_for_sparklines(client, transport, endpoint_payload):
    eid = (await create(client, endpoint_payload))["id"]
    transport.script(TARGET, httpx.Response(200), httpx.Response(500), httpx.Response(200))
    for _ in range(3):
        await check(client, eid)
    recent = (await client.get("/api/v1/analytics/recent", params={"per_endpoint": 2})).json()
    assert recent[0]["endpoint_id"] == eid
    checks = recent[0]["checks"]
    assert len(checks) == 2  # only the latest 2, oldest first
    assert [c["is_success"] for c in checks] == [False, True]


# ---------------------------------------------------------------- hosted-Postgres URLs


@pytest.mark.parametrize(
    ("raw", "expected_url", "expected_ssl"),
    [
        (
            "postgres://u:p@db.example.com:5432/app?sslmode=require",
            "postgresql+asyncpg://u:p@db.example.com:5432/app",
            "require",
        ),
        (
            "postgresql://u:p@host/db?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@host/db",
            "require",
        ),
        ("postgresql+asyncpg://u:p@host/db", "postgresql+asyncpg://u:p@host/db", None),
        ("sqlite+aiosqlite:///./x.db", "sqlite+aiosqlite:///./x.db", None),
    ],
)
def test_normalize_database_url(raw, expected_url, expected_ssl):
    url, connect_args = normalize_database_url(raw)
    assert url == expected_url
    assert connect_args.get("ssl") == expected_ssl


async def test_test_alert_without_email_configured(client, endpoint_payload):
    eid = (await create(client, {**endpoint_payload, "alert_emails": ["a@b.com"]}))["id"]
    response = await client.post(f"/api/v1/endpoints/{eid}/test-alert")
    assert response.status_code == 400
    assert "not configured" in response.json()["detail"]
