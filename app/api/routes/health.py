from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import SessionDep

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request, session: SessionDep):
    """Readiness probe: the database is reachable."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "down"})
    scheduler = request.app.state.scheduler
    return {
        "status": "ok",
        "database": "up",
        "scheduler": "running" if scheduler.running else "stopped",
        "inflight_checks": scheduler.inflight,
    }
