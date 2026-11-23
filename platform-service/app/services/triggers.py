from __future__ import annotations

import base64
import logging
import secrets
import threading
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import session_scope
from app.errors import BizError, not_found
from app.models import SchedulerLock, Workflow, WorkflowTrigger
from app.security import CurrentUser
from app.serialization import dumps, iso, loads

log = logging.getLogger("agentflow.triggers")

TYPE_CRON = "CRON"
TYPE_WEBHOOK = "WEBHOOK"
DEFAULT_TIMEZONE = "Asia/Shanghai"
CRON_LEASE = timedelta(seconds=10)

_firing: set[int] = set()
_firing_lock = threading.Lock()


def validate_cron(expression: str | None) -> str:
    value = " ".join((expression or "").strip().split())
    if not value:
        raise BizError("CRON 表达式不能为空")
    fields = len(value.split(" "))
    if fields == 5:
        value = "0 " + value
    elif fields != 6:
        raise BizError("CRON 表达式需为 5 段或 6 段")
    try:
        croniter(value)
    except (ValueError, KeyError) as exc:
        raise BizError(f"CRON 表达式不合法: {exc}") from exc
    return value


def _zone(timezone: str | None) -> ZoneInfo:
    value = (timezone or "").strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(value)
    except Exception as exc:
        raise BizError(f"时区不合法: {value}") from exc


def normalize_timezone(timezone: str | None) -> str:
    value = (timezone or "").strip() or DEFAULT_TIMEZONE
    _zone(value)
    return value


def next_run(cron: str, timezone: str) -> datetime:
    zone = _zone(timezone)
    base = datetime.now(zone)
    nxt = croniter(cron, base).get_next(datetime)
    return nxt.replace(tzinfo=None)


def new_token() -> str:
    return "wh_" + base64.urlsafe_b64encode(secrets.token_bytes(24)).decode("ascii").rstrip("=")


def normalize_type(value: str | None) -> str:
    text = (value or "").strip().upper()
    if text not in {TYPE_CRON, TYPE_WEBHOOK}:
        raise BizError("触发类型仅支持 CRON 或 WEBHOOK")
    return text


def to_vo(trigger: WorkflowTrigger) -> dict[str, Any]:
    return {
        "id": trigger.id,
        "workflowId": trigger.workflow_id,
        "name": trigger.name,
        "type": trigger.type,
        "enabled": trigger.enabled == 1,
        "cronExpression": trigger.cron_expression,
        "timezone": trigger.timezone,
        "webhookPath": (
            "/api/triggers/webhook/" + trigger.webhook_token
            if trigger.type == TYPE_WEBHOOK and trigger.webhook_token
            else None
        ),
        "input": parse_input(trigger.input_data),
        "lastRunId": trigger.last_run_id,
        "lastStatus": trigger.last_status,
        "lastRunAt": iso(trigger.last_run_at),
        "nextRunAt": iso(trigger.next_run_at),
        "createdAt": iso(trigger.created_at),
        "updatedAt": iso(trigger.updated_at),
    }


def _require_workflow(session: Session, workflow_id: int, user: CurrentUser | None) -> Workflow:
    workflow = session.scalar(select(Workflow).where(Workflow.id == workflow_id, Workflow.deleted == 0))
    if workflow is None:
        raise not_found(f"工作流不存在: {workflow_id}")
    if (
        user is not None
        and workflow.user_id is not None
        and workflow.user_id != user.id
        and not user.is_admin
    ):
        raise not_found(f"工作流不存在: {workflow_id}")
    return workflow


def _require_trigger(session: Session, trigger_id: int, user: CurrentUser | None) -> WorkflowTrigger:
    trigger = session.scalar(
        select(WorkflowTrigger).where(WorkflowTrigger.id == trigger_id, WorkflowTrigger.deleted == 0)
    )
    if trigger is None:
        raise not_found(f"触发器不存在: {trigger_id}")
    _require_workflow(session, trigger.workflow_id, user)
    return trigger


def list_triggers(session: Session, workflow_id: int, user: CurrentUser) -> list[dict[str, Any]]:
    _require_workflow(session, workflow_id, user)
    rows = session.scalars(
        select(WorkflowTrigger)
        .where(WorkflowTrigger.workflow_id == workflow_id, WorkflowTrigger.deleted == 0)
        .order_by(WorkflowTrigger.id.desc())
    ).all()
    return [to_vo(item) for item in rows]


