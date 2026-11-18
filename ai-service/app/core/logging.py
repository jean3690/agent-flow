import logging
import os
from contextvars import ContextVar

run_id_var: ContextVar[str] = ContextVar("agentflow_run_id", default="-")


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = run_id_var.get()
        return True


def setup_logging() -> None:
    level = os.getenv("AI_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s [runId:%(run_id)s] %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(_RunIdFilter())
