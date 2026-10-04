"""Telegram control for the owner: the bot runs on the lab box and drives the CLI.

Each command is validated, mapped to a `job-agent` invocation, run as a subprocess (LLM
commands through scripts/with_ollama.sh) and its output is sent back. Only the configured
chat id is obeyed; everyone else gets a polite refusal.
"""

from __future__ import annotations

import asyncio
import html
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from job_agent.settings import Settings

COMMANDS: list[tuple[str, str]] = [
    ("status", "GPU, running and scheduled runs, last run"),
    ("now", "Start a run now · /now or /now 25"),
    ("schedule", "Daily run at an hour · /schedule 3 or /schedule 3 once"),
    ("unschedule", "Remove all scheduled runs"),
    ("logs", "End of the latest run log"),
    ("top", "Best jobs · /top or /top 20"),
    ("show", "Everything about one job · /show <id>"),
    ("stats", "Run metrics"),
    ("ask", "🤖 Ask your job database · /ask remote AI jobs above 20 LPA?"),
    ("pitch", "🤖 Founder message + cover note · /pitch <id>"),
    ("prep", "🤖 Interview prep · /prep <id>"),
    ("tailor", "🤖 Resume tailoring · /tailor <id>"),
    ("help", "What I can do"),
]
LLM_COMMANDS = {"ask", "pitch", "prep", "tailor"}
TIMEOUT_S = {"llm": 30 * 60, "default": 3 * 60}
MAX_MESSAGE = 3900  # Telegram's limit is 4096 incl. markup
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
JOB_ID = re.compile(r"^\d{1,10}$")


class BadCommand(ValueError):
    pass


@dataclass(frozen=True)
class Invocation:
    args: list[str]  # arguments for `job-agent`
    llm: bool = False

    @property
    def timeout(self) -> int:
        return TIMEOUT_S["llm" if self.llm else "default"]


def parse(command: str, words: list[str]) -> Invocation:
    """Validate a Telegram command and turn it into CLI arguments. Never builds a shell string."""
    if command in {"status", "unschedule", "logs", "stats"}:
        return Invocation([command])
    if command == "now":
        if not words:
            return Invocation(["now"])
        if len(words) == 1 and words[0].isdigit():
            return Invocation(["now", "--limit", words[0]])
        raise BadCommand("Usage: /now or /now 25 (a job limit for a quick run)")
    if command == "schedule":
        if (
            words
            and words[0].isdigit()
            and 0 <= int(words[0]) <= 23
            and words[1:] in ([], ["once"])
        ):
            return Invocation(["schedule", words[0], *(["--once"] if words[1:] else [])])
        raise BadCommand("Usage: /schedule 3 (daily at 03:00) or /schedule 3 once")
    if command == "top":
        if not words:
            return Invocation(["top"])
        if len(words) == 1 and words[0].isdigit():
            return Invocation(["top", "-n", words[0]])
        raise BadCommand("Usage: /top or /top 20")
    if command in {"show", "pitch", "prep", "tailor"}:
        if len(words) == 1 and JOB_ID.match(words[0]):
            return Invocation([command, words[0]], llm=command in LLM_COMMANDS)
        raise BadCommand(f"Usage: /{command} <job id> (ids are in /top)")
    if command == "ask":
        question = " ".join(words).strip()
        if not question:
            raise BadCommand("Usage: /ask which remote AI jobs pay above 20 LPA?")
        return Invocation(["ask", question], llm=True)
    raise BadCommand("Unknown command. Try /help")


def chunks(text: str, size: int = MAX_MESSAGE) -> list[str]:
    """Split on line boundaries into Telegram-sized pieces."""
    out, current = [], ""
    for line in text.splitlines() or [""]:
        while len(line) > size:
            out.append(line[:size])
            line = line[size:]
        if len(current) + len(line) + 1 > size:
            out.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        out.append(current)
    return out or ["(no output)"]


def help_text() -> str:
    lines = ["<b>Job-Search-Agent</b> · commands", ""]
    lines += [f"/{name} — {html.escape(desc)}" for name, desc in COMMANDS]
    lines += ["", "🤖 = uses the GPU; refused politely while it's busy."]
    return "\n".join(lines)


async def run_cli(inv: Invocation, root: Path) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "job_agent.cli", *inv.args]
    if inv.llm:
        cmd = [str(root / "scripts" / "with_ollama.sh"), *cmd]
    env = {**os.environ, "COLUMNS": "64", "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=root, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), inv.timeout)
    except TimeoutError:
        proc.kill()
        return 124, f"Timed out after {inv.timeout // 60} min."
    return proc.returncode or 0, ANSI.sub("", out.decode("utf-8", errors="replace")).strip()


def build_app(settings: Settings, root: Path) -> Application:
    token, owner = settings.secrets.telegram_bot_token, settings.secrets.telegram_chat_id
    if not token or not owner:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing in .env")

    def is_owner(update: Update) -> bool:
        return update.effective_chat is not None and str(update.effective_chat.id) == str(owner)

    async def on_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not is_owner(update):
            await update.effective_message.reply_text("This bot is private for now. 🙂")
            return
        await update.effective_message.reply_text(help_text(), parse_mode=ParseMode.HTML)

    async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        if not is_owner(update):
            await msg.reply_text("This bot is private for now. 🙂")
            return
        command = msg.text.split()[0].lstrip("/").split("@")[0].lower()
        try:
            inv = parse(command, context.args or [])
        except BadCommand as exc:
            await msg.reply_text(str(exc))
            return
        if inv.llm:
            await msg.reply_text("⏳ On it. This uses the GPU, so it can take a minute or two.")
        code, output = await run_cli(inv, root)
        prefix = "" if code == 0 else f"⚠️ exit {code}\n"
        for piece in chunks(prefix + output):
            await msg.reply_text(f"<pre>{html.escape(piece)}</pre>", parse_mode=ParseMode.HTML)

    async def post_init(app: Application) -> None:
        await app.bot.set_my_commands([BotCommand(n, d[:256]) for n, d in COMMANDS])

    app = Application.builder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler(["help", "start"], on_help))
    app.add_handler(CommandHandler([n for n, _ in COMMANDS if n != "help"], on_command))
    return app
