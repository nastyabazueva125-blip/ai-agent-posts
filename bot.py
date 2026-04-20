#!/usr/bin/env python3
"""
AI Content Curator Bot для @bazuevaconsalt
Двухэтапная модерация:
  1. Бот присылает ТЕМУ + оригинальный заголовок + ссылку
  2. Если одобрено — генерирует пост в стиле Насти
  3. Пост можно опубликовать, переписать, редактировать или пропустить

Расписание (время Бали UTC+8):
  09:00 — Утренний инсайт        (#мысливслух)
  11:00 вт/чт/сб — Полезняшка   (#полезняшка)
  14:00 — Практика/Фреймворк     (#воронкиипродажи / #операционка)
  19:00 — Кейс/Сторителлинг      (#разборкейса)
"""

import asyncio
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

# ConversationHandler states
WAITING_EDIT = 1

PENDING_FILE = "pending_posts.json"
SEEN_FILE = "seen_ids.json"

SLOT_LABELS = {
    "morning_insight":    "☀️ Утренний инсайт",
    "afternoon_practice": "📚 Практика дня",
    "evening_case":       "🌙 Кейс вечера",
    "tool":               "🛠 Полезняшка",
}

CATEGORIES = {
    "#мысливслух":       "Мышление и Подход",
    "#воронкиипродажи":  "Продажи и Маркетинг",
    "#операционка":      "Управление и Процессы",
    "#разборкейса":      "Бизнес-разбор",
    "#полезняшка":       "Инструменты для бизнеса",
    "#aiдлябизнеса":     "Нейросети для SMB",
}


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


# ─── Keyboards ────────────────────────────────────────────────────────────

def topic_keyboard(post_id: str) -> InlineKeyboardMarkup:
    """Клавиатура для ЭТАПА 1 — одобрение темы."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Написать пост", callback_data=f"generate_{post_id}"),
            InlineKeyboardButton("⏭ Следующая тема", callback_data=f"next_{post_id}"),
        ],
        [
            InlineKeyboardButton("❌ Пропустить",    callback_data=f"skip_{post_id}"),
        ],
    ])


def draft_keyboard(post_id: str) -> InlineKeyboardMarkup:
    """Клавиатура для ЭТАПА 2 — модерация готового поста."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Опубликовать",  callback_data=f"approve_{post_id}"),
            InlineKeyboardButton("🔄 Переписать",    callback_data=f"rewrite_{post_id}"),
        ],
        [
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{post_id}"),
            InlineKeyboardButton("⏭ Другая тема",    callback_data=f"next_{post_id}"),
        ],
        [
            InlineKeyboardButton("❌ Пропустить",    callback_data=f"skip_{post_id}"),
        ],
    ])


# ─── Message builders ─────────────────────────────────────────────────────

def build_topic_message(post: dict) -> str:
    """ЭТАП 1: показываем тему + оригинал, без сгенерированного текста."""
    label = SLOT_LABELS.get(post.get("post_format", ""), "📋 Черновик")
    category = CATEGORIES.get(post.get("hashtag", ""), "Практика для бизнеса")
    source = post.get("source", "")
    published = post.get("published", "")
    url = post.get("url", "")
    title = post.get("title", "")
    summary = post.get("summary", "")[:300]

    date_str = f" · {published}" if published else ""

    lines = [
        f"<b>{label}</b> | 📂 {category}",
        f"",
        f"📌 <b>{title}</b>",
        f"",
        f"📰 <b>{source}</b>{date_str}",
    ]
    if url:
        lines.append(f'🔗 <a href="{url}">Читать оригинал</a>')
    if summary:
        lines.append(f"")
        lines.append(f"<i>{summary}…</i>")

    lines.append(f"")
    lines.append(f"Написать пост на эту тему?")

    return "\n".join(lines)


def build_draft_header(post: dict) -> str:
    """ЭТАП 2: шапка для готового поста."""
    label = SLOT_LABELS.get(post.get("post_format", ""), "📋 Черновик")
    category = CATEGORIES.get(post.get("hashtag", ""), "Практика для бизнеса")
    source = post.get("source", "")
    published = post.get("published", "")
    url = post.get("url", "")

    date_str = f" · {published}" if published else ""
    source_line = f"📰 <b>{source}</b>{date_str}"
    if url:
        source_line += f'\n🔗 <a href="{url}">Оригинал</a>'

    return f"<b>{label}</b> | 📂 {category}\n{source_line}\n\n"


