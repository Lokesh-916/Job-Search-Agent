"""The batch's placement-feed bot: registration with approval, the daily feed, suggestions.

Users:  /start · /join <roll no> · /today · /jobs · /internships · /events · /suggest · /forget
Admin (the owner's chat id): /users · /pending · /broadcast · /suggestions · /sendnow · /refresh
"""

from __future__ import annotations

import asyncio
import html
import re
from datetime import date

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from job_agent.community.digest import distinct, event_line, job_line, upcoming
from job_agent.community.service import (
    current,
    db_path,
    deliver,
    latest_workbook,
    load_roster,
    refresh_and_build,
    todays_digest,
)
from job_agent.community.store import CommunityStore
from job_agent.settings import Settings

ROLL = re.compile(r"^[A-Za-z0-9]{5,15}$")
CONSENT = (
    "This bot sends one message a day with <b>tech jobs, paid internships, hackathons and tech "
    "events in India</b>, plus a sheet with the full list.\n\n"
    "To manage access it stores your Telegram name, username and roll number, nothing else. "
    "Send /forget any time to delete it.\n\n"
    "To join, send: <code>/join YOUR_ROLL_NUMBER</code>"
)
USER_COMMANDS = [
    ("today", "Today's feed + full sheet"),
    ("jobs", "Latest jobs"),
    ("internships", "Paid internships"),
    ("events", "Hackathons and tech events"),
    ("suggest", "Send a suggestion · /suggest add Zoho jobs"),
    ("forget", "Delete my data and leave"),
    ("help", "What I can do"),
]
ADMIN_HELP = (
    "<b>Admin</b>\n/users — everyone and their status\n/pending — approve or reject requests\n"
    "/broadcast &lt;text&gt; — message all approved members\n/suggestions — latest suggestions\n"
    "/refresh — fetch all sources now (1–2 min)\n/sendnow — send today's feed to everyone"
)


def help_text(is_admin: bool) -> str:
    lines = ["<b>Placement Feed</b>", ""] + [f"/{c} — {html.escape(d)}" for c, d in USER_COMMANDS]
    return "\n".join(lines) + ("\n\n" + ADMIN_HELP if is_admin else "")


