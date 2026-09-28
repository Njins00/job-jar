import os
import re
import json
import uuid
import logging
import requests
from datetime import datetime
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlparse
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

load_dotenv()

BOT_TOKEN  = os.getenv("BOT_TOKEN")
ALLOWED_ID = int(os.getenv("ALLOWED_USER_ID"))
DATA_FILE  = os.getenv("DATA_FILE", "jobs.json")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
DASH_URL   = os.getenv("DASHBOARD_URL", "http://192.168.2.28:5000")

MAX_FILE_MB = 10

WAIT_RESUME, WAIT_COVER = range(2)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

Path(UPLOAD_DIR).mkdir(exist_ok=True)


# --- security helpers ---

def is_safe_url(url: str) -> bool:
    # only allow public http/https urls, block internal network
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False
        host = p.hostname or ""
        blocked = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
        if host in blocked:
            return False
        if host.startswith(("192.168.", "10.", "172.16.", "172.17.",
                             "172.18.", "172.19.", "172.20.", "172.21.",
                             "172.22.", "172.23.", "172.24.", "172.25.",
                             "172.26.", "172.27.", "172.28.", "172.29.",
                             "172.30.", "172.31.")):
            return False
        return True
    except Exception:
        return False


def safe_filename(name: str) -> str:
    # basename only — strip any path traversal attempts
    name = Path(name).name
    name = re.sub(r"[^\w\-.]", "_", name)
    return name[:100]


# --- title scraper ---

class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def fetch_title(url: str) -> str:
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        p = TitleParser()
        p.feed(r.text[:8000])
        return p.title.strip() or url
    except Exception:
        return url


# --- storage ---

def load_jobs() -> dict:
    if not Path(DATA_FILE).exists():
        return {}
    with open(DATA_FILE) as f:
        return json.load(f)


def save_jobs(jobs: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(jobs, f, indent=2)


def add_job(url: str, title: str, chat_id: int, message_id: int) -> str:
    jobs = load_jobs()
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id":             job_id,
        "url":            url,
        "title":          title,
        "status":         "pending",
        "added":          datetime.now().isoformat(),
        "applied_date":   None,
        "resume":         None,
        "cover_letter":   None,
        "chat_id":        chat_id,
        "message_id":     message_id,
        "reminder_count": 0,
    }
    save_jobs(jobs)
    return job_id


def update_job(job_id: str, **kwargs):
    jobs = load_jobs()
    if job_id in jobs:
        jobs[job_id].update(kwargs)
        save_jobs(jobs)


# --- keyboard builders ---

def pending_kb(job_id: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Already Applied", callback_data=f"applied:{job_id}"),
        InlineKeyboardButton("🌐 Open Job",        url=url),
        InlineKeyboardButton("❌ Don't Apply",     callback_data=f"skip:{job_id}"),
    ]])


def done_kb(job_id: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📋 View Application", url=f"{DASH_URL}/job/{job_id}"),
        InlineKeyboardButton("🌐 View Job",         url=url),
    ]])


def skipped_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🌐 View Job", url=url),
    ]])


# --- message text ---

def pending_text(title: str, url: str, reminder: int = 0) -> str:
    badge = f"⏰ Reminder #{reminder} — " if reminder > 0 else ""
    return f"{badge}💼 *{title}*\n{url}"


def applied_text(title: str) -> str:
    return f"✅ *{title}*"


def skipped_text(title: str) -> str:
    return f"❌ *{title}*"


# --- auth ---

def is_allowed(update: Update) -> bool:
    return update.effective_user.id == ALLOWED_ID


# --- url handler ---

async def handle_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    url = update.message.text.strip()

    # block internal network URLs
    if not is_safe_url(url):
        await update.message.reply_text("⚠️ That URL isn't allowed.")
        return

    msg = await update.message.reply_text("🔍 Fetching...")

    title = fetch_title(url)
    job_id = add_job(url, title, update.effective_chat.id, msg.message_id)

    await msg.edit_text(
        pending_text(title, url),
        reply_markup=pending_kb(job_id, url),
        parse_mode="Markdown",
        link_preview_options=LinkPreviewOptions(url=url),
    )

    # delete user's original message — keep chat to one message per job
    try:
        await update.message.delete()
    except Exception:
        pass  # fine if can't delete (e.g. forwarded messages)


# --- callback handler ---

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, job_id = query.data.split(":", 1)
    jobs = load_jobs()

    if job_id not in jobs:
        await query.edit_message_text("⚠️ Job not found.")
        return

    job = jobs[job_id]

    if action == "skip":
        update_job(job_id, status="skipped")
        await query.edit_message_text(
            skipped_text(job["title"]),
            reply_markup=skipped_kb(job["url"]),
            parse_mode="Markdown",
        )

    elif action == "applied":
        ctx.user_data["applying_job"] = job_id
        await query.message.reply_text(
            f"📎 Resume for *{job['title']}*\n\nSend a file or /skip",
            parse_mode="Markdown",
        )
        return WAIT_RESUME


