import json
from typing import Any

import httpx
import pytest

from tg_bot_aggregator.infra.telegram_client import TelegramBotApiClient, TelegramBotApiError


@pytest.mark.parametrize(
    ("call", "method"),
    [
        ("get_me", "getMe"),
        ("send_message", "sendMessage"),
        ("send_document", "sendDocument"),
        ("send_video", "sendVideo"),
    ],
)
async def test_bot_api_client_uses_configured_base_url(call: str, method: str) -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 10}})

    client = TelegramBotApiClient(
        "http://telegram-bot-api:8081", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    if call == "get_me":
        await client.get_me("123:token")
    elif call == "send_message":
        await client.send_message("123:token", "@chat", "hello", message_thread_id=7)
    elif call == "send_document":
        await client.send_document("123:token", "@chat", "file:///shared/media/a.mp4")
    else:
        await client.send_video("123:token", "@chat", "file:///shared/media/a.mp4")

    assert seen["url"] == f"http://telegram-bot-api:8081/bot123:token/{method}"


async def test_bot_api_client_raises_redacted_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "ok": False,
                "error_code": 400,
                "description": "bad token 123456:ABCdef_123456789012345",
            },
        )

    client = TelegramBotApiClient(
        "http://telegram-bot-api:8081", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(TelegramBotApiError) as exc_info:
        await client.get_me("123456:ABCdef_123456789012345")

    assert exc_info.value.error_code == 400
    assert "123456:ABCdef" not in str(exc_info.value.payload)


async def test_bot_api_client_does_not_log_tokenized_urls(caplog: pytest.LogCaptureFixture) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"id": 1}})

    caplog.set_level("INFO")
    client = TelegramBotApiClient(
        "http://telegram-bot-api:8081",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    await client.get_me("123456:ABCdef_123456789012345")

    assert not any("123456:ABCdef" in record.getMessage() for record in caplog.records)


async def test_bot_api_client_supports_polling_methods() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.read())))
        if request.url.path.endswith("/getUpdates"):
            return httpx.Response(
                200,
                json={"ok": True, "result": [{"update_id": 42, "message": {"message_id": 7}}]},
            )
        return httpx.Response(200, json={"ok": True, "result": True})

    client = TelegramBotApiClient(
        "http://telegram-bot-api:8081",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    await client.delete_webhook("123:token", drop_pending_updates=True)
    updates = await client.get_updates(
        "123:token",
        offset=43,
        poll_timeout=10,
        allowed_updates=["message", "channel_post"],
    )

    assert updates == [{"update_id": 42, "message": {"message_id": 7}}]
    assert calls == [
        ("deleteWebhook", {"drop_pending_updates": True}),
        (
            "getUpdates",
            {
                "offset": 43,
                "timeout": 10,
                "allowed_updates": ["message", "channel_post"],
            },
        ),
    ]


async def test_bot_api_client_sends_reply_markup() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.read()))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 10}})

    client = TelegramBotApiClient(
        "http://telegram-bot-api:8081",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    reply_markup = {
        "inline_keyboard": [
            [{"text": "Copy chat", "copy_text": {"text": "-100123"}}],
        ]
    }

    await client.send_message("123:token", "-100123", "diagnostic", reply_markup=reply_markup)

    assert seen["reply_markup"] == reply_markup


async def test_bot_api_client_checks_chat_metadata() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.read())))
        if request.url.path.endswith("/getChat"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {"id": -100, "type": "supergroup", "title": "Ops"},
                },
            )
        return httpx.Response(200, json={"ok": True, "result": 42})

    client = TelegramBotApiClient(
        "http://telegram-bot-api:8081",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    chat = await client.get_chat("123:token", "-100")
    count = await client.get_chat_member_count("123:token", "-100")

    assert chat["result"]["title"] == "Ops"
    assert count == 42
    assert calls == [
        ("getChat", {"chat_id": "-100"}),
        ("getChatMemberCount", {"chat_id": "-100"}),
    ]


async def test_bot_api_client_falls_back_to_localhost_when_internal_hostname_is_unresolvable(
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def post(self, url: str, json: dict[str, Any]) -> httpx.Response:
            self.calls.append(url)
            if url.startswith("http://telegram-bot-api:8081/"):
                request = httpx.Request("POST", url)
                raise httpx.ConnectError("[Errno -2] Name or service not known", request=request)
            return httpx.Response(
                200,
                json={"ok": True, "result": {"id": 1, "username": "ops_bot"}},
            )

        async def aclose(self) -> None:
            return None

    fake_client = FakeClient()
    client = TelegramBotApiClient("http://telegram-bot-api:8081", fake_client)  # type: ignore[arg-type]

    result = await client.get_me("123:token")

    assert result["result"]["username"] == "ops_bot"
    assert fake_client.calls == [
        "http://telegram-bot-api:8081/bot123:token/getMe",
        "http://127.0.0.1:8081/bot123:token/getMe",
    ]
    assert client.base_url == "http://127.0.0.1:8081"
