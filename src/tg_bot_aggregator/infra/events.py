import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import redis.asyncio as redis


@dataclass(frozen=True)
class EventRecord:
    id: str
    event_type: str
    payload: dict[str, Any]


def build_event_payload(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "event_type": event_type,
        "data": data,
    }


def format_sse(record: EventRecord) -> str:
    data = json.dumps(record.payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {record.id}\nevent: {record.event_type}\ndata: {data}\n\n"


class MemoryEventBus:
    def __init__(self) -> None:
        self._records: list[EventRecord] = []
        self._condition = asyncio.Condition()

    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        async with self._condition:
            event_id = str(len(self._records) + 1)
            payload = build_event_payload(event_type, data)
            self._records.append(EventRecord(event_id, event_type, payload))
            self._condition.notify_all()
            return event_id

    async def latest(self) -> EventRecord | None:
        return self._records[-1] if self._records else None

    async def stream(self, last_event_id: str | None = None) -> AsyncIterator[EventRecord]:
        next_index = int(last_event_id or "0")
        while True:
            async with self._condition:
                while len(self._records) <= next_index:
                    await self._condition.wait()
                record = self._records[next_index]
                next_index += 1
            yield record


class RedisEventBus:
    def __init__(self, redis_url: str, stream_name: str = "tg-bot-aggregator:events") -> None:
        self.redis_url = redis_url
        self.stream_name = stream_name
        self._client: redis.Redis | None = None

    async def _redis(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    async def publish(self, event_type: str, data: dict[str, Any]) -> str:
        client = await self._redis()
        payload = build_event_payload(event_type, data)
        event_id = await client.xadd(
            self.stream_name,
            {"event_type": event_type, "payload": json.dumps(payload, ensure_ascii=False)},
        )
        return str(event_id)

    async def stream(self, last_event_id: str | None = None) -> AsyncIterator[EventRecord]:
        client = await self._redis()
        cursor = last_event_id or "$"
        while True:
            response = await client.xread({self.stream_name: cursor}, block=15_000, count=1)
            if not response:
                yield EventRecord("heartbeat", "heartbeat", build_event_payload("heartbeat", {}))
                continue
            _, records = response[0]
            for event_id, fields in records:
                cursor = event_id
                payload = json.loads(fields["payload"])
                yield EventRecord(event_id, fields["event_type"], payload)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
