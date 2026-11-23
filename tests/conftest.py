"""Test fixtures.

By default tests run against a throwaway SQLite file (fast, zero setup). Set TEST_DATABASE_URL to
a PostgreSQL URL to run the full suite, including the PostgreSQL-only analytics tests (CI does).
"""

import os
from collections.abc import AsyncIterator

import httpx
import pytest

from app import models as _models  # noqa: F401  (register models on the metadata)
from app.core.config import Settings
from app.db.base import Base
from app.main import create_app

WEBHOOK_URL = "https://hooks.test/alerts"


class ScriptedTransport(httpx.MockTransport):
    """Fake network: each URL replays a script of responses/exceptions (last step repeats)."""

    def __init__(self) -> None:
        self.scripts: dict[str, list] = {}
        self.requests: list[httpx.Request] = []
        super().__init__(self._handle)

    def script(self, url: str, *steps: httpx.Response | Exception) -> None:
        self.scripts[url] = list(steps)

    def requests_to(self, url: str) -> list[httpx.Request]:
        return [r for r in self.requests if str(r.url) == url]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url == WEBHOOK_URL:
            return httpx.Response(200)
        steps = self.scripts.get(url)
        if not steps:
            return httpx.Response(404)
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        if isinstance(step, Exception):
            raise step
        return step


def postgres_enabled() -> bool:
    return os.getenv("TEST_DATABASE_URL", "").startswith("postgresql")


@pytest.fixture
def transport() -> ScriptedTransport:
    return ScriptedTransport()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=os.getenv("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"),
        scheduler_enabled=False,
        log_json=False,
        log_level="WARNING",
        alert_webhook_url=WEBHOOK_URL,
        alert_failure_threshold=2,
        alert_cooldown_seconds=900,
        anomaly_min_samples=10,
        max_concurrent_checks=10,
        ssl_checks_enabled=False,  # no real TLS handshakes in tests
        enable_demo_target=True,
    )


@pytest.fixture
async def app(settings, transport) -> AsyncIterator:
    application = create_app(settings, http_transport=transport)
    async with application.router.lifespan_context(application):
        async with application.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        yield application


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://sentinel.test"
    ) as c:
        yield c


@pytest.fixture
def endpoint_payload() -> dict:
    return {
        "name": "payments",
        "url": "https://api.example.com/health",
        "interval_seconds": 30,
        "timeout_seconds": 2,
        "max_retries": 0,
        "retry_backoff_seconds": 0,
    }