# --- apply conversation ---

async def receive_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    job_id = ctx.user_data.get("applying_job")
    if not job_id:
        return ConversationHandler.END

    if update.message.document:
        doc = update.message.document
        # file size check
        if doc.file_size > MAX_FILE_MB * 1024 * 1024:
            await update.message.reply_text(f"❌ File too large (max {MAX_FILE_MB}MB). Send another or /skip")
            return WAIT_RESUME
        file = await doc.get_file()
        fname = f"{job_id}_resume_{safe_filename(doc.file_name)}"
        path = str(Path(UPLOAD_DIR) / fname)
        await file.download_to_drive(path)
        update_job(job_id, resume=path)

    await update.message.reply_text("📝 Cover letter? Send a file or /skip")
    return WAIT_COVER


async def skip_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("📝 Cover letter? Send a file or /skip")
    return WAIT_COVER


async def receive_cover(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    return await _finish_apply(update, ctx, update.message.document)


async def skip_cover(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    return await _finish_apply(update, ctx, None)


async def _finish_apply(update, ctx, document):
    job_id = ctx.user_data.pop("applying_job", None)
    if not job_id:
        return ConversationHandler.END

    jobs = load_jobs()
    job = jobs.get(job_id, {})

    if document:
        if document.file_size > MAX_FILE_MB * 1024 * 1024:
            await update.message.reply_text(f"❌ File too large (max {MAX_FILE_MB}MB). Skipping cover letter.")
        else:
            file = await document.get_file()
            fname = f"{job_id}_cover_{safe_filename(document.file_name)}"
            path = str(Path(UPLOAD_DIR) / fname)
            await file.download_to_drive(path)
            update_job(job_id, cover_letter=path)

    update_job(job_id, status="applied", applied_date=datetime.now().isoformat())

    await update.message.delete()

    try:
        await ctx.bot.edit_message_text(
            chat_id=job["chat_id"],
            message_id=job["message_id"],
            text=applied_text(job["title"]),
            reply_markup=done_kb(job_id, job["url"]),
            parse_mode="Markdown",
        )
    except Exception as e:
        log.warning(f"could not edit original message: {e}")

    return ConversationHandler.END


# --- commands ---

async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    jobs = load_jobs()
    pending = [j for j in jobs.values() if j["status"] == "pending"]
    if not pending:
        await update.message.reply_text("No pending jobs 🎉")
        return
    lines = [f"🟡 *{j['title']}*\n{j['url']}" for j in pending]
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    jobs = load_jobs()
    total   = len(jobs)
    pending = sum(1 for j in jobs.values() if j["status"] == "pending")
    applied = sum(1 for j in jobs.values() if j["status"] == "applied")
    skipped = sum(1 for j in jobs.values() if j["status"] == "skipped")
    await update.message.reply_text(
        f"📊 *Job Stats*\n\nTotal: {total}\n🟡 Pending: {pending}\n✅ Applied: {applied}\n❌ Skipped: {skipped}",
        parse_mode="Markdown",
    )


# --- 12hr reminder ---

async def send_reminders(app):
    jobs = load_jobs()
    for job in jobs.values():
        if job["status"] != "pending":
            continue
        count = job.get("reminder_count", 0) + 1
        update_job(job["id"], reminder_count=count)
        try:
            await app.bot.edit_message_text(
                chat_id=job["chat_id"],
                message_id=job["message_id"],
                text=pending_text(job["title"], job["url"], reminder=count),
                reply_markup=pending_kb(job["id"], job["url"]),
                parse_mode="Markdown",
                link_preview_options=LinkPreviewOptions(url=job["url"]),
            )
        except Exception as e:
            log.warning(f"reminder edit failed for {job['id']}: {e}")


# --- main ---

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern=r"^applied:")],
        states={
            WAIT_RESUME: [
                MessageHandler(filters.Document.ALL, receive_resume),
                CommandHandler("skip", skip_resume),
            ],
            WAIT_COVER: [
                MessageHandler(filters.Document.ALL, receive_cover),
                CommandHandler("skip", skip_cover),
            ],
        },
        fallbacks=[],
        per_user=True,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^skip:"))
    app.add_handler(CommandHandler("list",  cmd_list))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"https?://"), handle_url))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders, "interval", hours=12, args=[app])
    scheduler.start()

    log.info("job-jar bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
