from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from typing import Protocol

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiError


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    terminal_status: str
    error_kind: str
    retry_after_seconds: int | None
    next_retry_at: datetime | None


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    bucket_key: str | None
    retry_after_seconds: int | None
    message: str | None


@dataclass(frozen=True)
class RateBucketSnapshot:
    bucket_key: str
    limit: int
    used: int
    retry_after_seconds: int | None


class RateLimitStore(Protocol):
    async def increment_window(self, key: str, window_seconds: int) -> int:
        ...

    async def get_count(self, key: str) -> int:
        ...

    async def retry_after(self, key: str) -> int | None:
        ...


class MemoryRateLimitStore:
    def __init__(self) -> None:
        self.counts: dict[str, int] = defaultdict(int)

    async def increment_window(self, key: str, window_seconds: int) -> int:
        self.counts[key] += 1
        return self.counts[key]

    async def get_count(self, key: str) -> int:
        return self.counts[key]

    async def retry_after(self, key: str) -> int | None:
        return 60


class RedisRateLimitStore:
    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    async def increment_window(self, key: str, window_seconds: int) -> int:
        value = await self.redis.incr(key)
        if value == 1:
            await self.redis.expire(key, window_seconds)
        return int(value)

    async def get_count(self, key: str) -> int:
        value = await self.redis.get(key)
        return int(value or 0)

    async def retry_after(self, key: str) -> int | None:
        ttl = await self.redis.ttl(key)
        if ttl is None or int(ttl) < 0:
            return None
        return int(ttl)


class SendRateLimiter:
    def __init__(
        self,
        *,
        store: RateLimitStore,
        global_limit_per_minute: int | None,
        bot_limit_per_minute: int | None,
        chat_limit_per_minute: int | None,
        destination_limit_per_minute: int | None,
    ) -> None:
        self.store = store
        self.limits = {
            "send:global": global_limit_per_minute,
            "send:bot": bot_limit_per_minute,
            "send:chat": chat_limit_per_minute,
            "send:destination": destination_limit_per_minute,
        }

    def _bucket_limits(
        self,
        *,
        bot_id: int,
        chat_id: str,
        destination_id: int | None,
    ) -> list[tuple[str, int]]:
        buckets: list[tuple[str, int]] = []
        global_limit = self.limits["send:global"]
        bot_limit = self.limits["send:bot"]
        chat_limit = self.limits["send:chat"]
        destination_limit = self.limits["send:destination"]
        if global_limit is not None:
            buckets.append(("send:global", global_limit))
        if bot_limit is not None:
            buckets.append((f"send:bot:{bot_id}", bot_limit))
        if chat_limit is not None:
            buckets.append((f"send:chat:{chat_id}", chat_limit))
        if destination_limit is not None and destination_id is not None:
            buckets.append((f"send:destination:{destination_id}", destination_limit))
        return buckets

    async def check_and_increment(
        self,
        *,
        bot_id: int,
        chat_id: str,
        destination_id: int | None,
    ) -> RateLimitDecision:
        for key, limit in self._bucket_limits(
            bot_id=bot_id,
            chat_id=chat_id,
            destination_id=destination_id,
        ):
            current = await self.store.get_count(key)
            if current >= limit:
                return RateLimitDecision(
                    allowed=False,
                    bucket_key=key,
                    retry_after_seconds=await self.store.retry_after(key),
                    message=f"rate limit exceeded for {key}",
                )
        for key, _limit in self._bucket_limits(
            bot_id=bot_id,
            chat_id=chat_id,
            destination_id=destination_id,
        ):
            await self.store.increment_window(key, 60)
        return RateLimitDecision(
            allowed=True,
            bucket_key=None,
            retry_after_seconds=None,
            message=None,
        )

    async def snapshots(
        self,
        *,
        bot_id: int,
        chat_id: str,
        destination_id: int | None,
    ) -> list[RateBucketSnapshot]:
        rows: list[RateBucketSnapshot] = []
        for key, limit in self._bucket_limits(
            bot_id=bot_id,
            chat_id=chat_id,
            destination_id=destination_id,
        ):
            rows.append(
                RateBucketSnapshot(
                    bucket_key=key,
                    limit=limit,
                    used=await self.store.get_count(key),
                    retry_after_seconds=await self.store.retry_after(key),
                )
            )
        return rows


def _retry_after_from_payload(payload: dict | None) -> int | None:
    if not isinstance(payload, dict):
        return None
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        return None
    retry_after = parameters.get("retry_after")
    if isinstance(retry_after, int) and retry_after > 0:
        return retry_after
    return None


def classify_telegram_error(error: TelegramBotApiError) -> str:
    if error.error_code == 429:
        return "telegram_rate_limit"
    if error.error_code is None:
        return "network"
    if 500 <= error.error_code <= 599:
        return "telegram_server"
    if 400 <= error.error_code <= 499:
        return "telegram_client"
    return "unknown"


def _bounded_backoff(settings: Settings, attempt_number: int) -> int:
    base = max(0.0, settings.send_retry_base_delay_seconds)
    if base == 0:
        return 0
    cap = max(base, settings.send_retry_max_delay_seconds)
    delay = base * (2 ** max(0, attempt_number - 1))
    return ceil(min(cap, delay))


def compute_retry_decision(
    *,
    settings: Settings,
    error: TelegramBotApiError,
    attempt_number: int,
    now: datetime,
) -> RetryDecision:
    error_kind = classify_telegram_error(error)
    retryable = error_kind in {"telegram_rate_limit", "telegram_server", "network"}
    if not retryable:
        return RetryDecision(
            retry=False,
            terminal_status="blocked",
            error_kind=error_kind,
            retry_after_seconds=None,
            next_retry_at=None,
        )
    if attempt_number >= max(1, settings.send_retry_max_attempts):
        return RetryDecision(
            retry=False,
            terminal_status="dead_letter",
            error_kind=error_kind,
            retry_after_seconds=None,
            next_retry_at=None,
        )
    retry_after = _retry_after_from_payload(error.payload)
    delay = retry_after if retry_after is not None else _bounded_backoff(settings, attempt_number)
    return RetryDecision(
        retry=True,
        terminal_status="deferred",
        error_kind=error_kind,
        retry_after_seconds=delay,
        next_retry_at=now + timedelta(seconds=delay),
    )
