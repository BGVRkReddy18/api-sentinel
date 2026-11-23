from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import Limit, Offset, SessionDep, WriteAuth, paginate
from app.core.clock import utcnow
from app.domain import AlertKind
from app.models import Alert
from app.schemas import AlertRead, Page

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=Page[AlertRead])
async def list_alerts(
    session: SessionDep,
    endpoint_id: int | None = None,
    kind: AlertKind | None = None,
    unresolved: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> dict:
    stmt = select(Alert).order_by(Alert.created_at.desc(), Alert.id.desc())
    if endpoint_id is not None:
        stmt = stmt.where(Alert.endpoint_id == endpoint_id)
    if kind is not None:
        stmt = stmt.where(Alert.kind == kind)
    if unresolved:
        stmt = stmt.where(Alert.resolved_at.is_(None), Alert.kind != AlertKind.RECOVERED)
    items, total = await paginate(session, stmt, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/{alert_id}/resolve", response_model=AlertRead, dependencies=[WriteAuth])
async def resolve_alert(alert_id: int, session: SessionDep) -> Alert:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="alert not found")
    if alert.resolved_at is None:
        alert.resolved_at = utcnow()
        await session.commit()
        await session.refresh(alert)
    return alert
