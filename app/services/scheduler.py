"""Non-blocking scheduler loop with bounded concurrency (backpressure).

Each tick claims at most `free capacity` due endpoints and launches their checks as background
tasks, so one slow endpoint (timeouts + retries) never delays checks for the others.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from app.core.config import Settings
from app.core.logging import log_extra
from app.observability.metrics import SCHEDULER_CLAIMED_TOTAL, SCHEDULER_TICK_SECONDS
from app.services.checker import CheckSpec
from app.services.monitor import MonitorService

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, monitor: MonitorService, settings: Settings) -> None:
        self._monitor = monitor
        self._tick_seconds = settings.scheduler_tick_seconds
        self._capacity = settings.max_concurrent_checks
        self._retention_interval = settings.retention_interval_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._inflight: set[asyncio.Task] = set()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def inflight(self) -> int:
        return len(self._inflight)

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="sentinel-scheduler")
        logger.info("scheduler started", extra=log_extra(capacity=self._capacity))

    async def stop(self, grace_seconds: float = 10.0) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        await self.drain(grace_seconds)
        logger.info("scheduler stopped")

    async def drain(self, timeout: float | None = None) -> None:
        """Wait for in-flight checks; cancel whatever is still running after `timeout`."""
        if not self._inflight:
            return
        _, pending = await asyncio.wait(set(self._inflight), timeout=timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def run_once(self) -> int:
        free = self._capacity - len(self._inflight)
        if free <= 0:
            return 0
        started = time.perf_counter()
        specs = await self._monitor.claim_due_endpoints(limit=free)
        SCHEDULER_TICK_SECONDS.observe(time.perf_counter() - started)
        for spec in specs:
            task = asyncio.create_task(self._execute(spec), name=f"check-{spec.endpoint_id}")
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)
        if specs:
            SCHEDULER_CLAIMED_TOTAL.inc(len(specs))
        return len(specs)

    async def _execute(self, spec: CheckSpec) -> None:
        try:
            await self._monitor.execute(spec)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("check pipeline failed", extra=log_extra(endpoint_id=spec.endpoint_id))

    async def _run(self) -> None:
        last_purge = float("-inf")
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("scheduler tick failed")

            if time.monotonic() - last_purge >= self._retention_interval:
                last_purge = time.monotonic()
                try:
                    deleted = await self._monitor.purge_old_results()
                    if deleted:
                        logger.info("purged old check results", extra=log_extra(deleted=deleted))
                except Exception:
                    logger.exception("retention purge failed")

            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._tick_seconds)
