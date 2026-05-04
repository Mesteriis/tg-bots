import json

from tg_bot_aggregator.infra.events import (
    EventRecord,
    MemoryEventBus,
    build_event_payload,
    format_sse,
)


def test_event_payload_and_sse_frame_shape() -> None:
    payload = build_event_payload("send.succeeded", {"send_history_id": 1})
    frame = format_sse(EventRecord("1-0", "send.succeeded", payload))

    assert payload["schema_version"] == "v1"
    assert payload["event_type"] == "send.succeeded"
    assert frame.startswith("id: 1-0\nevent: send.succeeded\n")
    assert json.loads(frame.split("data: ", 1)[1])["data"]["send_history_id"] == 1


async def test_memory_event_bus_assigns_incrementing_ids() -> None:
    bus = MemoryEventBus()

    first = await bus.publish("send.created", {"id": 1})
    second = await bus.publish("send.succeeded", {"id": 1})

    assert (first, second) == ("1", "2")
    assert (await bus.latest()).event_type == "send.succeeded"

