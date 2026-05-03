import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Protocol

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.models import SendHistory, utc_now
from tg_bot_aggregator.repositories import SendAttemptRepository, SendHistoryRepository
from tg_bot_aggregator.security import redact_secrets
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
    async def check_and_increment_window(
        self,
        bucket_limits: list[tuple[str, int]],
        window_seconds: int,
    ) -> RateLimitDecision:
        ...

    async def increment_window(self, key: str, window_seconds: int) -> int:
        ...

    async def get_count(self, key: str) -> int:
        ...

    async def retry_after(self, key: str) -> int | None:
        ...


class MemoryRateLimitStore:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        self._buckets: dict[str, tuple[int, float]] = {}

    def _clear_expired(self, key: str, now: float) -> None:
        bucket = self._buckets.get(key)
        if bucket is not None and bucket[1] <= now:
            del self._buckets[key]

    def _retry_after_locked(self, key: str, now: float) -> int | None:
        bucket = self._buckets.get(key)
        if bucket is None:
            return None
        return max(1, ceil(bucket[1] - now))

    async def check_and_increment_window(
        self,
        bucket_limits: list[tuple[str, int]],
        window_seconds: int,
    ) -> RateLimitDecision:
        async with self._lock:
            now = self._clock()
            for key, _limit in bucket_limits:
                self._clear_expired(key, now)

            for key, limit in bucket_limits:
                current, _expires_at = self._buckets.get(key, (0, now + window_seconds))
                if current >= limit:
                    return RateLimitDecision(
                        allowed=False,
                        bucket_key=key,
                        retry_after_seconds=self._retry_after_locked(key, now),
                        message=f"rate limit exceeded for {key}",
                    )

            for key, _limit in bucket_limits:
                current, expires_at = self._buckets.get(key, (0, now + window_seconds))
                self._buckets[key] = (current + 1, expires_at)

        return RateLimitDecision(
            allowed=True,
            bucket_key=None,
            retry_after_seconds=None,
            message=None,
        )

    async def increment_window(self, key: str, window_seconds: int) -> int:
        async with self._lock:
            now = self._clock()
            self._clear_expired(key, now)
            current, expires_at = self._buckets.get(key, (0, now + window_seconds))
            current += 1
            self._buckets[key] = (current, expires_at)
            return current

    async def get_count(self, key: str) -> int:
        async with self._lock:
            now = self._clock()
            self._clear_expired(key, now)
            current, _expires_at = self._buckets.get(key, (0, now))
            return current

    async def retry_after(self, key: str) -> int | None:
        async with self._lock:
            now = self._clock()
            self._clear_expired(key, now)
            return self._retry_after_locked(key, now)


class RedisRateLimitStore:
    _CHECK_AND_INCREMENT_SCRIPT = """
local window = tonumber(ARGV[1])

for i = 1, #KEYS do
    local limit = tonumber(ARGV[i + 1])
    local count = tonumber(redis.call("GET", KEYS[i]) or "0")
    if count >= limit then
        local ttl = redis.call("TTL", KEYS[i])
        if ttl < 0 then
            redis.call("EXPIRE", KEYS[i], window)
            ttl = window
        end
        return {0, KEYS[i], ttl}
    end
end

for i = 1, #KEYS do
    local value = redis.call("INCR", KEYS[i])
    if value == 1 then
        redis.call("EXPIRE", KEYS[i], window)
    else
        local ttl = redis.call("TTL", KEYS[i])
        if ttl < 0 then
            redis.call("EXPIRE", KEYS[i], window)
        end
    end
end

return {1, false, false}
"""
    _INCREMENT_SCRIPT = """
local window = tonumber(ARGV[1])
local value = redis.call("INCR", KEYS[1])
if value == 1 then
    redis.call("EXPIRE", KEYS[1], window)
else
    local ttl = redis.call("TTL", KEYS[1])
    if ttl < 0 then
        redis.call("EXPIRE", KEYS[1], window)
    end
end
return value
"""

    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    @staticmethod
    def _decode_result_value(value) -> str | int | None:
        if value is False or value is None:
            return None
        if isinstance(value, bytes):
            return value.decode()
        if isinstance(value, int):
            return value
        return str(value)

    async def check_and_increment_window(
        self,
        bucket_limits: list[tuple[str, int]],
        window_seconds: int,
    ) -> RateLimitDecision:
        if not bucket_limits:
            return RateLimitDecision(
                allowed=True,
                bucket_key=None,
                retry_after_seconds=None,
                message=None,
            )

        keys = [key for key, _limit in bucket_limits]
        limits = [str(limit) for _key, limit in bucket_limits]
        result = await self.redis.eval(
            self._CHECK_AND_INCREMENT_SCRIPT,
            len(keys),
            *keys,
            str(window_seconds),
            *limits,
        )

        allowed = int(result[0]) == 1
        if allowed:
            return RateLimitDecision(
                allowed=True,
                bucket_key=None,
                retry_after_seconds=None,
                message=None,
            )

        bucket_key_value = self._decode_result_value(result[1])
        retry_after_value = self._decode_result_value(result[2])
        bucket_key = str(bucket_key_value)
        retry_after_seconds = int(retry_after_value) if retry_after_value is not None else None
        return RateLimitDecision(
            allowed=False,
            bucket_key=bucket_key,
            retry_after_seconds=retry_after_seconds,
            message=f"rate limit exceeded for {bucket_key}",
        )

    async def increment_window(self, key: str, window_seconds: int) -> int:
        value = await self.redis.eval(self._INCREMENT_SCRIPT, 1, key, str(window_seconds))
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
        return await self.store.check_and_increment_window(
            self._bucket_limits(
                bot_id=bot_id,
                chat_id=chat_id,
                destination_id=destination_id,
            ),
            60,
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


def latency_ms_since(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


class SendQueueService:
    def __init__(self, history: SendHistoryRepository, attempts: SendAttemptRepository) -> None:
        self.history = history
        self.attempts = attempts

    async def acquire_lease(
        self,
        row: SendHistory,
        worker_id: str,
        lease_seconds: int,
    ) -> SendHistory | None:
        return await self.history.acquire_due_lease(
            row_id=row.id,
            worker_id=worker_id,
            now=utc_now(),
            lease_seconds=lease_seconds,
        )

    async def record_attempt(
        self,
        *,
        row: SendHistory,
        worker_id: str,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        telegram_error_code: str | None,
        error_kind: str | None,
        error_message: str | None,
        retry_after_seconds: int | None,
        latency_ms: int | None,
        response_payload: dict[str, Any] | None,
    ) -> None:
        await self.attempts.create(
            send_history_id=row.id,
            attempt_number=row.attempt_count,
            worker_id=worker_id,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            telegram_error_code=telegram_error_code,
            error_kind=error_kind,
            error_message=error_message,
            retry_after_seconds=retry_after_seconds,
            latency_ms=latency_ms,
            response_payload_json=redact_secrets(response_payload),
        )
