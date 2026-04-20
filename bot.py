#!/usr/bin/env python3
"""
AI Content Curator Bot
Flow: Reddit → Claude transform → admin approval (Telegram) → publish to channel
"""

import json
import logging
import os

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
from reddit_client import fetch_posts
from content_transformer import transform_post

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ConversationHandler state
WAITING_EDIT = 1

PENDING_FILE = "pending_posts.json"
SEEN_FILE = "seen_ids.json"


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _load_json(path: str, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_seen() -> set[str]:
    return set(_load_json(SEEN_FILE, []))


def save_seen(seen: set[str]) -> None:
    _save_json(SEEN_FILE, list(seen))


def load_pending() -> dict:
    return _load_json(PENDING_FILE, {})


def save_pending(pending: dict) -> None:
    _save_json(PENDING_FILE, pending)


# ---------------------------------------------------------------------------
# Keyboard factory
# ---------------------------------------------------------------------------

def approval_keyboard(post_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve_{post_id}"),
        InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{post_id}"),
        InlineKeyboardButton("❌ Пропустить",    callback_data=f"skip_{post_id}"),
    ]])


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------

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

    seen = load_seen()
    seen.add(post_id)
    save_seen(seen)

    short = post["text"][:200].rstrip()
    await query.edit_message_text(
        f"✅ <b>Опубликовано!</b>\n\n{short}…",
        parse_mode=ParseMode.HTML,
    )
    logger.info("Published post %s", post_id)


async def on_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    post_id = query.data.removeprefix("skip_")
    pending = load_pending()
    if post_id in pending:
        del pending[post_id]
        save_pending(pending)

    seen = load_seen()
    seen.add(post_id)
    save_seen(seen)

    original = query.message.text or ""
    await query.edit_message_text(
        original + "\n\n❌ <i>Пропущено</i>",
        parse_mode=ParseMode.HTML,
    )
    logger.info("Skipped post %s", post_id)


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
        await update.message.reply_text("⚠️ Нет активного редактирования.")
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


# ---------------------------------------------------------------------------
# Scheduled fetch job
# ---------------------------------------------------------------------------

async def fetch_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Fetch job started")
    seen = load_seen()
    pending = load_pending()
    skip_ids = seen | set(pending.keys())

    posts = fetch_posts(skip_ids)
    logger.info("Fetched %d candidate posts", len(posts))

    sent = 0
    for post in posts:
        if sent >= config.MAX_POSTS_PER_RUN:
            break

        logger.info("Transforming: %s (r/%s)", post.title[:60], post.subreddit)
        text = transform_post(post)
        if not text:
            seen.add(post.post_id)
            continue

        pending[post.post_id] = {"text": text, "title": post.title}
        save_pending(pending)

        meta = f"<b>r/{post.subreddit}</b> · {post.upvotes} upvotes"
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text=f"📋 <b>На проверку:</b>\n{meta}\n\n{text}",
            parse_mode=ParseMode.HTML,
            reply_markup=approval_keyboard(post.post_id),
        )
        sent += 1

    save_seen(seen)
    logger.info("Fetch job done — sent %d posts for approval", sent)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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
    app.add_handler(CallbackQueryHandler(on_skip, pattern=r"^skip_"))

    app.job_queue.run_repeating(
        fetch_job,
        interval=config.POST_INTERVAL_MINUTES * 60,
        first=10,
    )

    logger.info(
        "Bot started. Admin: %s | Channel: %s | Interval: %d min | Max posts: %d",
        config.TELEGRAM_ADMIN_CHAT_ID,
        config.TELEGRAM_CHANNEL_ID,
        config.POST_INTERVAL_MINUTES,
        config.MAX_POSTS_PER_RUN,
    )
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
