#!/usr/bin/env python3
"""
AI Content Curator Bot для @bazuevaconsalt
Расписание (время Бали UTC+8):
  09:00 — Утренний инсайт        (#мысливслух)
  11:00 вт/чт/сб — Полезняшка   (#полезняшка)
  14:00 — Практика/Фреймворк     (#воронкиипродажи / #операционка)
  19:00 — Кейс/Сторителлинг      (#разборкейса)
"""

import json
import logging
import os
import random
from datetime import time as dtime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from content_sources import fetch_for_slot, ContentItem
from content_transformer import transform

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/tmp/bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ConversationHandler state
WAITING_EDIT = 1

PENDING_FILE = "pending_posts.json"
SEEN_FILE = "seen_ids.json"


# ─── Storage helpers ──────────────────────────────────────────────────────

def _load_json(path: str, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_seen() -> set:
    return set(_load_json(SEEN_FILE, []))


def save_seen(seen: set) -> None:
    _save_json(SEEN_FILE, list(seen))


def load_pending() -> dict:
    return _load_json(PENDING_FILE, {})


def save_pending(pending: dict) -> None:
    _save_json(PENDING_FILE, pending)


# ─── Keyboard factory ─────────────────────────────────────────────────────

def approval_keyboard(post_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve_{post_id}"),
            InlineKeyboardButton("🔄 Переписать",   callback_data=f"rewrite_{post_id}"),
        ],
        [
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{post_id}"),
            InlineKeyboardButton("❌ Пропустить",    callback_data=f"skip_{post_id}"),
        ],
    ])


# ─── Slot runner ──────────────────────────────────────────────────────────

async def run_slot(context: ContextTypes.DEFAULT_TYPE, post_format: str) -> None:
    """Собрать контент для слота, трансформировать и отправить черновик."""
    logger.info(f"Running slot: {post_format}")
    seen = load_seen()
    pending = load_pending()

    try:
        items = fetch_for_slot(post_format, max_items=10)
        if not items:
            logger.warning(f"No items for slot {post_format}")
            return

        # Выбираем случайный из топ-5, которых ещё не видели
        candidates = [i for i in items[:5] if i.url not in seen]
        if not candidates:
            candidates = items[:3]

        item = random.choice(candidates)
        seen.add(item.url)
        save_seen(seen)

        logger.info(f"Transforming: {item.title[:60]}")
        text = transform(item)
        if not text:
            logger.warning("Empty transform result")
            return

        post_id = f"{post_format}_{abs(hash(item.url))}"
        pending[post_id] = {
            "text": text,
            "title": item.title,
            "post_format": item.post_format,
            "source": item.source,
            "url": item.url,
            "summary": item.summary,
            "hashtag": item.hashtag,
        }
        save_pending(pending)

        slot_labels = {
            "morning_insight":    "☀️ Утренний инсайт",
            "afternoon_practice": "📚 Практика дня",
            "evening_case":       "🌙 Кейс вечера",
            "tool":               "🛠 Полезняшка",
        }
        label = slot_labels.get(post_format, post_format)

        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text=(
                f"📋 <b>{label}</b>\n"
                f"📰 {item.source}\n\n"
                f"{text}"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=approval_keyboard(post_id),
        )
        logger.info(f"Draft sent for slot {post_format}: {post_id}")

    except Exception as e:
        logger.error(f"Slot {post_format} error: {e}")


# ─── Scheduled jobs ───────────────────────────────────────────────────────

async def job_morning(context: ContextTypes.DEFAULT_TYPE):
    await run_slot(context, "morning_insight")


async def job_afternoon(context: ContextTypes.DEFAULT_TYPE):
    await run_slot(context, "afternoon_practice")


async def job_evening(context: ContextTypes.DEFAULT_TYPE):
    await run_slot(context, "evening_case")


async def job_tool(context: ContextTypes.DEFAULT_TYPE):
    """Полезняшка — только вт(1), чт(3), сб(5)."""
    from datetime import datetime
    import pytz
    today = datetime.now(pytz.timezone("Asia/Makassar")).weekday()
    if today in (1, 3, 5):
        await run_slot(context, "tool")
    else:
        logger.info("Tool slot skipped (not Tue/Thu/Sat)")


# ─── Callback handlers ────────────────────────────────────────────────────

async def on_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    post_id = query.data.removeprefix("approve_")
    pending = load_pending()
    post = pending.get(post_id)

    if not post:
        await query.edit_message_text("⚠️ Пост не найден — возможно, уже обработан.")
        return

    await context.bot.send_message(
        chat_id=config.TELEGRAM_CHANNEL_ID,
        text=post["text"],
        parse_mode=ParseMode.HTML,
    )

    del pending[post_id]
    save_pending(pending)

    short = post["text"][:200].rstrip()
    await query.edit_message_text(
        f"✅ <b>Опубликовано в {config.TELEGRAM_CHANNEL_ID}!</b>\n\n{short}…",
        parse_mode=ParseMode.HTML,
    )
    logger.info(f"Published post {post_id}")