def create(session: Session, workflow_id: int, payload: dict[str, Any], user: CurrentUser) -> dict[str, Any]:
    workflow = _require_workflow(session, workflow_id, user)
    trigger_type = normalize_type(payload.get("type"))
    cron = validate_cron(payload.get("cronExpression")) if trigger_type == TYPE_CRON else None
    timezone = normalize_timezone(payload.get("timezone"))
    trigger = WorkflowTrigger(
        workflow_id=workflow_id,
        user_id=workflow.user_id,
        name=str(payload.get("name") or "").strip(),
        type=trigger_type,
        enabled=1 if payload.get("enabled", True) else 0,
        cron_expression=cron,
        timezone=timezone,
        webhook_token=new_token() if trigger_type == TYPE_WEBHOOK else None,
        input_data=dumps(payload.get("input") or {}),
        next_run_at=next_run(cron, timezone) if cron else None,
    )
    session.add(trigger)
    session.flush()
    _changed(trigger.id)
    return to_vo(trigger)


def update_trigger(session: Session, trigger_id: int, payload: dict[str, Any],
                    user: CurrentUser) -> dict[str, Any]:
    trigger = _require_trigger(session, trigger_id, user)
    trigger_type = normalize_type(payload.get("type"))
    cron = validate_cron(payload.get("cronExpression")) if trigger_type == TYPE_CRON else None
    timezone = normalize_timezone(payload.get("timezone"))
    trigger.name = str(payload.get("name") or "").strip()
    trigger.type = trigger_type
    trigger.enabled = 1 if payload.get("enabled", True) else 0
    trigger.cron_expression = cron
    trigger.timezone = timezone
    trigger.input_data = dumps(payload.get("input") or {})
    trigger.next_run_at = next_run(cron, timezone) if cron else None
    if trigger_type == TYPE_WEBHOOK:
        if not trigger.webhook_token:
            trigger.webhook_token = new_token()
    else:
        trigger.webhook_token = None
    session.flush()
    _changed(trigger.id)
    return to_vo(trigger)


def delete(session: Session, trigger_id: int, user: CurrentUser) -> None:
    trigger = _require_trigger(session, trigger_id, user)
    trigger.deleted = 1
    session.flush()
    _changed(trigger_id)


def rotate_token(session: Session, trigger_id: int, user: CurrentUser) -> dict[str, Any]:
    trigger = _require_trigger(session, trigger_id, user)
    if trigger.type != TYPE_WEBHOOK:
        raise BizError("只有 Webhook 触发器才有令牌")
    trigger.webhook_token = new_token()
    session.flush()
    return to_vo(trigger)


def run_now(session: Session, trigger_id: int, user: CurrentUser) -> dict[str, Any]:
    trigger = _require_trigger(session, trigger_id, user)
    fire(session, trigger, guard=False, check_enabled=False)
    session.expire_all()
    latest = session.get(WorkflowTrigger, trigger_id)
    return to_vo(latest)


def webhook(session: Session, token: str, body: Any) -> dict[str, Any]:
    trigger = session.scalar(
        select(WorkflowTrigger).where(
            WorkflowTrigger.webhook_token == (token or "").strip(),
            WorkflowTrigger.enabled == 1,
            WorkflowTrigger.deleted == 0,
        )
    )
    if trigger is None or trigger.type != TYPE_WEBHOOK:
        raise not_found("Webhook 不存在或已停用")
    data = parse_input(trigger.input_data)
    if isinstance(body, dict):
        data.update(body)
    elif body is not None:
        data["body"] = body
    update_last_run(session, trigger.id, None, "RUNNING")
    session.commit()
    from app.services.execution import get_execution_service

    run_id = get_execution_service().submit(
        trigger.workflow_id,
        {"input": data},
        trigger.user_id,
        True,
        lambda result: _finish_run(trigger.id, result),
    )
    return {"triggerId": trigger.id, "runId": run_id, "status": "ACCEPTED"}


def fire(session: Session, trigger: WorkflowTrigger, guard: bool, check_enabled: bool) -> str:
    if check_enabled and trigger.enabled != 1:
        raise BizError("触发器已停用")
    if guard and not _register_firing(trigger.id):
        raise BizError("上一次执行尚未结束")
    workflow = session.scalar(
        select(Workflow).where(Workflow.id == trigger.workflow_id, Workflow.deleted == 0)
    )
    if workflow is None:
        _unregister_firing(trigger.id)
        raise not_found(f"工作流不存在: {trigger.workflow_id}")
    update_last_run(session, trigger.id, None, "RUNNING")
    session.commit()
    from app.services.execution import get_execution_service

    try:
        return get_execution_service().submit(
            trigger.workflow_id,
            {"input": parse_input(trigger.input_data)},
            trigger.user_id,
            True,
            lambda result: _finish_run(trigger.id, result, guard),
        )
    except RuntimeError:
        if guard:
            _unregister_firing(trigger.id)
        raise


