import httpx
import pytest

from job_agent.notify import NotifyError, Telegram
from job_agent.settings import Secrets

SECRETS = Secrets(telegram_bot_token="T0KEN", telegram_chat_id="42")


def test_missing_secrets():
    with pytest.raises(NotifyError):
        Telegram(Secrets(telegram_bot_token=None, telegram_chat_id=None))


def test_send_message_posts_chat_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True, "result": {}})

    tg = Telegram(SECRETS, httpx.Client(transport=httpx.MockTransport(handler)))
    tg.send_message("hi")
    assert seen["path"].endswith("/sendMessage")
    assert "chat_id=42" in seen["body"]


def test_error_does_not_leak_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "chat not found"})

    tg = Telegram(SECRETS, httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(NotifyError) as exc:
        tg.send_message("hi")
    assert "T0KEN" not in str(exc.value)


def test_send_message_with_buttons():
    import json
    from urllib.parse import parse_qs

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"ok": True, "result": {}})

    tg = Telegram(SECRETS, httpx.Client(transport=httpx.MockTransport(handler)))
    tg.send_message("hi", buttons=[[("Pitch", "pitch:1"), ("Prep", "prep:1")]])
    markup = json.loads(seen["reply_markup"][0])
    assert markup["inline_keyboard"][0][1] == {"text": "Prep", "callback_data": "prep:1"}
