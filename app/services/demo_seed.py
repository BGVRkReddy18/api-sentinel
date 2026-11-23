"""Demo endpoints created automatically on first boot (SENTINEL_SEED_DEMO=true).

They point at the built-in demo API (/demo/*) on this deployment's public URL, plus two real
public APIs, so a fresh deployment has live data - and traffic - from the first minute.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import utcnow
from app.domain import EndpointStatus
from app.models import Endpoint

logger = logging.getLogger(__name__)


def demo_endpoints(base_url: str) -> list[dict]:
    base = base_url.rstrip("/")
    return [
        {"name": "demo-healthy", "url": f"{base}/demo/ok", "interval_seconds": 30, "timeout_seconds": 5},
        {
            "name": "demo-latency-spikes",
            "url": f"{base}/demo/slow",
            "interval_seconds": 30,
            "timeout_seconds": 5,
            "max_retries": 1,
            "max_latency_ms": 1000,
        },
        {
            "name": "demo-flaky",
            "url": f"{base}/demo/flaky",
            "interval_seconds": 30,
            "timeout_seconds": 5,
            "max_retries": 2,
        },
        {
            "name": "demo-orders",
            "url": f"{base}/demo/orders",
            "interval_seconds": 20,
            "timeout_seconds": 4,
            "max_retries": 1,
            "expected_body_contains": "orders",
            "max_latency_ms": 500,
        },
        {
            "name": "github-status",
            "url": "https://www.githubstatus.com/api/v2/status.json",
            "interval_seconds": 60,
            "timeout_seconds": 10,
            "expected_body_contains": "indicator",
        },
        {
            "name": "jsonplaceholder",
            "url": "https://jsonplaceholder.typicode.com/todos/1",
            "interval_seconds": 60,
            "timeout_seconds": 10,
            "expected_body_contains": "userId",
        },
        *PUBLIC_APIS,
    ]


# Real public APIs (no key needed). Avoid APIs with per-IP rate limits (GitHub, CoinGecko,
# Open-Meteo): cloud hosts share outbound IPs, so those limits are exhausted by other tenants.
PUBLIC_APIS: list[dict] = [
    {
        "name": "jsonplaceholder-create-post",
        "url": "https://jsonplaceholder.typicode.com/posts",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": '{"title": "sentinel", "body": "synthetic check", "userId": 1}',
        "expected_status": 201,
        "expected_body_contains": '"id"',
        "interval_seconds": 120,
    },
    {
        "name": "hacker-news-api",
        "url": "https://hacker-news.firebaseio.com/v0/maxitem.json",
        "interval_seconds": 120,
    },
    {
        "name": "chuck-norris-jokes",
        "url": "https://api.chucknorris.io/jokes/random",
        "expected_body_contains": "value",
        "interval_seconds": 120,
    },
    {
        "name": "zippopotam-postal",
        "url": "https://api.zippopotam.us/in/500001",
        "expected_body_contains": "places",
        "max_latency_ms": 1500,
        "interval_seconds": 180,
    },
    {
        "name": "wikipedia-rest",
        "url": "https://en.wikipedia.org/api/rest_v1/page/summary/Python_(programming_language)",
        "expected_body_contains": "extract",
        "max_latency_ms": 1500,
        "interval_seconds": 300,
    },
    {
        "name": "ipify",
        "url": "https://api.ipify.org?format=json",
        "expected_body_contains": '"ip"',
        "interval_seconds": 300,
    },
    {
        "name": "pokeapi",
        "url": "https://pokeapi.co/api/v2/pokemon/pikachu",
        "expected_body_contains": "pikachu",
        "interval_seconds": 300,
    },
    {
        "name": "dog-ceo-images",
        "url": "https://dog.ceo/api/breeds/image/random",
        "expected_body_contains": "success",
        "interval_seconds": 120,
    },
    {
        "name": "cat-facts",
        "url": "https://catfact.ninja/fact",
        "expected_body_contains": "fact",
        "interval_seconds": 120,
    },
    {
        "name": "httpbin",
        "url": "https://httpbin.org/get",
        "expected_body_contains": "headers",
        "interval_seconds": 180,
    },
]


async def seed_demo_endpoints(sessionmaker: async_sessionmaker[AsyncSession], base_url: str) -> int:
    """Create demo endpoints only when the database has none. Returns how many were created."""
    async with sessionmaker() as session:
        if await session.scalar(select(func.count(Endpoint.id))):
            return 0
        for spec in demo_endpoints(base_url):
            defaults = {
                "method": "GET",
                "headers": {},
                "expected_status": 200,
                "timeout_seconds": 10,
                "max_retries": 2,
                "retry_backoff_seconds": 0.5,
            }
            session.add(
                Endpoint(
                    **{**defaults, **spec},
                    is_active=True,
                    is_public=True,
                    current_status=EndpointStatus.UNKNOWN,
                    consecutive_failures=0,
                    next_check_at=utcnow(),
                )
            )
        await session.commit()
    logger.info("seeded demo endpoints", extra={"extra_fields": {"base_url": base_url}})
    return len(demo_endpoints(base_url))
