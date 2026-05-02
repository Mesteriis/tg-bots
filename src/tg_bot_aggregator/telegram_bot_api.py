from typing import Any

import httpx

from tg_bot_aggregator.security import redact_secrets


class TelegramBotApiError(RuntimeError):
    def __init__(self, method: str, error_code: int | None, description: str, payload: dict[str, Any]):
        super().__init__(description)
        self.method = method
        self.error_code = error_code
        self.description = description
        self.payload = payload


class TelegramBotApiClient:
    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)

    def _build_url(self, token: str, method: str) -> str:
        return f"{self.base_url}/bot{token}/{method}"

    async def _post(self, token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        close_client = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout)
            close_client = True
        try:
            response = await client.post(self._build_url(token, method), json=payload)
            data = response.json()
        finally:
            if close_client:
                await client.aclose()

        if response.status_code >= 400 or data.get("ok") is not True:
            raise TelegramBotApiError(
                method=method,
                error_code=data.get("error_code", response.status_code),
                description=data.get("description", response.text),
                payload=redact_secrets(data),
            )
        return data

    async def get_me(self, token: str) -> dict[str, Any]:
        return await self._post(token, "getMe", {})

    async def send_message(
        self,
        token: str,
        chat_id: str,
        text: str,
        parse_mode: str | None = None,
        disable_web_page_preview: bool | None = None,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if disable_web_page_preview is not None:
            payload["disable_web_page_preview"] = disable_web_page_preview
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        return await self._post(token, "sendMessage", payload)

    async def send_document(
        self,
        token: str,
        chat_id: str,
        document: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "document": document}
        if caption:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        return await self._post(token, "sendDocument", payload)

    async def send_video(
        self,
        token: str,
        chat_id: str,
        video: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "video": video}
        if caption:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        return await self._post(token, "sendVideo", payload)

