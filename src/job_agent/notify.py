"""Telegram delivery: a short message plus the day's workbook."""

from __future__ import annotations

from pathlib import Path

import httpx

from job_agent.settings import Secrets

API = "https://api.telegram.org/bot{token}/{method}"


class NotifyError(RuntimeError):
    pass


class Telegram:
    def __init__(self, secrets: Secrets, client: httpx.Client | None = None):
        if not (secrets.telegram_bot_token and secrets.telegram_chat_id):
            raise NotifyError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing in .env")
        self.token = secrets.telegram_bot_token
        self.chat_id = secrets.telegram_chat_id
        self.client = client or httpx.Client(timeout=60)

    def _call(self, method: str, **kwargs) -> dict:
        resp = self.client.post(API.format(token=self.token, method=method), **kwargs)
        body = resp.json()
        if not body.get("ok"):
            # Never echo the URL: it contains the bot token.
            raise NotifyError(
                f"Telegram {method} failed: {body.get('description', resp.status_code)}"
            )
        return body["result"]

    def send_message(self, text: str) -> None:
        self._call(
            "sendMessage",
            data={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": "true"},
        )  # fmt: skip

    def send_document(self, path: Path, caption: str = "") -> None:
        with path.open("rb") as fh:
            self._call(
                "sendDocument",
                data={"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"document": (path.name, fh)},
            )
