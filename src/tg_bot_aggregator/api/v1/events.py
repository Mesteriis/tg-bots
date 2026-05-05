from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

from tg_bot_aggregator.infra.events import EventRecord, build_event_payload, format_sse

router = APIRouter(tags=["events"])


@router.get("/events", response_model=None)
async def events(request: Request, once: bool = False):
    bus = request.app.state.event_bus
    if once:
        record = await bus.latest()
        if record is None:
            record = EventRecord("0", "heartbeat", build_event_payload("heartbeat", {}))
        return PlainTextResponse(format_sse(record), media_type="text/event-stream")

    last_event_id = request.headers.get("last-event-id")

    async def stream() -> object:
        async for record in bus.stream(last_event_id):
            yield format_sse(record)

    return StreamingResponse(stream(), media_type="text/event-stream")
