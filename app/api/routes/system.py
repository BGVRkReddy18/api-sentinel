from fastapi import APIRouter, Request

from app import __version__
from app.api.deps import SessionDep, SettingsDep, WriteAuth
from app.schemas import StatusPage
from app.services.status_page import build_status_page

router = APIRouter(tags=["system"])


@router.get("/meta")
async def meta(request: Request, settings: SettingsDep) -> dict:
    """What the frontend needs to know about this deployment."""
    return {
        "app_name": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
        "auth_required": settings.api_key is not None,
        "demo_enabled": settings.enable_demo_target,
        "public_base_url": settings.public_base_url,
        "live_clients": request.app.state.events.subscriber_count,
        "email_enabled": request.app.state.email_notifier is not None,
        "email_provider": settings.email_provider,
    }


@router.get("/auth/verify", dependencies=[WriteAuth])
async def verify_key() -> dict:
    """Returns 200 if the X-API-Key header is valid (used by the UI's admin login)."""
    return {"ok": True}


@router.get("/status", response_model=StatusPage)
async def status_page(session: SessionDep):
    """Public status page data: 90-day daily uptime per public service + recent incidents."""
    return await build_status_page(session)
