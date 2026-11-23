import secrets
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.config import Settings
from app.models import Endpoint
from app.services.events import EventBus
from app.services.monitor import MonitorService


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_monitor(request: Request) -> MonitorService:
    return request.app.state.monitor


def get_events(request: Request) -> EventBus:
    return request.app.state.events


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


async def require_api_key(
    request: Request, x_api_key: Annotated[str | None, Header()] = None
) -> None:
    expected = request.app.state.settings.api_key
    if expected is None:
        return
    # Constant-time comparison avoids leaking the key through response timing.
    if not secrets.compare_digest(x_api_key or "", expected.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


SessionDep = Annotated[AsyncSession, Depends(get_session)]
MonitorDep = Annotated[MonitorService, Depends(get_monitor)]
EventsDep = Annotated[EventBus, Depends(get_events)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
WriteAuth = Depends(require_api_key)

Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]
WindowHours = Annotated[int, Query(ge=1, le=24 * 90, description="Look-back window in hours")]


def since(hours: int) -> datetime:
    return utcnow() - timedelta(hours=hours)


async def get_endpoint_or_404(session: AsyncSession, endpoint_id: int) -> Endpoint:
    endpoint = await session.get(Endpoint, endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="endpoint not found")
    return endpoint


async def paginate(session: AsyncSession, stmt: Select, *, limit: int, offset: int) -> tuple[list, int]:
    total = await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    items = (await session.scalars(stmt.limit(limit).offset(offset))).all()
    return list(items), total or 0
