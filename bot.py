#!/usr/bin/env python3
"""
AI Content Curator Bot для @bazuevaconsalt
Режим дайджеста:
  1. Утром бот собирает 10 свежих тем из всех слотов
  2. Переводит заголовки на русский (быстро, без полного текста)
  3. Присылает одно сообщение-дайджест со списком тем + кнопки 1-10
  4. Пользователь нажимает номер → бот генерирует полный перевод статьи
  5. Готовый пост: Опубликовать / Переписать / Редактировать / Пропустить / 🖼 Карточка

Расписание (UTC, Бали UTC+8):
  01:00 UTC (09:00 Бали) — дайджест 10 тем на день
"""

import asyncio
import json
import logging
import os
import random
import tempfile
from datetime import time as dtime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from content_sources import fetch_for_slot, ContentItem
from content_transformer import transform, translate_title
from card_generator import generate_card
from telegram_scraper import fetch_all_tg_channels

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
DIGEST_FILE = "digest_items.json"

SLOT_LABELS = {
    "morning_insight":    "☀️ Утро",
    "afternoon_practice": "📚 Практика",
    "evening_case":       "🌙 Кейс",
    "tool":               "🛠 Инструмент",
    "tg_channel":         "💬 TG-канал",
}

CATEGORIES = {
    "#мысливслух":       "Мышление и Подход",
    "#воронкиипродажи":  "Продажи и Маркетинг",
    "#операционка":      "Управление и Процессы",
    "#разборкейса":      "Бизнес-разбор",
    "#tools":            "Инструменты для бизнеса",
    "#aiдлябизнеса":     "Нейросети для SMB",
    "#трафик":           "SEO и Трафик",
    "#контентмаркетинг": "Контент-маркетинг",
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


def load_digest() -> list:
    return _load_json(DIGEST_FILE, [])


def save_digest(items: list) -> None:
    _save_json(DIGEST_FILE, items)


# ─── Keyboards ────────────────────────────────────────────────────────────

def digest_keyboard(count: int) -> InlineKeyboardMarkup:
    """Кнопки 1-N для выбора темы из дайджеста."""
    buttons = [
        InlineKeyboardButton(str(i + 1), callback_data=f"pick_{i}")
        for i in range(count)
    ]
    rows = []
    for i in range(0, len(buttons), 5):
        rows.append(buttons[i:i + 5])
    rows.append([InlineKeyboardButton("🔄 Обновить темы", callback_data="refresh_digest")])
    return InlineKeyboardMarkup(rows)


def draft_keyboard(post_id: str) -> InlineKeyboardMarkup:
    """Клавиатура для модерации готового поста."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Опубликовать",  callback_data=f"approve_{post_id}"),
            InlineKeyboardButton("🔄 Переписать",    callback_data=f"rewrite_{post_id}"),
        ],
        [
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{post_id}"),
            InlineKeyboardButton("❌ Пропустить",    callback_data=f"skip_{post_id}"),
        ],
        [
            InlineKeyboardButton("🖼 Карточка",      callback_data=f"card_{post_id}"),
            InlineKeyboardButton("📋 К дайджесту",   callback_data="show_digest"),
        ],
    ])


# ─── Digest builder ───────────────────────────────────────────────────────

def _build_digest_blocking() -> list:
    """Синхронная функция: собрать 10 тем и перевести заголовки.
    
    Структура дайджеста:
      - 3 темы из Telegram-каналов-референсов (гарантировано)
      - 7 тем из RSS-источников
    """
    seen = load_seen()

    # ── 1. Собираем посты из TG-каналов (гарантированные 3 темы) ──────────
    tg_items = []
    try:
        all_tg = fetch_all_tg_channels(max_per_channel=5)
        fresh_tg = [i for i in all_tg if i.url not in seen]
        # Берём не более 3, стараемся взять из разных каналов
        seen_sources = set()
        for item in fresh_tg:
            if item.source not in seen_sources:
                tg_items.append(item)
                seen_sources.add(item.source)
            if len(tg_items) >= 3:
                break
        # Если разных каналов мало — добираем из оставшихся
        if len(tg_items) < 3:
            for item in fresh_tg:
                if item not in tg_items:
                    tg_items.append(item)
                if len(tg_items) >= 3:
                    break
        logger.info(f"TG channels: {len(tg_items)} items selected for digest")
    except Exception as e:
        logger.error(f"TG channels fetch failed: {e}")

    # ── 2. Собираем RSS-посты (7 тем) ─────────────────────────────────────
    rss_items = []
    tg_urls = {i.url for i in tg_items}
    slots = ["morning_insight", "afternoon_practice", "evening_case", "tool"]
    for slot in slots:
        try:
            items = fetch_for_slot(slot, max_items=8)
            fresh = [i for i in items if i.url not in seen and i.url not in tg_urls]
            rss_items.extend(fresh[:4])
            logger.info(f"Slot {slot}: {len(fresh)} fresh items")
        except Exception as e:
            logger.error(f"Error fetching slot {slot}: {e}")

    # Убираем дубли по URL среди RSS
    seen_urls = set(tg_urls)
    unique_rss = []
    for item in rss_items:
        if item.url not in seen_urls:
            seen_urls.add(item.url)
            unique_rss.append(item)

    random.shuffle(unique_rss)
    rss_selected = unique_rss[:7]

    # ── 3. Собираем финальный список: TG первыми, затем RSS ───────────────
    selected = tg_items + rss_selected
    if not selected:
        logger.warning("No fresh items found for digest!")
        return []
    
    # Перемешиваем чтобы TG-посты не были всегда в начале
    random.shuffle(selected)
    selected = selected[:10]

    if not selected:
        logger.warning("No fresh items found for digest!")
        return []

    digest_items = []
    for idx, item in enumerate(selected):
        try:
            translated = translate_title(item.title, item.summary)
            digest_items.append({
                "num": idx + 1,
                "ru_title": translated["title"],
                "ru_desc": translated["description"],
                "slot_label": SLOT_LABELS.get(item.post_format, "📋"),
                "source": item.source,
                "url": item.url,
                "title": item.title,
                "summary": item.summary,
                "post_format": item.post_format,
                "hashtag": item.hashtag,
                "published": item.published or "",
            })
            logger.info(f"Translated {idx+1}/{len(selected)}: {translated['title'][:50]}")
        except Exception as e:
            logger.error(f"translate_title failed for item {idx+1}: {e}")
            digest_items.append({
                "num": idx + 1,
                "ru_title": item.title,
                "ru_desc": item.summary[:100] if item.summary else "",
                "slot_label": SLOT_LABELS.get(item.post_format, "📋"),
                "source": item.source,
                "url": item.url,
                "title": item.title,
                "summary": item.summary,
                "post_format": item.post_format,
                "hashtag": item.hashtag,
                "published": item.published or "",
            })

    return digest_items


def format_digest_message(digest_items: list) -> str:
    """Сформировать текст сообщения-дайджеста."""
    lines = ["<b>📋 Дайджест тем на сегодня</b>", ""]

    for item in digest_items:
        num = item["num"]
        label = item["slot_label"]
        title = item["ru_title"]
        source = item["source"]
        desc = item.get("ru_desc", "")

        lines.append(f"<b>{num}.</b> {label} <b>{title}</b>")
        lines.append(f"    <i>{source}</i>")
        if desc:
            lines.append(f"    {desc[:120]}{'…' if len(desc) > 120 else ''}")
        lines.append("")

    lines.append("👇 <b>Выбери тему — нажми на номер:</b>")
    return "\n".join(lines)


# ─── Digest job ───────────────────────────────────────────────────────────

async def job_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Собрать дайджест и отправить администратору."""
    logger.info("Building daily digest...")

    try:
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text="⏳ <i>Собираю темы дня, перевожу заголовки...</i>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    loop = asyncio.get_event_loop()
    digest_items = await loop.run_in_executor(None, _build_digest_blocking)

    if not digest_items:
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text="⚠️ Не удалось найти свежие темы. Попробуй позже или нажми /digest",
        )
        return

    save_digest(digest_items)

    text = format_digest_message(digest_items)
    keyboard = digest_keyboard(len(digest_items))

    for attempt in range(3):
        try:
            await context.bot.send_message(
                chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
            logger.info(f"Digest sent: {len(digest_items)} topics")
            break
        except Exception as e:
            if attempt < 2:
                logger.warning(f"Send attempt {attempt+1} failed: {e} — retrying in 5s")
                await asyncio.sleep(5)
            else:
                logger.error(f"Failed to send digest after 3 attempts: {e}")


# ─── Callback: pick topic from digest ─────────────────────────────────────

async def on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пользователь выбрал тему из дайджеста — генерируем полный пост."""
    query = update.callback_query
    await query.answer("Генерирую пост...")

    idx = int(query.data.removeprefix("pick_"))
    digest_items = load_digest()

    if idx >= len(digest_items):
        await query.edit_message_text("⚠️ Тема не найдена. Запроси новый дайджест: /digest")
        return

    item_data = digest_items[idx]

    try:
        await query.edit_message_text(
            f"⏳ <i>Генерирую пост по теме:</i>\n<b>{item_data['ru_title']}</b>\n\n"
            f"Это займёт 15-30 секунд...",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass

    item = ContentItem(
        title=item_data["title"],
        url=item_data["url"],
        summary=item_data.get("summary", ""),
        source=item_data["source"],
        post_format=item_data["post_format"],
        hashtag=item_data["hashtag"],
        published=item_data.get("published", ""),
    )

    loop = asyncio.get_event_loop()
    try:
        text = await loop.run_in_executor(None, transform, item)
    except Exception as e:
        logger.error(f"Transform failed: {e}")
        text = ""

    if not text:
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text="❌ Не удалось сгенерировать пост. Попробуй другую тему.",
        )
        return

    post_id = f"{item.post_format}_{abs(hash(item.url))}"
    pending = load_pending()
    pending[post_id] = {
        "stage": "draft",
        "text": text,
        "title": item.title,
        "ru_title": item_data["ru_title"],
        "post_format": item.post_format,
        "source": item.source,
        "url": item.url,
        "summary": item.summary,
        "hashtag": item.hashtag,
        "published": item.published or "",
    }
    save_pending(pending)

    seen = load_seen()
    seen.add(item.url)
    save_seen(seen)

    label = SLOT_LABELS.get(item.post_format, "📋 Черновик")
    category = CATEGORIES.get(item.hashtag, "Практика для бизнеса")
    date_str = f" · {item.published}" if item.published else ""
    source_line = f"📰 <b>{item.source}</b>{date_str}"
    if item.url:
        source_line += f'\n🔗 <a href="{item.url}">Оригинал</a>'
    header = f"<b>{label}</b> | 📂 {category}\n{source_line}\n\n"

    await context.bot.send_message(
        chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
        text=header + text,
        parse_mode=ParseMode.HTML,
        reply_markup=draft_keyboard(post_id),
        disable_web_page_preview=True,
    )
    logger.info(f"Draft sent for: {item.title[:50]}")


async def on_refresh_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обновить дайджест по кнопке."""
    query = update.callback_query
    await query.answer("Обновляю темы...")
    await job_digest(context)


async def on_show_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать текущий дайджест (кнопка 'К дайджесту' из черновика)."""
    query = update.callback_query
    await query.answer()

    digest_items = load_digest()
    if not digest_items:
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text="📋 Дайджест пуст. Запроси новый: /digest",
        )
        return

    text = format_digest_message(digest_items)
    keyboard = digest_keyboard(len(digest_items))

    await context.bot.send_message(
        chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ─── Callback: 🖼 Карточка — генерация по требованию ─────────────────────

async def on_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Сгенерировать и отправить визуальную карточку для поста."""
    query = update.callback_query
    await query.answer("Генерирую карточку...")

    post_id = query.data.removeprefix("card_")
    pending = load_pending()
    post = pending.get(post_id)

    if not post:
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text="⚠️ Пост не найден.",
        )
        return

    ru_title = post.get("ru_title", post.get("title", ""))
    source = post.get("source", "")
    hashtag = post.get("hashtag", "")

    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            card_path = tmp.name

        loop = asyncio.get_event_loop()
        card_path = await loop.run_in_executor(
            None,
            lambda: generate_card(
                title=ru_title,
                source=source,
                hashtag=hashtag,
                output_path=card_path,
            )
        )
        logger.info(f"Card generated on demand: {card_path}")

        with open(card_path, "rb") as photo_file:
            await context.bot.send_photo(
                chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
                photo=photo_file,
                caption=f"🖼 <b>Карточка для поста</b>\n<i>{ru_title}</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📤 Опубликовать с карточкой", callback_data=f"approve_with_card_{post_id}"),
                ]]),
            )
        os.unlink(card_path)

    except Exception as e:
        logger.error(f"Card generation failed: {e}")
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text=f"❌ Не удалось сгенерировать карточку: {e}",
        )


