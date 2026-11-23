from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    EventsDep,
    Limit,
    MonitorDep,
    Offset,
    SessionDep,
    SettingsDep,
    WindowHours,
    WriteAuth,
    get_endpoint_or_404,
    paginate,
    since,
)
from app.core.clock import utcnow
from app.core.config import Settings
from app.domain import AlertKind, AlertSeverity, EndpointStatus
from app.models import CheckResult, Endpoint
from app.observability.metrics import forget_endpoint
from app.schemas import (
    CheckResultRead,
    EndpointCreate,
    EndpointRead,
    EndpointUpdate,
    MaintenanceRequest,
    Page,
)
from app.services.events import EventBus
from app.services.notifier import AlertEvent
from app.services.url_guard import UnsafeTargetError, ensure_public_target

router = APIRouter(prefix="/endpoints", tags=["endpoints"])

_DUPLICATE_NAME = HTTPException(status.HTTP_409_CONFLICT, detail="an endpoint with this name already exists")


async def _guard_target(settings: Settings, url: str) -> None:
    if not settings.block_private_targets:
        return
    try:
        await ensure_public_target(url)
    except UnsafeTargetError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"unsafe target: {exc}") from None


def _publish(events: EventBus, action: str, endpoint: Endpoint) -> None:
    events.publish(
        "endpoint",
        {"action": action, "endpoint": EndpointRead.model_validate(endpoint).model_dump(mode="json")},
    )


@router.post("", response_model=EndpointRead, status_code=status.HTTP_201_CREATED, dependencies=[WriteAuth])
async def create_endpoint(
    payload: EndpointCreate, session: SessionDep, settings: SettingsDep, events: EventsDep
) -> Endpoint:
    await _guard_target(settings, str(payload.url))
    endpoint = Endpoint(
        **payload.model_dump(exclude={"url"}),
        url=str(payload.url),
        current_status=EndpointStatus.UNKNOWN,
        consecutive_failures=0,
        next_check_at=utcnow(),  # first check on the next scheduler tick
    )
    session.add(endpoint)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _DUPLICATE_NAME from None
    await session.refresh(endpoint)
    _publish(events, "created", endpoint)
    return endpoint


