from dataclasses import dataclass
from datetime import datetime, timedelta

from tg_bot_aggregator.config import Settings
from tg_bot_aggregator.telegram_bot_api import TelegramBotApiError


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    terminal_status: str
    error_kind: str
    retry_after_seconds: int | None
    next_retry_at: datetime | None


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
    cap = max(base, settings.send_retry_max_delay_seconds)
    delay = base * (2 ** max(0, attempt_number - 1))
    return int(min(cap, delay))


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
