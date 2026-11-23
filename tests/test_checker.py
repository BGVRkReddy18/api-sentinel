import asyncio
import random

import httpx
import pytest

from app.domain import ErrorType
from app.services.checker import CheckSpec, HealthChecker

URL = "https://svc.test/health"


class FakeSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def make_checker(handler, sleep=None) -> tuple[HealthChecker, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    checker = HealthChecker(client, sleep=sleep or FakeSleep(), rng=random.Random(42))
    return checker, client


def spec(**overrides) -> CheckSpec:
    defaults = dict(endpoint_id=1, name="svc", url=URL, max_retries=2, retry_backoff_seconds=0.5)
    return CheckSpec(**{**defaults, **overrides})


def sequence(*responses):
    """Handler returning responses in order (the last one repeats); counts calls."""
    calls = {"n": 0}

    def handler(request):
        index = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        item = responses[index]
        if isinstance(item, Exception):
            raise item
        return item

    return handler, calls


async def test_success():
    handler, calls = sequence(httpx.Response(200, text="ok"))
    checker, client = make_checker(handler)
    async with client:
        outcome = await checker.run(spec())
    assert outcome.is_success
    assert outcome.status_code == 200
    assert outcome.error_type is None
    assert outcome.attempts == 1
    assert outcome.response_time_ms is not None and outcome.response_time_ms >= 0
    assert calls["n"] == 1


async def test_retries_5xx_then_fails_with_exponential_backoff():
    sleep = FakeSleep()
    handler, calls = sequence(httpx.Response(503))
    checker, client = make_checker(handler, sleep)
    async with client:
        outcome = await checker.run(spec())
    assert not outcome.is_success
    assert outcome.error_type is ErrorType.UNEXPECTED_STATUS
    assert outcome.status_code == 503
    assert outcome.attempts == 3
    assert calls["n"] == 3
    assert len(sleep.delays) == 2
    assert 0.5 <= sleep.delays[0] <= 0.55  # base * 2^0 + <=10% jitter
    assert 1.0 <= sleep.delays[1] <= 1.1  # base * 2^1 + <=10% jitter


async def test_recovers_on_retry():
    handler, _ = sequence(httpx.Response(502), httpx.Response(200))
    checker, client = make_checker(handler)
    async with client:
        outcome = await checker.run(spec())
    assert outcome.is_success
    assert outcome.attempts == 2


async def test_4xx_is_not_retried():
    handler, calls = sequence(httpx.Response(404))
    checker, client = make_checker(handler)
    async with client:
        outcome = await checker.run(spec())
    assert outcome.error_type is ErrorType.UNEXPECTED_STATUS
    assert outcome.attempts == 1
    assert calls["n"] == 1


async def test_timeout_is_classified_and_retried():
    handler, calls = sequence(httpx.ReadTimeout("slow"))
    checker, client = make_checker(handler)
    async with client:
        outcome = await checker.run(spec(max_retries=1))
    assert outcome.error_type is ErrorType.TIMEOUT
    assert outcome.status_code is None
    assert calls["n"] == 2


async def test_connection_error():
    handler, _ = sequence(httpx.ConnectError("refused"))
    checker, client = make_checker(handler)
    async with client:
        outcome = await checker.run(spec(max_retries=0))
    assert outcome.error_type is ErrorType.CONNECTION
    assert "ConnectError" in outcome.error_message


async def test_body_assertion():
    handler, calls = sequence(httpx.Response(200, text='{"status": "degraded"}'))
    checker, client = make_checker(handler)
    async with client:
        outcome = await checker.run(spec(expected_body_contains='"status": "ok"'))
    assert not outcome.is_success
    assert outcome.error_type is ErrorType.BODY_MISMATCH
    assert calls["n"] == 1  # deterministic failure, no retry


async def test_custom_expected_status_and_method():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["body"] = request.content
        return httpx.Response(201)

    checker, client = make_checker(handler)
    async with client:
        outcome = await checker.run(spec(method="POST", body='{"ping": 1}', expected_status=201))
    assert outcome.is_success
    assert seen == {"method": "POST", "body": b'{"ping": 1}'}


async def test_latency_slo_breach_is_degraded_success():
    async def handler(request):
        await asyncio.sleep(0.05)
        return httpx.Response(200)

    checker, client = make_checker(handler)
    async with client:
        outcome = await checker.run(spec(max_latency_ms=10))
    assert outcome.is_success
    assert outcome.is_degraded
    assert outcome.error_type is ErrorType.SLOW


@pytest.mark.parametrize(
    ("status", "retry"), [(500, True), (503, True), (429, True), (400, False), (401, False)]
)
async def test_retry_policy_by_status(status, retry):
    handler, calls = sequence(httpx.Response(status))
    checker, client = make_checker(handler)
    async with client:
        await checker.run(spec(max_retries=1))
    assert calls["n"] == (2 if retry else 1)
