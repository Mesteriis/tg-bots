import json
from typing import Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from tg_bot_aggregator.api.dependencies import create_send_service, get_session
from tg_bot_aggregator.domain.sending.service import SendService, SendServiceError
from tg_bot_aggregator.repositories import BotRepository

router = APIRouter(tags=["telegram-compatible"])


def _telegram_error(status_code: int, description: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error_code": status_code, "description": description},
        status_code=status_code,
    )


async def _payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    if not body:
        return {}
    if "application/json" in content_type:
        decoded = json.loads(body)
        return decoded if isinstance(decoded, dict) else {}
    if "application/x-www-form-urlencoded" in content_type:
        return dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True))
    return {}


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


def _telegram_result(row: object) -> JSONResponse:
    response = getattr(row, "response_payload_json", None) or {}
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict):
        result = {"message_id": getattr(row, "telegram_message_id", None)}
    return JSONResponse({"ok": True, "result": result})


def _telegram_send_error(row: object) -> JSONResponse:
    code_value = getattr(row, "error_code", None) or "400"
    try:
        code = int(code_value)
    except ValueError:
        code = 400
    if code < 400 or code > 599:
        code = 400
    return _telegram_error(code, getattr(row, "error_message", None) or "Telegram request failed")


async def _stored_bot(token: str, session: AsyncSession) -> object | None:
    bot = await BotRepository(session).get_by_token(token)
    if bot is None or not bot.is_active:
        return None
    return bot


@router.post("/bot{token}/getMe")
async def telegram_get_me(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    bot = await _stored_bot(token, session)
    if bot is None:
        return _telegram_error(401, "Unauthorized")
    return JSONResponse(
        {
            "ok": True,
            "result": {
                "id": bot.telegram_bot_id,
                "is_bot": True,
                "first_name": bot.name,
                "username": bot.username,
            },
        }
    )


@router.post("/bot{token}/sendMessage")
async def telegram_send_message(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    bot = await _stored_bot(token, session)
    if bot is None:
        return _telegram_error(401, "Unauthorized")
    payload = await _payload(request)
    service = create_send_service(session, request)
    try:
        row = await service.send_text(
            bot_id=bot.id,
            chat_id=str(payload.get("chat_id") or ""),
            text=str(payload.get("text") or ""),
            parse_mode=payload.get("parse_mode"),
            disable_web_page_preview=_optional_bool(payload.get("disable_web_page_preview")),
            message_thread_id=_optional_int(payload.get("message_thread_id")),
        )
    except SendServiceError as exc:
        return _telegram_error(400, str(exc))
    if row.status == "failed":
        return _telegram_send_error(row)
    return _telegram_result(row)


async def _send_media_reference(
    token: str,
    request: Request,
    session: AsyncSession,
    media_type: str,
    field_name: str,
) -> JSONResponse:
    bot = await _stored_bot(token, session)
    if bot is None:
        return _telegram_error(401, "Unauthorized")
    payload = await _payload(request)
    reference = payload.get(field_name)
    if not reference:
        return _telegram_error(400, f"{field_name} is required")
    service: SendService = create_send_service(session, request)
    try:
        row = await service.send_media_reference(
            bot_id=bot.id,
            media_type=media_type,
            file_reference=str(reference),
            chat_id=str(payload.get("chat_id") or ""),
            caption=payload.get("caption"),
            parse_mode=payload.get("parse_mode"),
            message_thread_id=_optional_int(payload.get("message_thread_id")),
        )
    except SendServiceError as exc:
        return _telegram_error(400, str(exc))
    if row.status == "failed":
        return _telegram_send_error(row)
    return _telegram_result(row)


@router.post("/bot{token}/sendDocument")
async def telegram_send_document(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    return await _send_media_reference(token, request, session, "document", "document")


@router.post("/bot{token}/sendVideo")
async def telegram_send_video(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    return await _send_media_reference(token, request, session, "video", "video")
