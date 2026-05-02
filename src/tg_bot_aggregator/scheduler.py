import asyncio
import os

from tg_bot_aggregator.tasks import refresh_all_analytics_targets


async def main() -> None:
    interval = int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "3600"))
    while True:
        await refresh_all_analytics_targets.kiq()
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())

