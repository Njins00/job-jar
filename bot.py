import os
import json
import uuid
import logging
import requests
from datetime import datetime
from pathlib import Path
from html.parser import HTMLParser
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# config
BOT_TOKEN  = os.getenv("BOT_TOKEN")
ALLOWED_ID = int(os.getenv("ALLOWED_USER_ID"))
DATA_FILE  = os.getenv("DATA_FILE", "jobs.json")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
DASH_PORT  = int(os.getenv("DASHBOARD_PORT", 5000))

# conversation states
WAIT_RESUME, WAIT_COVER = range(2)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

Path(UPLOAD_DIR).mkdir(exist_ok=True)


# --- tiny title scraper ---

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
        p.feed(r.text[:8000])  # only parse first 8kb — fast enough for titles
        return p.title.strip() or url
    except Exception:
        return url


# --- job storage ---

def load_jobs() -> dict:
    if not Path(DATA_FILE).exists():
        return {}
    with open(DATA_FILE) as f:
        return json.load(f)


def save_jobs(jobs: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(jobs, f, indent=2)


def add_job(url: str, title: str) -> str:
    jobs = load_jobs()
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id": job_id,
        "url": url,
        "title": title,
        "status": "pending",
        "added": datetime.now().isoformat(),
        "applied_date": None,
        "resume": None,
        "cover_letter": None,
        "notes": None,
    }
    save_jobs(jobs)
    return job_id


def update_job(job_id: str, **kwargs):
    jobs = load_jobs()
    if job_id in jobs:
        jobs[job_id].update(kwargs)
        save_jobs(jobs)


# --- auth check ---

def is_allowed(update: Update) -> bool:
    return update.effective_user.id == ALLOWED_ID


# --- handlers ---

async def handle_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    url = update.message.text.strip()
    msg = await update.message.reply_text("🔍 Fetching job details...")

    title = fetch_title(url)
    job_id = add_job(url, title)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Apply",            callback_data=f"apply:{job_id}"),
            InlineKeyboardButton("❌ Skip",             callback_data=f"skip:{job_id}"),
            InlineKeyboardButton("✔️ Already Applied",  callback_data=f"done:{job_id}"),
        ]
    ])

    await msg.edit_text(
        f"💼 *{title}*\n{url}\n\n_What do you want to do?_",
        reply_markup=kb,
        parse_mode="Markdown",
    )


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
        await query.edit_message_text(f"❌ Skipped\n_{job['title']}_", parse_mode="Markdown")

    elif action == "done":
        update_job(job_id, status="applied", applied_date=datetime.now().isoformat())
        await query.edit_message_text(f"✔️ Marked as applied\n_{job['title']}_", parse_mode="Markdown")

    elif action == "apply":
        # store job_id so the next message handler knows which job
        ctx.user_data["applying_job"] = job_id
        await query.edit_message_text(
            f"📎 Send your resume for:\n*{job['title']}*\n\nSend a file or type /skip to skip.",
            parse_mode="Markdown",
        )
        return WAIT_RESUME


async def receive_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    job_id = ctx.user_data.get("applying_job")
    if not job_id:
        return ConversationHandler.END

    if update.message.document:
        file = await update.message.document.get_file()
        fname = f"{job_id}_resume_{update.message.document.file_name}"
        resume_path = str(Path(UPLOAD_DIR) / fname)
        await file.download_to_drive(resume_path)
        update_job(job_id, resume=resume_path)

    await update.message.reply_text(
        "📝 Cover letter? Send a file or type /skip to skip."
    )
    return WAIT_COVER


async def skip_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("📝 Cover letter? Send a file or type /skip to skip.")
    return WAIT_COVER


async def receive_cover(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    job_id = ctx.user_data.get("applying_job")
    jobs = load_jobs()
    job = jobs.get(job_id, {})

    if update.message.document:
        file = await update.message.document.get_file()
        fname = f"{job_id}_cover_{update.message.document.file_name}"
        cover_path = str(Path(UPLOAD_DIR) / fname)
        await file.download_to_drive(cover_path)
        update_job(job_id, cover_letter=cover_path)

    update_job(job_id, status="applied", applied_date=datetime.now().isoformat())

    await update.message.reply_text(
        f"✅ Applied!\n*{job.get('title', '')}*\n\nTracked in dashboard.",
        parse_mode="Markdown",
    )
    ctx.user_data.pop("applying_job", None)
    return ConversationHandler.END


async def skip_cover(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    job_id = ctx.user_data.get("applying_job")
    jobs = load_jobs()
    job = jobs.get(job_id, {})

    update_job(job_id, status="applied", applied_date=datetime.now().isoformat())

    await update.message.reply_text(
        f"✅ Applied!\n*{job.get('title', '')}*\n\nTracked in dashboard.",
        parse_mode="Markdown",
    )
    ctx.user_data.pop("applying_job", None)
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


async def cmd_applied(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    jobs = load_jobs()
    applied = [j for j in jobs.values() if j["status"] == "applied"]
    if not applied:
        await update.message.reply_text("No applications yet.")
        return
    lines = []
    for j in applied:
        date = j["applied_date"][:10] if j["applied_date"] else "unknown"
        lines.append(f"✅ *{j['title']}*\nApplied: {date}")
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
        f"📊 *Job Stats*\n\n"
        f"Total: {total}\n"
        f"🟡 Pending: {pending}\n"
        f"✅ Applied: {applied}\n"
        f"❌ Skipped: {skipped}",
        parse_mode="Markdown",
    )


# --- 12hr reminder ---

async def send_reminders(app):
    jobs = load_jobs()
    pending = [j for j in jobs.values() if j["status"] == "pending"]
    if not pending:
        return
    lines = [f"⏰ Still pending:\n*{j['title']}*\n{j['url']}" for j in pending]
    text = "🔔 *Pending job reminder*\n\n" + "\n\n".join(lines)
    await app.bot.send_message(chat_id=ALLOWED_ID, text=text, parse_mode="Markdown")


# --- main ---

def main():
    # uses Telegram's official API — no local bot API server needed
    app = Application.builder().token(BOT_TOKEN).build()

    # conversation for apply flow
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern=r"^apply:")],
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
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^(skip|done):"))
    app.add_handler(CommandHandler("list",    cmd_list))
    app.add_handler(CommandHandler("applied", cmd_applied))
    app.add_handler(CommandHandler("stats",   cmd_stats))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"https?://"), handle_url))

    # 12hr reminders
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders, "interval", hours=12, args=[app])
    scheduler.start()

    log.info("job-jar bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
