from __future__ import annotations

import logging
import threading
from datetime import datetime

from sqlalchemy import select

from app.database import session_scope
from app.models import WorkflowTrigger
from app.services import triggers

log = logging.getLogger("agentflow.scheduler")


class CronScheduler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_purge: datetime | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        now = datetime.now()
        with session_scope() as session:
            for trigger in triggers.enabled_cron_triggers(session):
                if trigger.next_run_at is None or trigger.next_run_at <= now:
                    try:
                        trigger.next_run_at = triggers.next_run(trigger.cron_expression, trigger.timezone)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("trigger %s schedule error: %s", trigger.id, exc)
        self._thread = threading.Thread(target=self._loop, name="trigger-scheduler", daemon=True)
        self._thread.start()
        log.info("trigger scheduler started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def refresh(self, trigger_id: int) -> None:
        try:
            with session_scope() as session:
                trigger = session.scalar(
                    select(WorkflowTrigger).where(
                        WorkflowTrigger.id == trigger_id, WorkflowTrigger.deleted == 0
                    )
                )
                if trigger is None or trigger.type != triggers.TYPE_CRON or not trigger.cron_expression:
                    return
                trigger.next_run_at = triggers.next_run(trigger.cron_expression, trigger.timezone)
        except Exception as exc:  # noqa: BLE001
            log.warning("trigger %s refresh failed: %s", trigger_id, exc)

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001
                log.warning("trigger scheduler tick failed: %s", exc)

    def _tick(self) -> None:
        now = datetime.now()
        due: list[int] = []
        purge = self._last_purge is None or (now - self._last_purge).total_seconds() >= 600
        with session_scope() as session:
            for trigger in triggers.enabled_cron_triggers(session):
                if trigger.next_run_at is None or trigger.next_run_at <= now:
                    try:
                        trigger.next_run_at = triggers.next_run(trigger.cron_expression, trigger.timezone)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("trigger %s schedule error: %s", trigger.id, exc)
                        continue
                    due.append(trigger.id)
        if purge:
            self._last_purge = now
            try:
                triggers.purge_expired_locks()
            except Exception as exc:  # noqa: BLE001
                log.warning("purge expired scheduler locks failed: %s", exc)
        for trigger_id in due:
            triggers.fire_cron(trigger_id)


_scheduler: CronScheduler | None = None


def get_scheduler() -> CronScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = CronScheduler()
    return _scheduler