# ─── Slot runner ──────────────────────────────────────────────────────────

async def run_slot(context: ContextTypes.DEFAULT_TYPE, post_format: str) -> None:
    """Собрать контент для слота и показать ТЕМУ (этап 1)."""
    logger.info(f"Running slot: {post_format}")
    seen = load_seen()

    try:
        items = fetch_for_slot(post_format, max_items=10)
        if not items:
            logger.warning(f"No items for slot {post_format}")
            return

        candidates = [i for i in items[:5] if i.url not in seen]
        if not candidates:
            candidates = items[:3]

        item = random.choice(candidates)
        await _send_topic(context, item)

    except Exception as e:
        logger.error(f"Slot {post_format} error: {e}")


async def _send_topic(context: ContextTypes.DEFAULT_TYPE, item: ContentItem) -> None:
    """ЭТАП 1: отправить тему + оригинал для одобрения."""
    seen = load_seen()
    pending = load_pending()

    seen.add(item.url)
    save_seen(seen)

    post_id = f"{item.post_format}_{abs(hash(item.url))}"
    pending[post_id] = {
        "stage": "topic",          # этап 1 — тема ещё не сгенерирована
        "text": None,              # текст будет после генерации
        "title": item.title,
        "post_format": item.post_format,
        "source": item.source,
        "url": item.url,
        "summary": item.summary,
        "hashtag": item.hashtag,
        "published": item.published or "",
    }
    save_pending(pending)

    message = build_topic_message(pending[post_id])

    for attempt in range(3):
        try:
            await context.bot.send_message(
                chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
                text=message,
                parse_mode=ParseMode.HTML,
                reply_markup=topic_keyboard(post_id),
                disable_web_page_preview=True,
            )
            logger.info(f"Topic sent for slot {item.post_format}: {item.title[:50]}")
            break
        except Exception as e:
            if attempt < 2:
                logger.warning(f"Send attempt {attempt+1} failed: {e} — retrying in 5s")
                await asyncio.sleep(5)
            else:
                logger.error(f"Failed to send topic after 3 attempts: {e}")
                raise


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

async def on_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ЭТАП 1 → 2: одобрили тему, генерируем пост."""
    query = update.callback_query
    await query.answer("Генерирую пост...")

    post_id = query.data.removeprefix("generate_")
    pending = load_pending()
    post = pending.get(post_id)

    if not post:
        await query.edit_message_text("⚠️ Тема не найдена — возможно, уже обработана.")
        return

    await query.edit_message_text(
        query.message.text + "\n\n⏳ <i>Генерирую пост...</i>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    try:
        item = ContentItem(
            title=post["title"],
            url=post["url"],
            summary=post.get("summary", ""),
            source=post["source"],
            post_format=post["post_format"],
            hashtag=post["hashtag"],
            published=post.get("published", ""),
        )
        text = transform(item)
        if not text:
            await context.bot.send_message(
                chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
                text="❌ Не удалось сгенерировать пост. Попробуй другую тему.",
            )
            return

        pending[post_id]["text"] = text
        pending[post_id]["stage"] = "draft"
        save_pending(pending)

        header = build_draft_header(pending[post_id])

        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text=header + text,
            parse_mode=ParseMode.HTML,
            reply_markup=draft_keyboard(post_id),
            disable_web_page_preview=True,
        )
        logger.info(f"Draft generated for {post_id}")

    except Exception as e:
        logger.error(f"Generate error: {e}")
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text=f"❌ Ошибка генерации: {e}",
        )


async def on_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Опубликовать готовый пост в канал."""
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
    """Пропустить тему или пост."""
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
        disable_web_page_preview=True,
    )
    logger.info(f"Skipped post {post_id}")


