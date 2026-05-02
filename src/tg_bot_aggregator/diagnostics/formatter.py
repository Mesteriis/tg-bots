from dataclasses import dataclass
from typing import Any

Identifier = tuple[str, str]

MESSAGE_UPDATE_KEYS = ("message", "edited_message", "channel_post", "edited_channel_post")
SCALAR_TYPES = (str, int, float, bool)
KNOWN_MESSAGE_KEYS = {
    "message_id",
    "message_thread_id",
    "is_topic_message",
    "date",
    "chat",
    "from",
    "sender_chat",
    "text",
    "caption",
    "forward_origin",
    "reply_to_message",
    "document",
    "photo",
    "video",
    "animation",
    "audio",
    "voice",
    "sticker",
    "video_note",
    "contact",
    "location",
    "poll",
    "dice",
    "entities",
    "caption_entities",
}


@dataclass(frozen=True)
class DiagnosticReport:
    text: str
    identifiers: list[Identifier]
    reply_chat_id: str | None
    reply_message_thread_id: int | None


def _message_from_update(update: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    for key in MESSAGE_UPDATE_KEYS:
        value = update.get(key)
        if isinstance(value, dict):
            return key, value
    return "unsupported", None


def _bool_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "-"


def _value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _line(lines: list[str], key: str, value: Any) -> None:
    if value is not None:
        lines.append(f"{key}: {_value(value)}")


def _add_identifier(identifiers: list[Identifier], label: str, value: Any) -> None:
    if value is None:
        return
    text = str(value)
    if 1 <= len(text) <= 256:
        identifiers.append((label, text))


def _format_user(lines: list[str], prefix: str, user: dict[str, Any] | None) -> None:
    if not user:
        return
    _line(lines, f"{prefix}_id", user.get("id"))
    _line(lines, f"{prefix}_username", user.get("username"))
    _line(lines, f"{prefix}_first_name", user.get("first_name"))
    _line(lines, f"{prefix}_last_name", user.get("last_name"))
    _line(lines, f"{prefix}_is_bot", user.get("is_bot"))


def _format_forward(
    lines: list[str],
    identifiers: list[Identifier],
    message: dict[str, Any],
) -> None:
    origin = message.get("forward_origin")
    if not isinstance(origin, dict):
        return
    lines.append("")
    lines.append("Forward origin")
    _line(lines, "origin_type", origin.get("type"))
    chat = origin.get("chat")
    if isinstance(chat, dict):
        _line(lines, "source_chat_id", chat.get("id"))
        _line(lines, "source_chat_type", chat.get("type"))
        _line(lines, "source_chat_title", chat.get("title"))
        _line(lines, "source_chat_username", chat.get("username"))
        _add_identifier(identifiers, "Forward Chat ID", chat.get("id"))
    sender_user = origin.get("sender_user")
    if isinstance(sender_user, dict):
        _format_user(lines, "source_user", sender_user)
        _add_identifier(identifiers, "Forward User ID", sender_user.get("id"))
    _line(lines, "source_message_id", origin.get("message_id"))
    _line(lines, "sender_user_name", origin.get("sender_user_name"))
    _line(lines, "author_signature", origin.get("author_signature"))
    _add_identifier(identifiers, "Forward Message ID", origin.get("message_id"))


def _format_reply(lines: list[str], identifiers: list[Identifier], message: dict[str, Any]) -> None:
    reply = message.get("reply_to_message")
    if not isinstance(reply, dict):
        return
    lines.append("")
    lines.append("Reply")
    _line(lines, "reply_message_id", reply.get("message_id"))
    _line(lines, "reply_thread_id", reply.get("message_thread_id"))
    user = reply.get("from")
    if isinstance(user, dict):
        _line(lines, "reply_sender_id", user.get("id"))
        _line(lines, "reply_sender_username", user.get("username"))
        _add_identifier(identifiers, "Reply Sender ID", user.get("id"))
    _add_identifier(identifiers, "Reply Message ID", reply.get("message_id"))
    _add_identifier(identifiers, "Reply Thread ID", reply.get("message_thread_id"))


def _format_media(lines: list[str], identifiers: list[Identifier], message: dict[str, Any]) -> None:
    media_fields = ("document", "video", "animation", "audio", "voice", "sticker", "video_note")
    for field in media_fields:
        media = message.get(field)
        if not isinstance(media, dict):
            continue
        lines.append("")
        lines.append("Media")
        file_id = media.get("file_id")
        _line(lines, f"{field}_file_id", file_id)
        _line(lines, f"{field}_file_unique_id", media.get("file_unique_id"))
        _line(lines, "file_name", media.get("file_name"))
        _line(lines, "mime_type", media.get("mime_type"))
        _line(lines, "file_size", media.get("file_size"))
        _add_identifier(identifiers, "File ID", file_id)
        return
    photo = message.get("photo")
    if isinstance(photo, list) and photo:
        largest = photo[-1]
        if isinstance(largest, dict):
            lines.append("")
            lines.append("Media")
            _line(lines, "photo_file_id", largest.get("file_id"))
            _line(lines, "photo_file_unique_id", largest.get("file_unique_id"))
            _line(lines, "width", largest.get("width"))
            _line(lines, "height", largest.get("height"))
            _line(lines, "file_size", largest.get("file_size"))
            _add_identifier(identifiers, "File ID", largest.get("file_id"))


def _format_other_fields(lines: list[str], message: dict[str, Any]) -> None:
    other = sorted(key for key in message if key not in KNOWN_MESSAGE_KEYS)
    if not other:
        return
    lines.append("")
    lines.append("Other fields")
    for key in other:
        value = message[key]
        if isinstance(value, SCALAR_TYPES) or value is None:
            _line(lines, key, value)
        elif isinstance(value, list):
            lines.append(f"{key}: list[{len(value)}]")
        elif isinstance(value, dict):
            lines.append(f"{key}: object[{len(value)}]")


def format_update_report(update: dict[str, Any]) -> DiagnosticReport:
    update_kind, message = _message_from_update(update)
    if message is None:
        text = (
            "Telegram diagnostic report\n\n"
            "Update\n"
            f"update_id: {update.get('update_id')}\n"
            "update_kind: unsupported"
        )
        return DiagnosticReport(
            text=text,
            identifiers=[],
            reply_chat_id=None,
            reply_message_thread_id=None,
        )

    identifiers: list[Identifier] = []
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    thread_id = message.get("message_thread_id")

    lines = ["Telegram diagnostic report", "", "Message"]
    _line(lines, "update_id", update.get("update_id"))
    _line(lines, "update_kind", update_kind)
    _line(lines, "message_id", message.get("message_id"))
    _line(lines, "date", message.get("date"))
    _line(lines, "text", message.get("text"))
    _line(lines, "caption", message.get("caption"))
    lines.append("")
    lines.append("Thread")
    _line(lines, "message_thread_id", thread_id)
    lines.append(f"is_topic_message: {_bool_text(message.get('is_topic_message'))}")
    lines.append("")
    lines.append("Chat")
    _line(lines, "chat_id", chat.get("id"))
    _line(lines, "chat_type", chat.get("type"))
    _line(lines, "chat_title", chat.get("title"))
    _line(lines, "chat_username", chat.get("username"))
    lines.append("")
    lines.append("Sender")
    _format_user(lines, "sender", sender)

    _add_identifier(identifiers, "Chat ID", chat.get("id"))
    _add_identifier(identifiers, "Message ID", message.get("message_id"))
    _add_identifier(identifiers, "Thread ID", thread_id)
    _add_identifier(identifiers, "Sender ID", sender.get("id"))

    _format_forward(lines, identifiers, message)
    _format_reply(lines, identifiers, message)
    _format_media(lines, identifiers, message)
    _format_other_fields(lines, message)

    reply_chat_id = str(chat["id"]) if chat.get("id") is not None else None
    reply_thread_id = thread_id if isinstance(thread_id, int) else None
    return DiagnosticReport(
        text="\n".join(lines),
        identifiers=identifiers,
        reply_chat_id=reply_chat_id,
        reply_message_thread_id=reply_thread_id,
    )


def build_copy_keyboard(identifiers: list[Identifier]) -> dict[str, Any] | None:
    buttons: list[dict[str, Any]] = []
    seen: set[Identifier] = set()
    for label, value in identifiers:
        item = (label, value)
        if item in seen:
            continue
        seen.add(item)
        buttons.append({"text": f"Copy {label}", "copy_text": {"text": value}})
    if not buttons:
        return None
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    return {"inline_keyboard": rows}


def chunk_report(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        chunks.append(remaining[:limit])
        remaining = remaining[limit:]
    return chunks
