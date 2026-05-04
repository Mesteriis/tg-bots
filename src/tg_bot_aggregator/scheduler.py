import asyncio
import logging
import os
from typing import Protocol

from tg_bot_aggregator.tasks import (
    due_send_history,
    ops_automation_rules,
    refresh_all_analytics_targets,
    scheduled_backup_if_due,
)

logger = logging.getLogger(__name__)


class SchedulerTask(Protocol):
    async def kiq(self) -> object: ...


async def _enqueue_task(task: SchedulerTask) -> None:
    try:
        await task.kiq()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("failed to enqueue scheduled task")


async def main() -> None:
    interval = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "3600"))
    while True:
        for task in (
            refresh_all_analytics_targets,
            due_send_history,
            scheduled_backup_if_due,
            ops_automation_rules,
        ):
            await _enqueue_task(task)
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