# ─── Callback: approve with card ─────────────────────────────────────────

async def on_approve_with_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Опубликовать пост в канал вместе с карточкой."""
    query = update.callback_query
    await query.answer("Публикую с карточкой...")

    post_id = query.data.removeprefix("approve_with_card_")
    pending = load_pending()
    post = pending.get(post_id)

    if not post or not post.get("text"):
        await query.edit_message_text("⚠️ Пост не найден или пустой.")
        return

    try:
        ru_title = post.get("ru_title", post.get("title", ""))
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            card_path = tmp.name

        card_path = generate_card(
            title=ru_title,
            source=post.get("source", ""),
            hashtag=post.get("hashtag", ""),
            output_path=card_path,
        )

        with open(card_path, "rb") as photo_file:
            await context.bot.send_photo(
                chat_id=config.TELEGRAM_CHANNEL_ID,
                photo=photo_file,
                caption=post["text"],
                parse_mode=ParseMode.HTML,
            )
        os.unlink(card_path)

        del pending[post_id]
        save_pending(pending)

        await query.edit_message_caption(
            caption=query.message.caption + "\n\n✅ <b>Опубликовано с карточкой!</b>",
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"Published with card: {post.get('title', '')[:50]}")

    except Exception as e:
        logger.error(f"Publish with card failed: {e}")
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text=f"❌ Ошибка публикации с карточкой: {e}",
        )


# ─── Callback: approve / skip / rewrite / edit ────────────────────────────

async def on_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Опубликовать пост в канал (только текст)."""
    query = update.callback_query
    await query.answer("Публикую...")

    post_id = query.data.removeprefix("approve_")
    pending = load_pending()
    post = pending.get(post_id)

    if not post or not post.get("text"):
        await query.edit_message_text("⚠️ Пост не найден или пустой.")
        return

    try:
        await context.bot.send_message(
            chat_id=config.TELEGRAM_CHANNEL_ID,
            text=post["text"],
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        del pending[post_id]
        save_pending(pending)

        await query.edit_message_text(
            query.message.text + "\n\n✅ <b>Опубликовано!</b>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info(f"Published post: {post.get('title', '')[:50]}")
    except Exception as e:
        logger.error(f"Publish failed: {e}")
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text=f"❌ Ошибка публикации: {e}",
        )


async def on_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пропустить пост."""
    query = update.callback_query
    await query.answer("Пропущено")

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


async def on_rewrite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Переписать пост заново."""
    query = update.callback_query
    await query.answer("Переписываю...")

    post_id = query.data.removeprefix("rewrite_")
    pending = load_pending()
    post = pending.get(post_id)

    if not post:
        await query.edit_message_text("⚠️ Пост не найден.")
        return

    await query.edit_message_text(
        query.message.text + "\n\n🔄 <i>Переписываю...</i>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    item = ContentItem(
        title=post["title"],
        url=post["url"],
        summary=post.get("summary", ""),
        source=post["source"],
        post_format=post["post_format"],
        hashtag=post["hashtag"],
        published=post.get("published", ""),
    )

    loop = asyncio.get_event_loop()
    try:
        text = await loop.run_in_executor(None, transform, item)
    except Exception as e:
        logger.error(f"Rewrite failed: {e}")
        text = ""

    if not text:
        await context.bot.send_message(
            chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
            text="❌ Не удалось переписать пост.",
        )
        return

    pending[post_id]["text"] = text
    save_pending(pending)

    label = SLOT_LABELS.get(post["post_format"], "📋 Черновик")
    category = CATEGORIES.get(post.get("hashtag", ""), "Практика для бизнеса")
    date_str = f" · {post['published']}" if post.get("published") else ""
    source_line = f"📰 <b>{post['source']}</b>{date_str}"
    if post.get("url"):
        source_line += f'\n🔗 <a href="{post["url"]}">Оригинал</a>'
    header = f"<b>{label}</b> | 📂 {category}\n{source_line}\n\n"

    await context.bot.send_message(
        chat_id=config.TELEGRAM_ADMIN_CHAT_ID,
        text=header + text,
        parse_mode=ParseMode.HTML,
        reply_markup=draft_keyboard(post_id),
        disable_web_page_preview=True,
    )


async def on_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начать редактирование поста вручную."""
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

    post = pending[post_id]
    label = SLOT_LABELS.get(post["post_format"], "📋 Черновик")
    category = CATEGORIES.get(post.get("hashtag", ""), "Практика для бизнеса")
    date_str = f" · {post['published']}" if post.get("published") else ""
    source_line = f"📰 <b>{post['source']}</b>{date_str}"
    if post.get("url"):
        source_line += f'\n🔗 <a href="{post["url"]}">Оригинал</a>'
    header = f"<b>{label}</b> | 📂 {category}\n{source_line}\n\n"

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


# ─── Command handlers ─────────────────────────────────────────────────────

async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/digest — запросить дайджест вручную."""
    await update.message.reply_text("⏳ Собираю темы дня...")
    await job_digest(context)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — приветствие."""
    await update.message.reply_text(
        "👋 Привет! Я бот-куратор контента для @bazuevaconsalt.\n\n"
        "Каждое утро в 09:00 (Бали) я пришлю дайджест из 10 свежих тем.\n"
        "Ты выбираешь тему — я пишу пост.\n\n"
        "Команды:\n"
        "/digest — получить дайджест прямо сейчас\n"
        "/start — это сообщение"
    )


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
    app.add_handler(CallbackQueryHandler(on_pick,              pattern=r"^pick_\d+$"))
    app.add_handler(CallbackQueryHandler(on_refresh_digest,    pattern=r"^refresh_digest$"))
    app.add_handler(CallbackQueryHandler(on_show_digest,       pattern=r"^show_digest$"))
    app.add_handler(CallbackQueryHandler(on_card,              pattern=r"^card_"))
    app.add_handler(CallbackQueryHandler(on_approve_with_card, pattern=r"^approve_with_card_"))
    app.add_handler(CallbackQueryHandler(on_approve,           pattern=r"^approve_"))
    app.add_handler(CallbackQueryHandler(on_skip,              pattern=r"^skip_"))
    app.add_handler(CallbackQueryHandler(on_rewrite,           pattern=r"^rewrite_"))
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("digest", cmd_digest))

    # Расписание: дайджест каждый день в 01:00 UTC (09:00 Бали)
    jq = app.job_queue
    jq.run_daily(job_digest, time=dtime(hour=1, minute=0), name="daily_digest")

    # Тестовый запуск через 5 секунд после старта
    async def startup_test(ctx: ContextTypes.DEFAULT_TYPE):
        logger.info("Startup: sending digest...")
        await job_digest(ctx)

    jq.run_once(startup_test, when=5)

    logger.info("=" * 55)
    logger.info("Bot started! Digest mode.")
    logger.info("  Daily digest at 01:00 UTC (09:00 Bali)")
    logger.info("  10 topics → user picks one → bot writes post")
    logger.info(f"  Channel: {config.TELEGRAM_CHANNEL_ID}")
    logger.info(f"  Admin:   {config.TELEGRAM_ADMIN_CHAT_ID}")
    logger.info("=" * 55)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