def build_app(settings: Settings) -> Application:
    token, owner = settings.secrets.community_bot_token, settings.secrets.telegram_chat_id
    if not token or not owner:
        raise RuntimeError("COMMUNITY_BOT_TOKEN / TELEGRAM_CHAT_ID missing in .env")
    owner_id = int(owner)
    store = CommunityStore(db_path(settings))

    def is_admin(update: Update) -> bool:
        return update.effective_user is not None and update.effective_user.id == owner_id

    def member(update: Update) -> bool:
        if is_admin(update):
            return True
        u = store.user(update.effective_user.id)
        if u and u["status"] == "approved":
            store.touch(u["telegram_id"])
            return True
        return False

    async def reply(update: Update, text: str, **kw) -> None:
        await update.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, **kw
        )

    async def need_member(update: Update) -> bool:
        if member(update):
            return True
        u = store.user(update.effective_user.id)
        await reply(update, "⏳ Your request is waiting for approval." if u and
                    u["status"] == "pending" else CONSENT)  # fmt: skip
        return False

    # --- registration -------------------------------------------------------------------
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if member(update):
            await reply(update, "👋 Welcome back!\n\n" + help_text(is_admin(update)))
        else:
            await need_member(update)

    async def join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if member(update):
            await reply(update, "You're already in. Try /today")
            return
        roll = (context.args or [""])[0].strip().upper()
        if not ROLL.match(roll):
            await reply(update, "Send it like this: <code>/join 123AD0001</code>")
            return
        roster = load_roster()
        allowed = roll in roster if roster else settings.community.roll_allowed(roll)
        if not allowed:
            await reply(update, "That roll number isn't part of this batch. Check it, or message "
                                "the placement coordinator.")  # fmt: skip
            return
        name = roster.get(roll) or user.full_name
        store.register(user.id, name, user.username, roll)
        await reply(update, "✅ Request sent. You'll get a message once it's approved.")
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject:{user.id}"),
        ]])  # fmt: skip
        handle = f" (@{user.username})" if user.username else ""
        roster_note = "on the roster" if roster else "valid batch roll number"
        await context.bot.send_message(
            owner_id, f"🙋 Join request: <b>{html.escape(name)}</b>{html.escape(handle)}\n"
                      f"Roll: <code>{roll}</code> · {roster_note}",
            parse_mode=ParseMode.HTML, reply_markup=buttons,
        )  # fmt: skip

    async def decide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not is_admin(update):
            await query.answer("Only the coordinator can do that.")
            return
        action, _, uid = (query.data or "").partition(":")
        if action not in ("approve", "reject") or not uid.isdigit():
            await query.answer()
            return
        target = store.user(int(uid))
        if target is None:
            await query.answer("That request no longer exists.")
            return
        store.set_status(int(uid), "approved" if action == "approve" else "rejected")
        await query.answer("Done")
        verdict = "✅ approved" if action == "approve" else "❌ rejected"
        await query.edit_message_text(
            f"{html.escape(target['name'])} ({target['roll_no']}) {verdict}",
            parse_mode=ParseMode.HTML,
        )
        if action == "approve":
            await context.bot.send_message(
                int(uid),
                "🎉 You're in! The feed arrives every morning.\n\n" + help_text(False),
                parse_mode=ParseMode.HTML,
            )

    async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        store.forget(update.effective_user.id)
        await reply(update, "🗑️ Done. Everything about you is deleted. /start to rejoin later.")

    # --- feed ---------------------------------------------------------------------------
    async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await need_member(update):
            return
        await reply(update, todays_digest(store))
        if path := latest_workbook(store):
            await update.effective_message.reply_document(path.open("rb"), filename=path.name)

    async def listing(update: Update, kind: str) -> None:
        if not await need_member(update):
            return
        jobs, interns, events = current(store)
        jobs, interns = distinct(jobs), distinct(interns)
        if kind == "jobs":
            lines = [job_line(r) for r in jobs[:12]]
            title = f"💼 <b>Jobs</b> · {len(jobs)} open, newest and best-known first"
        elif kind == "internships":
            lines = [job_line(r, "pay") for r in interns[:12]]
            title = f"🎓 <b>Paid internships</b> · {len(interns)} open"
        else:
            soon = upcoming(events, date.today().isoformat())
            lines = [event_line(e) for e in soon[:12]]
            title = f"🏆 <b>Hackathons & events</b> · {len(events)} upcoming"
        await reply(update, "\n".join([title, "", *(lines or ["Nothing yet today."]),
                                       "", "Full list: /today"])[:4000])  # fmt: skip

    async def jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await listing(update, "jobs")

    async def internships(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await listing(update, "internships")

    async def events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await listing(update, "events")

    async def suggest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await need_member(update):
            return
        text = " ".join(context.args or []).strip()
        if not text:
            example = "<code>/suggest please add Zoho and Razorpay jobs</code>"
            await reply(update, f"Write it after the command, e.g. {example}")
            return
        user = update.effective_user
        store.suggest(user.id, text[:1000])
        await reply(update, "🙏 Thanks! Your suggestion reached the coordinator.")
        u = store.user(user.id)
        who = f"{u['name']} ({u['roll_no']})" if u else user.full_name
        await context.bot.send_message(owner_id, f"💡 <b>Suggestion</b> from {html.escape(who)}:\n"
                                                 f"{html.escape(text[:1000])}",
                                       parse_mode=ParseMode.HTML)  # fmt: skip

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await need_member(update):
            await reply(update, help_text(is_admin(update)))

    # --- admin --------------------------------------------------------------------------
    def admin_only(fn):
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if is_admin(update):
                await fn(update, context)

        return wrapped

    @admin_only
    async def users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        rows = store.users()
        counts = {
            s: sum(r["status"] == s for r in rows) for s in ("approved", "pending", "rejected")
        }
        lines = [f"👥 <b>{counts['approved']}</b> members · {counts['pending']} pending · "
                 f"{counts['rejected']} rejected", ""]  # fmt: skip
        icon = {"approved": "✅", "pending": "⏳", "rejected": "❌"}
        for r in rows:
            seen = (r["last_active"] or r["joined_at"])[:10]
            handle = f" @{r['username']}" if r["username"] else ""
            lines.append(f"{icon.get(r['status'], '•')} {html.escape(r['name'] or '?')}"
                         f"{html.escape(handle)} · {r['roll_no']} · active {seen} · "
                         f"{r['digests']} feeds")  # fmt: skip
        await reply(update, "\n".join(lines)[:4000])

    @admin_only
    async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        rows = store.users("pending")
        if not rows:
            await reply(update, "No pending requests.")
        for r in rows:
            buttons = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{r['telegram_id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{r['telegram_id']}"),
            ]])  # fmt: skip
            await reply(update, f"{html.escape(r['name'] or '?')} · {r['roll_no']}",
                        reply_markup=buttons)  # fmt: skip

    @admin_only
    async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = (update.effective_message.text or "").partition(" ")[2].strip()
        if not text:
            await reply(update, "Usage: /broadcast your message")
            return
        sent = 0
        for r in store.users("approved"):
            try:
                await context.bot.send_message(r["telegram_id"], f"📢 {html.escape(text)}",
                                               parse_mode=ParseMode.HTML)  # fmt: skip
                sent += 1
            except Exception:  # a member who blocked the bot shouldn't stop the rest
                pass
            await asyncio.sleep(0.05)
        await reply(update, f"Sent to {sent} member(s).")

    @admin_only
    async def suggestions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        rows = store.suggestions()
        lines = [f"• {html.escape(r['name'] or '?')} ({r['created_at'][:10]}): "
                 f"{html.escape(r['text'])}" for r in rows]  # fmt: skip
        await reply(
            update, "\n".join(["💡 <b>Suggestions</b>", "", *(lines or ["None yet."])])[:4000]
        )

    @admin_only
    async def refresh_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, "⏳ Fetching every source…")
        stats, path = await asyncio.to_thread(refresh_and_build, settings, store)
        await reply(update, f"Done: {stats.kept['job']} jobs, {stats.kept['internship']} "
                            f"internships, {stats.events} events · new today: "
                            f"{stats.new['job']} jobs, {stats.new['internship']} internships · "
                            f"source errors: {len(stats.errors)}")  # fmt: skip

    @admin_only
    async def sendnow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        sent, failed = await asyncio.to_thread(deliver, settings, store)
        await reply(update, f"Sent to {sent} member(s); {len(failed)} failed.")

    async def post_init(app: Application) -> None:
        await app.bot.set_my_commands([BotCommand(c, d) for c, d in USER_COMMANDS])

    app = Application.builder().token(token).post_init(post_init).build()
    for name, fn in [("start", start), ("join", join), ("forget", forget), ("today", today),
                     ("jobs", jobs), ("internships", internships), ("events", events),
                     ("suggest", suggest), ("help", help_cmd), ("users", users),
                     ("pending", pending), ("broadcast", broadcast),
                     ("suggestions", suggestions), ("refresh", refresh_cmd),
                     ("sendnow", sendnow)]:  # fmt: skip
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(decide))
    return app
