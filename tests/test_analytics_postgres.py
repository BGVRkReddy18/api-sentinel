"""PostgreSQL-only analytics (percentile_cont, FILTER, date_trunc). Run with TEST_DATABASE_URL set."""

from datetime import timedelta

import pytest

from app.core.clock import utcnow
from app.services.checker import CheckOutcome, CheckSpec
from tests.conftest import postgres_enabled

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not postgres_enabled(), reason="requires TEST_DATABASE_URL=postgresql+asyncpg://..."),
]


async def seed(app, client, endpoint_payload) -> int:
    eid = (await client.post("/api/v1/endpoints", json=endpoint_payload)).json()["id"]
    spec = CheckSpec(endpoint_id=eid, name="payments", url="https://api.example.com/health")
    start = utcnow() - timedelta(hours=2)
    # 100 checks: latencies 1..100 ms, every 10th check fails -> 90% uptime.
    for i in range(1, 101):
        failed = i % 10 == 0
        await app.state.monitor.record(
            spec,
            CheckOutcome(
                checked_at=start + timedelta(minutes=i),
                is_success=not failed,
                status_code=500 if failed else 200,
                response_time_ms=float(i),
            ),
        )
    return eid


async def test_summary_uptime_and_percentiles(app, client, endpoint_payload):
    eid = await seed(app, client, endpoint_payload)
    rows = (await client.get("/api/v1/analytics/summary", params={"hours": 24})).json()
    row = next(r for r in rows if r["endpoint_id"] == eid)
    assert row["total_checks"] == 100
    assert row["failed_checks"] == 10
    assert row["uptime_pct"] == pytest.approx(90.0)
    # successful latencies are 1..99 excluding multiples of 10
    assert row["p50_latency_ms"] == pytest.approx(50.5, abs=1.0)
    assert row["p99_latency_ms"] > row["p95_latency_ms"] > row["p50_latency_ms"]


async def test_summary_includes_endpoints_without_checks(client, endpoint_payload):
    eid = (await client.post("/api/v1/endpoints", json=endpoint_payload)).json()["id"]
    rows = (await client.get("/api/v1/analytics/summary")).json()
    row = next(r for r in rows if r["endpoint_id"] == eid)
    assert row["total_checks"] == 0
    assert row["uptime_pct"] is None


async def test_timeseries_buckets(app, client, endpoint_payload):
    eid = await seed(app, client, endpoint_payload)
    points = (
        await client.get(
            f"/api/v1/analytics/endpoints/{eid}/timeseries", params={"hours": 24, "bucket": "hour"}
        )
    ).json()
    assert 2 <= len(points) <= 3
    assert sum(p["total_checks"] for p in points) == 100


async def test_incidents_gaps_and_islands(app, client, endpoint_payload):
    eid = await seed(app, client, endpoint_payload)
    incidents = (await client.get(f"/api/v1/analytics/endpoints/{eid}/incidents")).json()
    assert len(incidents) == 10  # each isolated failure is its own incident
    assert incidents[0]["ongoing"] is True  # the very last check (i=100) failed
    assert all(i["failed_checks"] == 1 for i in incidents)
