from tg_bot_aggregator.diagnostics.formatter import (
    build_copy_keyboard,
    chunk_report,
    format_update_report,
)


def test_format_update_report_includes_forum_thread_and_copy_ids() -> None:
    update = {
        "update_id": 10,
        "message": {
            "message_id": 55,
            "message_thread_id": 42,
            "is_topic_message": True,
            "date": 1_700_000_000,
            "chat": {"id": -100123, "type": "supergroup", "title": "Ops"},
            "from": {"id": 777, "is_bot": False, "username": "alice", "first_name": "Alice"},
            "text": "hello topic",
        },
    }

    report = format_update_report(update)

    assert "update_id: 10" in report.text
    assert "message_id: 55" in report.text
    assert "message_thread_id: 42" in report.text
    assert "is_topic_message: true" in report.text
    assert "chat_id: -100123" in report.text
    assert "sender_id: 777" in report.text
    assert report.reply_chat_id == "-100123"
    assert report.reply_message_thread_id == 42
    assert ("Thread ID", "42") in report.identifiers


def test_format_update_report_summarizes_forward_reply_and_media() -> None:
    update = {
        "update_id": 11,
        "message": {
            "message_id": 56,
            "date": 1_700_000_001,
            "chat": {"id": 123, "type": "private", "username": "bob"},
            "from": {"id": 123, "is_bot": False, "first_name": "Bob"},
            "forward_origin": {
                "type": "channel",
                "chat": {"id": -100555, "type": "channel", "title": "News"},
                "message_id": 900,
            },
            "reply_to_message": {
                "message_id": 44,
                "from": {"id": 321, "first_name": "Carol"},
                "message_thread_id": 41,
            },
            "document": {
                "file_id": "doc-file",
                "file_unique_id": "doc-unique",
                "file_name": "report.pdf",
                "mime_type": "application/pdf",
                "file_size": 12345,
            },
            "caption": "forwarded doc",
        },
    }

    report = format_update_report(update)

    assert "Forward origin" in report.text
    assert "origin_type: channel" in report.text
    assert "source_chat_id: -100555" in report.text
    assert "source_message_id: 900" in report.text
    assert "Reply" in report.text
    assert "reply_message_id: 44" in report.text
    assert "reply_thread_id: 41" in report.text
    assert "document_file_id: doc-file" in report.text
    assert ("File ID", "doc-file") in report.identifiers


def test_build_copy_keyboard_uses_copy_text_buttons() -> None:
    keyboard = build_copy_keyboard(
        [
            ("Chat ID", "-100123"),
            ("Message ID", "55"),
            ("Message ID", "55"),
        ]
    )

    assert keyboard == {
        "inline_keyboard": [
            [
                {"text": "Copy Chat ID", "copy_text": {"text": "-100123"}},
                {"text": "Copy Message ID", "copy_text": {"text": "55"}},
            ]
        ]
    }


def test_chunk_report_keeps_messages_below_limit() -> None:
    chunks = chunk_report("a" * 25, limit=10)

    assert chunks == ["aaaaaaaaaa", "aaaaaaaaaa", "aaaaa"]
