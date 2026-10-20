from __future__ import annotations

from src.telegram_client import TelegramDocument, _multipart_body, send_chart_documents


def test_multipart_includes_png_filename_and_fields() -> None:
    body, content_type = _multipart_body(
        {"chat_id": "123", "caption": "$NASI"},
        [("document", "nasi.png", b"\x89PNG", "image/png")],
    )
    assert "multipart/form-data; boundary=" in content_type
    text = body.decode("latin-1")
    assert 'name="chat_id"' in text
    assert "123" in text
    assert 'filename="nasi.png"' in text
    assert "image/png" in text
    assert "\x89PNG" in text


def test_send_chart_documents_uses_document_media_group(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_post(*, bot_token, method, fields, files, timeout=90):
        calls.append((method, fields))
        assert bot_token == "tok"
        assert files[0][1].endswith(".png")
        assert files[1][1].endswith(".png")

    monkeypatch.setattr("src.telegram_client._post_telegram_form", fake_post)

    class T:
        bot_token = "tok"
        chat_id = "42"

    send_chart_documents(
        telegram=T(),  # type: ignore[arg-type]
        documents=(
            TelegramDocument("nasi.png", b"aaa", "$NASI"),
            TelegramDocument("vix.png", b"bbb", "$VIX"),
        ),
    )
    assert calls[0][0] == "sendMediaGroup"
    media = calls[0][1]["media"]
    assert '"type": "document"' in media
    assert "$NASI" in media
    assert "$VIX" in media
    assert "sendPhoto" not in calls[0][0]