async def on_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    post_id = query.data.removeprefix("skip_")
    pending = load_pending()
    if post_id in pending:
        del pending[post_id]
        save_pending(pending)

    await query.edit_message_text(
        query.message.text + "\n\n❌ <i>Пропущено</i>",
        parse_mode=ParseMode.HTML,
    )
    logger.info(f"Skipped post {post_id}")


async def on_rewrite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    post_id = query.data.removeprefix("rewrite_")
    pending = load_pending()
    post = pending.get(post_id)

    if not post:
        await query.edit_message_text("⚠️ Пост не найден.")
        return

    await query.edit_message_text("🔄 Переписываю пост... подождите немного")

    try:
        item = ContentItem(
            title=post["title"],
            url=post["url"],
            summary=post.get("summary", ""),
            source=post["source"],
            post_format=post["post_format"],
            hashtag=post["hashtag"],
        )
        new_text = transform(item)
        if not new_text:
            await query.edit_message_text("❌ Не удалось переписать. Попробуйте ещё раз.")
            return

        pending[post_id]["text"] = new_text
        save_pending(pending)

        slot_labels = {
            "morning_insight":    "☀️ Утренний инсайт",
            "afternoon_practice": "📚 Практика дня",
            "evening_case":       "🌙 Кейс вечера",
            "tool":               "🛠 Полезняшка",
        }
        label = slot_labels.get(post["post_format"], post["post_format"])

        await query.edit_message_text(
            f"📋 <b>{label}</b> (переписан)\n"
            f"📰 {post['source']}\n\n"
            f"{new_text}",
            parse_mode=ParseMode.HTML,
            reply_markup=approval_keyboard(post_id),
        )
        logger.info(f"Rewritten post {post_id}")

    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {e}")
        logger.error(f"Rewrite error: {e}")


async def on_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    post_id = query.data.removeprefix("edit_")
    pending = load_pending()
    post = pending.get(post_id)

    if not post:
        await query.edit_message_text("⚠️ Пост не найден.")
        return ConversationHandler.END

    context.user_data["editing_post_id"] = post_id

    await query.message.reply_text(
        f"✏️ <b>Редактирование</b>\n\n"
        f"<i>Текущий текст:</i>\n{post['text']}\n\n"
        f"Отправь новый текст или /cancel для отмены.",
        parse_mode=ParseMode.HTML,
    )
    return WAITING_EDIT


async def on_edit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    post_id = context.user_data.get("editing_post_id")
    if not post_id:
        return ConversationHandler.END

    new_text = update.message.text
    pending = load_pending()
    if post_id not in pending:
        await update.message.reply_text("⚠️ Пост не найден.")
        return ConversationHandler.END

    pending[post_id]["text"] = new_text
    save_pending(pending)
    context.user_data.pop("editing_post_id", None)

    await update.message.reply_text(
        f"📋 <b>Предпросмотр:</b>\n\n{new_text}",
        parse_mode=ParseMode.HTML,
        reply_markup=approval_keyboard(post_id),
    )
    return ConversationHandler.END


async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("editing_post_id", None)
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


# ─── Entry point ──────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(on_edit_start, pattern=r"^edit_")],
        states={
            WAITING_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_edit_receive)],
        },
        fallbacks=[MessageHandler(filters.Regex(r"^/cancel$"), on_cancel)],
        per_chat=True,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(on_approve, pattern=r"^approve_"))
    app.add_handler(CallbackQueryHandler(on_skip,    pattern=r"^skip_"))
    app.add_handler(CallbackQueryHandler(on_rewrite, pattern=r"^rewrite_"))

    # Расписание (UTC, Бали = UTC+8)
    jq = app.job_queue
    jq.run_daily(job_morning,   time=dtime(hour=1,  minute=0), name="morning")    # 09:00 Bali
    jq.run_daily(job_tool,      time=dtime(hour=3,  minute=0), name="tool")       # 11:00 Bali
    jq.run_daily(job_afternoon, time=dtime(hour=6,  minute=0), name="afternoon")  # 14:00 Bali
    jq.run_daily(job_evening,   time=dtime(hour=11, minute=0), name="evening")    # 19:00 Bali

    # Тестовый запуск через 5 секунд после старта
    async def startup_test(ctx: ContextTypes.DEFAULT_TYPE):
        logger.info("Startup test — sending morning insight...")
        await run_slot(ctx, "morning_insight")

    jq.run_once(startup_test, when=5)

    logger.info("=" * 55)
    logger.info("Bot started! Schedule (Bali UTC+8):")
    logger.info("  09:00 daily      — Morning Insight  #мысливслух")
    logger.info("  11:00 Tue/Thu/Sat — Tool            #полезняшка")
    logger.info("  14:00 daily      — Afternoon Practice #воронкиипродажи")
    logger.info("  19:00 daily      — Evening Case     #разборкейса")
    logger.info(f"  Channel: {config.TELEGRAM_CHANNEL_ID}")
    logger.info(f"  Admin:   {config.TELEGRAM_ADMIN_CHAT_ID}")
    logger.info("=" * 55)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