def fire_cron(trigger_id: int) -> None:
    with session_scope() as session:
        trigger = session.scalar(
            select(WorkflowTrigger).where(
                WorkflowTrigger.id == trigger_id, WorkflowTrigger.deleted == 0
            )
        )
        if trigger is None or trigger.enabled != 1 or trigger.type != TYPE_CRON:
            return
        if not _try_acquire_lock(session, f"cron:{trigger_id}", CRON_LEASE):
            return
        try:
            fire(session, trigger, guard=True, check_enabled=True)
        except Exception as exc:  # noqa: BLE001
            log.error("trigger %s fire failed: %s", trigger_id, exc)
            update_last_run(session, trigger_id, None, "FAILED")


def enabled_cron_triggers(session: Session) -> list[WorkflowTrigger]:
    return list(
        session.scalars(
            select(WorkflowTrigger).where(
                WorkflowTrigger.enabled == 1,
                WorkflowTrigger.type == TYPE_CRON,
                WorkflowTrigger.cron_expression.is_not(None),
                WorkflowTrigger.deleted == 0,
            )
        ).all()
    )


def find(session: Session, trigger_id: int) -> WorkflowTrigger | None:
    return session.scalar(
        select(WorkflowTrigger).where(WorkflowTrigger.id == trigger_id, WorkflowTrigger.deleted == 0)
    )


def refresh_next_run(trigger_id: int) -> None:
    with session_scope() as session:
        trigger = session.get(WorkflowTrigger, trigger_id)
        if trigger is None or trigger.type != TYPE_CRON or not trigger.cron_expression:
            return
        trigger.next_run_at = next_run(trigger.cron_expression, trigger.timezone)


def update_last_run(session: Session, trigger_id: int, run_id: str | None, status: str | None) -> None:
    trigger = session.get(WorkflowTrigger, trigger_id)
    if trigger is None:
        return
    trigger.last_run_id = run_id
    trigger.last_status = status
    trigger.last_run_at = datetime.now()
    if trigger.type == TYPE_CRON and trigger.cron_expression:
        try:
            trigger.next_run_at = next_run(trigger.cron_expression, trigger.timezone)
        except Exception:  # noqa: BLE001
            trigger.next_run_at = None


def parse_input(text: str | None) -> dict[str, Any]:
    value = loads(text, {})
    return value if isinstance(value, dict) else {}


def _finish_run(trigger_id: int, result: dict[str, Any], guard: bool = False) -> None:
    if guard:
        _unregister_firing(trigger_id)
    try:
        with session_scope() as session:
            update_last_run(session, trigger_id, result.get("runId"), result.get("status"))
    except Exception as exc:  # noqa: BLE001
        log.warning("trigger %s callback failed: %s", trigger_id, exc)


def _register_firing(trigger_id: int) -> bool:
    with _firing_lock:
        if trigger_id in _firing:
            return False
        _firing.add(trigger_id)
        return True


def _unregister_firing(trigger_id: int) -> None:
    with _firing_lock:
        _firing.discard(trigger_id)


def _changed(trigger_id: int) -> None:
    from app.services.scheduler import get_scheduler

    get_scheduler().refresh(trigger_id)


def _try_acquire_lock(session: Session, lock_key: str, lease: timedelta) -> bool:
    now = datetime.now()
    expires_at = now + lease
    owner = _owner_id()
    updated = session.execute(
        update(SchedulerLock)
        .where(SchedulerLock.lock_key == lock_key, SchedulerLock.expires_at < now)
        .values(owner=owner, expires_at=expires_at)
    ).rowcount
    if updated:
        session.commit()
        return True
    session.rollback()
    try:
        with session_scope() as inner:
            inner.add(SchedulerLock(lock_key=lock_key, owner=owner, expires_at=expires_at))
        return True
    except IntegrityError:
        return False


def purge_expired_locks() -> int:
    with session_scope() as session:
        removed = session.query(SchedulerLock).filter(SchedulerLock.expires_at < datetime.now()).delete()
        return int(removed or 0)


def _owner_id() -> str:
    global _OWNER
    try:
        return _OWNER
    except NameError:
        _OWNER = secrets.token_hex(16)
        return _OWNER
