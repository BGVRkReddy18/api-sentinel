"""A deliberately unreliable API to demo Sentinel.

Mounted inside the main app at /demo (SENTINEL_ENABLE_DEMO_TARGET=true) or run standalone:
    uvicorn demo.flaky_api:app --port 9000

Flip its behaviour live (from the dashboard's Settings page, or with curl):
    POST /demo/chaos/down      /orders starts returning 503 -> DOWN alert
    POST /demo/chaos/slow      /orders gets ~13x slower    -> latency anomaly + degraded
    POST /demo/chaos/healthy   back to normal              -> RECOVERED alert
"""

import asyncio
import random
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException

ChaosMode = Literal["healthy", "down", "slow"]
state: dict[str, str] = {"mode": "healthy"}

public_router = APIRouter(tags=["demo"])
chaos_router = APIRouter(tags=["demo"])


@public_router.get("/ok")
async def ok() -> dict:
    return {"status": "ok"}


@public_router.get("/slow")
async def slow() -> dict:
    """Normally ~120 ms, with an occasional 1.5 s spike."""
    delay = 1.5 if random.random() < 0.05 else max(0.02, random.gauss(0.12, 0.02))
    await asyncio.sleep(delay)
    return {"status": "ok", "delay_s": round(delay, 3)}


@public_router.get("/flaky")
async def flaky() -> dict:
    """Fails ~20% of the time with a 503."""
    if random.random() < 0.2:
        raise HTTPException(status_code=503, detail="temporarily unavailable")
    return {"status": "ok"}


@public_router.get("/orders")
async def orders() -> dict:
    mode = state["mode"]
    if mode == "down":
        raise HTTPException(status_code=503, detail="orders service unavailable")
    delay = random.gauss(0.8, 0.05) if mode == "slow" else max(0.01, random.gauss(0.06, 0.01))
    await asyncio.sleep(delay)
    return {"status": "ok", "orders": [{"id": 1, "total": 42.0}]}


@public_router.get("/chaos")
async def get_mode() -> dict:
    return {"mode": state["mode"]}


@chaos_router.post("/chaos/{mode}")
async def set_mode(mode: ChaosMode) -> dict:
    state["mode"] = mode
    return {"mode": mode}


app = FastAPI(title="Sentinel demo target")
app.include_router(public_router)
app.include_router(chaos_router)