@router.get("", response_model=Page[EndpointRead])
async def list_endpoints(
    session: SessionDep,
    status_filter: Annotated[EndpointStatus | None, Query(alias="status")] = None,
    is_active: bool | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> dict:
    stmt = select(Endpoint).order_by(Endpoint.id)
    if status_filter is not None:
        stmt = stmt.where(Endpoint.current_status == status_filter)
    if is_active is not None:
        stmt = stmt.where(Endpoint.is_active.is_(is_active))
    items, total = await paginate(session, stmt, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{endpoint_id}", response_model=EndpointRead)
async def get_endpoint(endpoint_id: int, session: SessionDep) -> Endpoint:
    return await get_endpoint_or_404(session, endpoint_id)


@router.patch("/{endpoint_id}", response_model=EndpointRead, dependencies=[WriteAuth])
async def update_endpoint(
    endpoint_id: int,
    payload: EndpointUpdate,
    session: SessionDep,
    settings: SettingsDep,
    events: EventsDep,
) -> Endpoint:
    endpoint = await get_endpoint_or_404(session, endpoint_id)
    changes = payload.model_dump(exclude_unset=True, mode="json")
    if not changes:
        return endpoint

    # Re-validate the merged configuration so cross-field rules (timeout budget) still hold.
    current = EndpointRead.model_validate(endpoint).model_dump(include=set(EndpointCreate.model_fields))
    try:
        merged = EndpointCreate.model_validate({**current, **changes})
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_context=False)) from None
    if "url" in changes:
        await _guard_target(settings, str(merged.url))

    old_name = endpoint.name
    for field in changes:
        value = getattr(merged, field)
        setattr(endpoint, field, str(value) if field == "url" else value)
    if {"interval_seconds", "is_active", "url"} & changes.keys():
        endpoint.next_check_at = utcnow()
    if "url" in changes:
        endpoint.ssl_checked_at = None  # re-probe the new host's certificate

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _DUPLICATE_NAME from None
    if endpoint.name != old_name:
        forget_endpoint(old_name)
    await session.refresh(endpoint)
    _publish(events, "updated", endpoint)
    return endpoint


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[WriteAuth])
async def delete_endpoint(endpoint_id: int, session: SessionDep, events: EventsDep) -> Response:
    endpoint = await get_endpoint_or_404(session, endpoint_id)
    name = endpoint.name
    await session.delete(endpoint)
    await session.commit()
    forget_endpoint(name)
    events.publish("endpoint", {"action": "deleted", "endpoint": {"id": endpoint_id, "name": name}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{endpoint_id}/check", response_model=CheckResultRead, dependencies=[WriteAuth])
async def run_check_now(endpoint_id: int, monitor: MonitorDep) -> CheckResultRead:
    """Run a health check immediately and return its result."""
    result = await monitor.run_now(endpoint_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="endpoint not found")
    return result


@router.post("/{endpoint_id}/test-alert", dependencies=[WriteAuth])
async def send_test_alert(endpoint_id: int, request: Request, session: SessionDep) -> dict:
    """Send a test alert email to this endpoint's contacts, to confirm delivery works."""
    endpoint = await get_endpoint_or_404(session, endpoint_id)
    email = request.app.state.email_notifier
    if email is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Email alerts are not configured on the server (set SENTINEL_EMAIL_PROVIDER).",
        )
    event = AlertEvent(
        alert_id=0,
        kind=AlertKind.DOWN,
        severity=AlertSeverity.CRITICAL,
        endpoint_id=endpoint.id,
        endpoint_name=endpoint.name,
        endpoint_url=endpoint.url,
        message=f"Test alert: this is what you will receive when {endpoint.name} goes down.",
        created_at=utcnow(),
        recipients=tuple(endpoint.alert_emails or ()),
        is_test=True,
    )
    recipients = email.recipients_for(event)
    if not recipients:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="This endpoint has no alert emails yet.")
    if not await email.notify(event):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="The email provider rejected the message.")
    return {"sent_to": recipients}


@router.post("/{endpoint_id}/maintenance", response_model=EndpointRead, dependencies=[WriteAuth])
async def start_maintenance(
    endpoint_id: int, payload: MaintenanceRequest, session: SessionDep, events: EventsDep
) -> Endpoint:
    """Mute alerts for planned downtime. Checks keep running; the SLA ignores these checks."""
    endpoint = await get_endpoint_or_404(session, endpoint_id)
    endpoint.maintenance_until = utcnow() + timedelta(minutes=payload.minutes)
    endpoint.maintenance_reason = payload.reason
    await session.commit()
    await session.refresh(endpoint)
    _publish(events, "updated", endpoint)
    return endpoint


@router.delete("/{endpoint_id}/maintenance", response_model=EndpointRead, dependencies=[WriteAuth])
async def end_maintenance(endpoint_id: int, session: SessionDep, events: EventsDep) -> Endpoint:
    endpoint = await get_endpoint_or_404(session, endpoint_id)
    endpoint.maintenance_until = None
    endpoint.maintenance_reason = None
    await session.commit()
    await session.refresh(endpoint)
    _publish(events, "updated", endpoint)
    return endpoint


@router.get("/{endpoint_id}/results", response_model=Page[CheckResultRead])
async def list_results(
    endpoint_id: int,
    session: SessionDep,
    hours: WindowHours = 24,
    success: bool | None = None,
    anomalies_only: bool = False,
    limit: Limit = 100,
    offset: Offset = 0,
) -> dict:
    await get_endpoint_or_404(session, endpoint_id)
    stmt = (
        select(CheckResult)
        .where(CheckResult.endpoint_id == endpoint_id, CheckResult.checked_at >= since(hours))
        .order_by(CheckResult.checked_at.desc())
    )
    if success is not None:
        stmt = stmt.where(CheckResult.is_success.is_(success))
    if anomalies_only:
        stmt = stmt.where(CheckResult.is_anomaly.is_(True))
    items, total = await paginate(session, stmt, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
