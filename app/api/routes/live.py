"""Real-time event stream over WebSocket.

Clients connect to /ws and receive JSON events as they happen:
    {"type": "check" | "status_changed" | "alert" | "endpoint" | "hello" | "ping", "ts": ..., "data": {...}}
"""

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import __version__

router = APIRouter(tags=["live"])
HEARTBEAT_SECONDS = 25  # keeps proxies (Render, nginx) from closing idle connections


@router.websocket("/ws")
async def live_events(websocket: WebSocket) -> None:
    await websocket.accept()
    bus = websocket.app.state.events
    queue = bus.subscribe()

    async def sender() -> None:
        await websocket.send_json({"type": "hello", "data": {"version": __version__}})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                event = {"type": "ping", "data": {}}
            await websocket.send_json(event)

    async def receiver() -> None:
        while True:  # we only read to detect disconnects (and ignore client pings)
            await websocket.receive_text()

    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError, Exception):
                await task
        bus.unsubscribe(queue)
