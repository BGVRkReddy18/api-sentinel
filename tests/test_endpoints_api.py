from pydantic import SecretStr


async def test_create_and_get_endpoint(client, endpoint_payload):
    response = await client.post("/api/v1/endpoints", json=endpoint_payload)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["name"] == "payments"
    assert created["current_status"] == "unknown"
    assert created["method"] == "GET"
    assert response.headers["x-request-id"]

    fetched = await client.get(f"/api/v1/endpoints/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["url"] == endpoint_payload["url"]


async def test_duplicate_name_conflict(client, endpoint_payload):
    assert (await client.post("/api/v1/endpoints", json=endpoint_payload)).status_code == 201
    assert (await client.post("/api/v1/endpoints", json=endpoint_payload)).status_code == 409


async def test_validation_rejects_bad_input(client, endpoint_payload):
    bad_url = {**endpoint_payload, "url": "not-a-url"}
    assert (await client.post("/api/v1/endpoints", json=bad_url)).status_code == 422

    bad_method = {**endpoint_payload, "method": "BREW"}
    assert (await client.post("/api/v1/endpoints", json=bad_method)).status_code == 422


async def test_retry_budget_must_fit_interval(client, endpoint_payload):
    # 3 attempts * 10s timeout = 30s >= 15s interval -> rejected
    payload = {**endpoint_payload, "interval_seconds": 15, "timeout_seconds": 10, "max_retries": 2}
    response = await client.post("/api/v1/endpoints", json=payload)
    assert response.status_code == 422
    assert "interval_seconds" in response.text


async def test_list_with_filters_and_pagination(client, endpoint_payload):
    for i in range(3):
        await client.post("/api/v1/endpoints", json={**endpoint_payload, "name": f"svc-{i}"})
    await client.post(
        "/api/v1/endpoints", json={**endpoint_payload, "name": "paused", "is_active": False}
    )

    page = (await client.get("/api/v1/endpoints", params={"limit": 2})).json()
    assert page["total"] == 4
    assert len(page["items"]) == 2

    active = (await client.get("/api/v1/endpoints", params={"is_active": "true"})).json()
    assert active["total"] == 3

    unknown = (await client.get("/api/v1/endpoints", params={"status": "unknown"})).json()
    assert unknown["total"] == 4


async def test_patch_revalidates_merged_config(client, endpoint_payload):
    created = (await client.post("/api/v1/endpoints", json=endpoint_payload)).json()
    url = f"/api/v1/endpoints/{created['id']}"

    ok = await client.patch(url, json={"interval_seconds": 120, "max_latency_ms": 800})
    assert ok.status_code == 200
    assert ok.json()["interval_seconds"] == 120
    assert ok.json()["max_latency_ms"] == 800

    # 30s timeout * 3 attempts = 90s worst case, which fits in the 120s interval -> allowed.
    assert (await client.patch(url, json={"timeout_seconds": 30, "max_retries": 2})).status_code == 200
    # ...but shrinking the interval below the retry budget is rejected.
    assert (await client.patch(url, json={"interval_seconds": 60})).status_code == 422


async def test_delete_endpoint(client, endpoint_payload):
    created = (await client.post("/api/v1/endpoints", json=endpoint_payload)).json()
    url = f"/api/v1/endpoints/{created['id']}"
    assert (await client.delete(url)).status_code == 204
    assert (await client.get(url)).status_code == 404


async def test_unknown_endpoint_404(client):
    assert (await client.get("/api/v1/endpoints/999")).status_code == 404
    assert (await client.post("/api/v1/endpoints/999/check")).status_code == 404


async def test_api_key_protects_writes(app, client, endpoint_payload):
    app.state.settings.api_key = SecretStr("s3cret")
    try:
        assert (await client.post("/api/v1/endpoints", json=endpoint_payload)).status_code == 401
        wrong = await client.post(
            "/api/v1/endpoints", json=endpoint_payload, headers={"X-API-Key": "nope"}
        )
        assert wrong.status_code == 401
        ok = await client.post(
            "/api/v1/endpoints", json=endpoint_payload, headers={"X-API-Key": "s3cret"}
        )
        assert ok.status_code == 201
        # Reads stay public
        assert (await client.get("/api/v1/endpoints")).status_code == 200
    finally:
        app.state.settings.api_key = None


async def test_health_and_metrics(client):
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    ready = (await client.get("/health/ready")).json()
    assert ready["database"] == "up"
    metrics = await client.get("/metrics")
    assert metrics.status_code == 200
    assert "sentinel_checks_total" in metrics.text
