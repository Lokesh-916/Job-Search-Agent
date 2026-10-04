"""Minimal Telegram Bot API client for sending to many chats (used by cron delivery)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(RuntimeError):
    pass


class Sender:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self.token = token
        self.client = client or httpx.Client(timeout=60)

    def _call(self, method: str, **kwargs) -> dict:
        resp = self.client.post(API.format(token=self.token, method=method), **kwargs)
        body = resp.json()
        if not body.get("ok"):  # never include the URL: it contains the token
            raise TelegramError(f"{method}: {body.get('description', resp.status_code)}")
        return body["result"]

    def message(self, chat_id: int | str, text: str,
                buttons: list[list[tuple[str, str]]] | None = None) -> None:  # fmt: skip
        data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": "true"}  # fmt: skip
        if buttons:
            keyboard = [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]
            data["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
        self._call("sendMessage", data=data)

    def document(self, chat_id: int | str, path: Path, caption: str = "") -> None:
        with path.open("rb") as fh:
            self._call("sendDocument", data={"chat_id": chat_id, "caption": caption},
                       files={"document": (path.name, fh)})  # fmt: skip

    def broadcast(self, chat_ids: list[int], text: str, path: Path | None = None,
                  pause_s: float = 0.05) -> dict[int, str]:  # fmt: skip
        """Send to many chats; returns {chat_id: error} for the ones that failed."""
        failed = {}
        for chat_id in chat_ids:
            try:
                self.message(chat_id, text)
                if path:
                    self.document(chat_id, path)
            except (TelegramError, httpx.HTTPError) as exc:
                failed[chat_id] = str(exc)[:200]
            time.sleep(pause_s)  # stay far below Telegram's ~30 msg/s limit
        return failed