async def on_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать следующую тему из того же слота."""
    query = update.callback_query
    await query.answer("Ищу следующую тему...")

    post_id = query.data.removeprefix("next_")
    pending = load_pending()
    post = pending.get(post_id)

    if not post:
        await query.edit_message_text("⚠️ Пост не найден.")
        return

    post_format = post.get("post_format", "morning_insight")
    seen = load_seen()

    if post_id in pending:
        del pending[post_id]
        save_pending(pending)

    await query.edit_message_text(
        query.message.text + "\n\n⏭ <i>Загружаю следующую тему...</i>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    try:
        items = fetch_for_slot(post_format, max_items=10)
        candidates = [i for i in items if i.url not in seen]
        if not candidates:
            await context.bot.send_message(
                chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
                text="😔 Больше новых тем для этого слота нет. Попробуй позже.",
            )
            return

        item = random.choice(candidates[:5])
        await _send_topic(context, item)

    except Exception as e:
        logger.error(f"Next topic error: {e}")
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text=f"❌ Ошибка при загрузке следующей темы: {e}",
        )


async def on_rewrite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Переписать пост заново."""
    query = update.callback_query
    await query.answer()

    post_id = query.data.removeprefix("rewrite_")
    pending = load_pending()
    post = pending.get(post_id)

    if not post:
        await query.edit_message_text("⚠️ Пост не найден.")
        return

    await query.edit_message_text(
        build_draft_header(post) + (post.get("text") or "") + "\n\n🔄 <i>Переписываю...</i>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    try:
        item = ContentItem(
            title=post["title"],
            url=post["url"],
            summary=post.get("summary", ""),
            source=post["source"],
            post_format=post["post_format"],
            hashtag=post["hashtag"],
            published=post.get("published", ""),
        )
        new_text = transform(item)
        if not new_text:
            await context.bot.send_message(
                chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
                text="❌ Не удалось переписать. Попробуйте ещё раз.",
            )
            return

        pending[post_id]["text"] = new_text
        save_pending(pending)

        header = build_draft_header(pending[post_id])
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text=header + new_text + "\n\n<i>(переписан)</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=draft_keyboard(post_id),
            disable_web_page_preview=True,
        )
        logger.info(f"Rewritten post {post_id}")

    except Exception as e:
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text=f"❌ Ошибка: {e}",
        )
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
        f"<i>Текущий текст:</i>\n{post.get('text', '')}\n\n"
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

    header = build_draft_header(pending[post_id])
    await update.message.reply_text(
        header + new_text,
        parse_mode=ParseMode.HTML,
        reply_markup=draft_keyboard(post_id),
        disable_web_page_preview=True,
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
    app.add_handler(CallbackQueryHandler(on_generate, pattern=r"^generate_"))
    app.add_handler(CallbackQueryHandler(on_approve,  pattern=r"^approve_"))
    app.add_handler(CallbackQueryHandler(on_skip,     pattern=r"^skip_"))
    app.add_handler(CallbackQueryHandler(on_rewrite,  pattern=r"^rewrite_"))
    app.add_handler(CallbackQueryHandler(on_next,     pattern=r"^next_"))

    # Расписание (UTC, Бали = UTC+8)
    jq = app.job_queue
    jq.run_daily(job_morning,   time=dtime(hour=1,  minute=0), name="morning")    # 09:00 Bali
    jq.run_daily(job_tool,      time=dtime(hour=3,  minute=0), name="tool")       # 11:00 Bali
    jq.run_daily(job_afternoon, time=dtime(hour=6,  minute=0), name="afternoon")  # 14:00 Bali
    jq.run_daily(job_evening,   time=dtime(hour=11, minute=0), name="evening")    # 19:00 Bali

    # Тестовый запуск через 5 секунд после старта
    async def startup_test(ctx: ContextTypes.DEFAULT_TYPE):
        logger.info("Startup test — sending morning insight topic...")
        await run_slot(ctx, "morning_insight")

    jq.run_once(startup_test, when=5)

    logger.info("=" * 55)
    logger.info("Bot started! 2-stage moderation mode.")
    logger.info("  Stage 1: Topic + Original link → approve/skip/next")
    logger.info("  Stage 2: Generated draft → publish/rewrite/edit/skip")
    logger.info(f"  Channel: {config.TELEGRAM_CHANNEL_ID}")
    logger.info(f"  Admin:   {config.TELEGRAM_ADMIN_CHAT_ID}")
    logger.info("=" * 55)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
