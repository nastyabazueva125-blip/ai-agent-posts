"""
Telegram-бот @bazuevaconsalt — контент-менеджер.

4 рубрики:
  📚 Контент-план  — учебные посты по темам недели (content_plan.py)
  🛠 Tools         — новые инструменты с Product Hunt
  📌 Конкуренты    — посты из TG-каналов коллег (@grebenukm, @big_bad_coach, @llm_under_hood)
  💡 Мои наблюдения — голосовые заметки + ввод темы вручную

Дайджест: 10 тем — 3 из контент-плана, 2 tools, 3 конкуренты, 2 полезные TG
"""

import asyncio
import json
import logging
import os
import random
import subprocess
import tempfile
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import content_plan as cp
import content_sources as cs
import content_transformer as ct
import telegram_scraper as ts

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/bot.log"),
    ],
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@bazuevaconsalt")
ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "318891687"))

SEEN_FILE = "seen_ids.json"
THOUGHTS_FILE = "thoughts.json"

# ─── Seen IDs ─────────────────────────────────────────────────────────────

def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen: set):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

# ─── Thoughts (голосовые заметки) ─────────────────────────────────────────

def load_thoughts() -> list:
    if os.path.exists(THOUGHTS_FILE):
        with open(THOUGHTS_FILE) as f:
            return json.load(f)
    return []

def save_thoughts(thoughts: list):
    with open(THOUGHTS_FILE, "w") as f:
        json.dump(thoughts, f, ensure_ascii=False, indent=2)

def add_thought(text: str, source: str = "voice") -> int:
    thoughts = load_thoughts()
    idx = len(thoughts)
    thoughts.append({
        "id": idx,
        "text": text,
        "source": source,
        "created": datetime.now(timezone.utc).isoformat(),
    })
    save_thoughts(thoughts)
    return idx

# ─── Draft storage ────────────────────────────────────────────────────────

drafts: dict = {}  # chat_id -> {item, post_text, card_path}

# ─── Build digest ─────────────────────────────────────────────────────────

def _build_digest_blocking() -> list:
    """Собрать 10 тем: 3 контент-план + 2 tools + 3 конкуренты + 2 useful TG."""
    seen = load_seen()
    items = []

    # 1. Контент-план — 3 темы
    plan = cp.get_or_create_weekly_plan()
    topics = plan.get("topics", [])
    used_idx = set(plan.get("used_indices", []))
    plan_count = 0
    for i, topic in enumerate(topics):
        if plan_count >= 3:
            break
        item_id = f"cp_{i}_{topic[:20]}"
        if item_id not in seen:
            from dataclasses import dataclass
            @dataclass
            class PlanItem:
                title: str
                url: str
                summary: str
                source: str
                post_format: str
                hashtag: str
                published: str = ""
            items.append(PlanItem(
                title=topic,
                url="",
                summary="",
                source="Контент-план",
                post_format="content_plan",
                hashtag="#мысливслух",
            ))
            plan_count += 1

    # 2. Tools — 2 темы с Product Hunt
    try:
        tools_items = cs.fetch_tools_rss(max_items=8)
        tools_added = 0
        for it in tools_items:
            if tools_added >= 2:
                break
            item_id = it.url or it.title
            if item_id not in seen:
                items.append(it)
                tools_added += 1
    except Exception as e:
        logger.warning(f"Tools fetch failed: {e}")

    # 3. Конкуренты — 3 темы из TG-каналов конкурентов
    try:
        comp_posts = []
        for ch in cs.TG_COMPETITORS:
            posts = ts.fetch_channel_posts(ch["handle"], max_posts=10)
            for p in posts:
                p["_channel"] = ch
            comp_posts.extend(posts)
        random.shuffle(comp_posts)
        comp_added = 0
        for p in comp_posts:
            if comp_added >= 3:
                break
            item_id = p.get("url", "") or p.get("text", "")[:50]
            if item_id not in seen:
                ch = p["_channel"]
                from dataclasses import dataclass
                @dataclass
                class TGItem:
                    title: str
                    url: str
                    summary: str
                    source: str
                    post_format: str
                    hashtag: str
                    published: str = ""
                items.append(TGItem(
                    title=p.get("text", "")[:120] + "...",
                    url=p.get("url", ""),
                    summary=p.get("text", ""),
                    source=ch["name"],
                    post_format="competitors",
                    hashtag=ch["hashtag"],
                ))
                comp_added += 1
    except Exception as e:
        logger.warning(f"Competitors TG fetch failed: {e}")

    # 4. Useful TG — 2 темы из @promtolog, @ai_for_business, @prompt_design
    try:
        useful_posts = []
        for ch in cs.TG_USEFUL:
            posts = ts.fetch_channel_posts(ch["handle"], max_posts=10)
            for p in posts:
                p["_channel"] = ch
            useful_posts.extend(posts)
        random.shuffle(useful_posts)
        useful_added = 0
        for p in useful_posts:
            if useful_added >= 2:
                break
            item_id = p.get("url", "") or p.get("text", "")[:50]
            if item_id not in seen:
                ch = p["_channel"]
                from dataclasses import dataclass
                @dataclass
                class TGItem2:
                    title: str
                    url: str
                    summary: str
                    source: str
                    post_format: str
                    hashtag: str
                    published: str = ""
                items.append(TGItem2(
                    title=p.get("text", "")[:120] + "...",
                    url=p.get("url", ""),
                    summary=p.get("text", ""),
                    source=ch["name"],
                    post_format="useful",
                    hashtag=ch["hashtag"],
                ))
                useful_added += 1
    except Exception as e:
        logger.warning(f"Useful TG fetch failed: {e}")

    logger.info(f"Digest built: {len(items)} items")
    return items[:10]


# ─── Format digest message ────────────────────────────────────────────────

def _format_digest(items: list) -> tuple[str, InlineKeyboardMarkup]:
    """Сформировать текст дайджеста и клавиатуру."""
    lines = ["📋 <b>Дайджест тем на сегодня</b>\n"]

    # Группируем по рубрикам
    sections = {
        "content_plan": ("📚 Контент-план", []),
        "tools": ("🛠 Tools", []),
        "competitors": ("📌 Конкуренты", []),
        "useful": ("💡 Полезное", []),
    }

    for i, item in enumerate(items):
        fmt = item.post_format
        if fmt not in sections:
            fmt = "useful"
        sections[fmt][1].append((i, item))

    buttons = []
    for fmt, (section_title, section_items) in sections.items():
        if not section_items:
            continue
        lines.append(f"\n<b>{section_title}</b>")
        row = []
        for i, item in section_items:
            title = item.title[:60] + ("..." if len(item.title) > 60 else "")
            lines.append(f"  {i+1}. {title}")
            row.append(InlineKeyboardButton(str(i+1), callback_data=f"pick_{i}"))
            if len(row) == 5:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

    buttons.append([
        InlineKeyboardButton("🔄 Обновить темы", callback_data="refresh_digest"),
        InlineKeyboardButton("📅 Контент-план", callback_data="show_plan"),
    ])
    buttons.append([
        InlineKeyboardButton("✍️ Написать тему вручную", callback_data="manual_topic"),
        InlineKeyboardButton("🎤 Голосовая", callback_data="voice_hint"),
    ])

    text = "\n".join(lines)
    return text, InlineKeyboardMarkup(buttons)


# ─── Handlers ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Дайджест тем", callback_data="show_digest")],
        [InlineKeyboardButton("📅 Контент-план недели", callback_data="show_plan")],
        [InlineKeyboardButton("📝 Мои мысли", callback_data="show_thoughts")],
    ])
    await update.message.reply_text(
        "Привет! Я помогаю вести канал @bazuevaconsalt.\n\n"
        "Что делаем?",
        reply_markup=kb,
    )


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Собираю дайджест...")
    await _send_digest(update.effective_chat.id, context.bot, msg.message_id)


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_plan(update.effective_chat.id, context.bot)


async def cmd_thoughts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_thoughts(update.effective_chat.id, context.bot)


async def _send_digest(chat_id: int, bot: Bot, edit_msg_id: int = None):
    loop = asyncio.get_event_loop()
    items = await loop.run_in_executor(None, _build_digest_blocking)
    context_data = {"digest_items": items}

    # Сохраняем items в drafts для доступа из callback
    drafts[f"digest_{chat_id}"] = items

    text, kb = _format_digest(items)
    if edit_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=edit_msg_id,
                text=text, reply_markup=kb, parse_mode="HTML",
            )
        except Exception:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML")
    else:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML")
    logger.info(f"Digest sent: {len(items)} topics")


async def _send_plan(chat_id: int, bot: Bot):
    plan = cp.get_or_create_weekly_plan()
    text = cp.format_plan_message(plan)
    topics = plan.get("topics", [])
    buttons = []
    days = ["Пн", "Вт", "Ср", "Чт", "Пт"]
    for i, topic in enumerate(topics):
        day = days[i] if i < len(days) else f"День {i+1}"
        buttons.append([InlineKeyboardButton(
            f"{day}: {topic[:40]}",
            callback_data=f"plan_topic_{i}"
        )])
    buttons.append([
        InlineKeyboardButton("✅ Утвердить план", callback_data="approve_plan"),
        InlineKeyboardButton("🔄 Новый план", callback_data="regen_plan"),
    ])
    await bot.send_message(
        chat_id=chat_id, text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


async def _send_thoughts(chat_id: int, bot: Bot):
    thoughts = load_thoughts()
    if not thoughts:
        await bot.send_message(chat_id=chat_id, text="У тебя пока нет сохранённых мыслей.\n\nОтправь голосовое сообщение — я сохраню и предложу написать пост.")
        return
    lines = ["📝 <b>Мои мысли</b>\n"]
    buttons = []
    for t in thoughts[-20:]:  # последние 20
        preview = t["text"][:80] + ("..." if len(t["text"]) > 80 else "")
        dt = t.get("created", "")[:10]
        lines.append(f"• {dt}: {preview}")
        buttons.append([InlineKeyboardButton(
            f"✍️ Пост из: {preview[:40]}",
            callback_data=f"thought_post_{t['id']}"
        )])
    text = "\n".join(lines)
    await bot.send_message(
        chat_id=chat_id, text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


def _draft_keyboard(show_card: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("✅ Опубликовать", callback_data="approve"),
            InlineKeyboardButton("🔄 Переписать", callback_data="rewrite"),
        ],
        [
            InlineKeyboardButton("✏️ Редактировать", callback_data="edit"),
            InlineKeyboardButton("🖼 Карточка", callback_data="gen_card"),
        ],
        [
            InlineKeyboardButton("⏭ Пропустить", callback_data="skip"),
            InlineKeyboardButton("📋 К дайджесту", callback_data="show_digest"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    # ── Дайджест ──────────────────────────────────────────────────────────
    if data == "show_digest":
        msg = await query.message.reply_text("⏳ Собираю дайджест...")
        await _send_digest(chat_id, context.bot, msg.message_id)
        return

    if data == "refresh_digest":
        await query.edit_message_text("⏳ Обновляю темы...")
        await _send_digest(chat_id, context.bot, query.message.message_id)
        return

    # ── Выбор темы из дайджеста ───────────────────────────────────────────
    if data.startswith("pick_"):
        idx = int(data.split("_")[1])
        items = drafts.get(f"digest_{chat_id}", [])
        if idx >= len(items):
            await query.message.reply_text("Тема не найдена. Обнови дайджест.")
            return
        item = items[idx]
        await query.message.reply_text(f"⏳ Пишу пост по теме:\n<i>{item.title[:100]}</i>", parse_mode="HTML")
        loop = asyncio.get_event_loop()
        post_text = await loop.run_in_executor(None, ct.transform, item)
        if not post_text:
            await query.message.reply_text("Не удалось написать пост. Попробуй другую тему.")
            return
        drafts[chat_id] = {"item": item, "post_text": post_text, "card_path": None}
        source_line = f"\n\n<i>Источник: {item.source}</i>" if item.source and item.source != "Контент-план" else ""
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{post_text}{source_line}",
            reply_markup=_draft_keyboard(),
            parse_mode="HTML",
        )
        return

    # ── Контент-план ──────────────────────────────────────────────────────
    if data == "show_plan":
        await _send_plan(chat_id, context.bot)
        return

    if data.startswith("plan_topic_"):
        idx = int(data.split("_")[-1])
        plan = cp.get_or_create_weekly_plan()
        topics = plan.get("topics", [])
        if idx >= len(topics):
            await query.message.reply_text("Тема не найдена.")
            return
        topic = topics[idx]
        await query.message.reply_text(f"⏳ Пишу пост по теме:\n<i>{topic}</i>", parse_mode="HTML")
        loop = asyncio.get_event_loop()
        post_text = await loop.run_in_executor(None, ct.transform_content_plan_topic, topic)
        if not post_text:
            await query.message.reply_text("Не удалось написать пост.")
            return
        from dataclasses import dataclass
        @dataclass
        class PlanItem:
            title: str
            url: str = ""
            summary: str = ""
            source: str = "Контент-план"
            post_format: str = "content_plan"
            hashtag: str = "#мысливслух"
        item = PlanItem(title=topic)
        drafts[chat_id] = {"item": item, "post_text": post_text, "card_path": None}
        await context.bot.send_message(
            chat_id=chat_id,
            text=post_text,
            reply_markup=_draft_keyboard(),
            parse_mode="HTML",
        )
        cp.mark_topic_used(topic)
        return

    if data == "approve_plan":
        cp.approve_plan()
        await query.message.reply_text("✅ Контент-план утверждён!")
        return

    if data == "regen_plan":
        await query.message.reply_text("⏳ Генерирую новый план на неделю...")
        # Сбрасываем план
        import content_plan as cp_mod
        if os.path.exists(cp_mod.PLAN_FILE):
            os.remove(cp_mod.PLAN_FILE)
        loop = asyncio.get_event_loop()
        plan = await loop.run_in_executor(None, cp.get_or_create_weekly_plan)
        await _send_plan(chat_id, context.bot)
        return

    # ── Мои мысли ─────────────────────────────────────────────────────────
    if data == "show_thoughts":
        await _send_thoughts(chat_id, context.bot)
        return

    if data.startswith("thought_post_"):
        thought_id = int(data.split("_")[-1])
        thoughts = load_thoughts()
        thought = next((t for t in thoughts if t["id"] == thought_id), None)
        if not thought:
            await query.message.reply_text("Мысль не найдена.")
            return
        await query.message.reply_text("⏳ Пишу пост из твоей заметки...")
        loop = asyncio.get_event_loop()
        post_text = await loop.run_in_executor(None, ct.transform_voice_note, thought["text"])
        if not post_text:
            await query.message.reply_text("Не удалось написать пост.")
            return
        from dataclasses import dataclass
        @dataclass
        class VoiceItem:
            title: str
            url: str = ""
            summary: str = ""
            source: str = "Голосовая заметка"
            post_format: str = "voice_note"
            hashtag: str = "#мысливслух"
        item = VoiceItem(title=thought["text"][:80])
        drafts[chat_id] = {"item": item, "post_text": post_text, "card_path": None}
        await context.bot.send_message(
            chat_id=chat_id,
            text=post_text,
            reply_markup=_draft_keyboard(),
            parse_mode="HTML",
        )
        return

    # ── Ручной ввод темы ──────────────────────────────────────────────────
    if data == "manual_topic":
        context.user_data["awaiting"] = "manual_topic"
        await query.message.reply_text(
            "✍️ Напиши тему поста — одним предложением.\n\n"
            "Например: <i>Почему предприниматели боятся делегировать</i>",
            parse_mode="HTML",
        )
        return

    if data == "voice_hint":
        await query.message.reply_text(
            "🎤 Просто отправь голосовое сообщение — я транскрибирую и предложу написать пост."
        )
        return

    # ── Действия с черновиком ─────────────────────────────────────────────
    if data == "approve":
        draft = drafts.get(chat_id)
        if not draft:
            await query.message.reply_text("Черновик не найден.")
            return
        post_text = draft["post_text"]
        card_path = draft.get("card_path")
        try:
            if card_path and os.path.exists(card_path):
                with open(card_path, "rb") as f:
                    await context.bot.send_photo(
                        chat_id=CHANNEL_ID,
                        photo=f,
                        caption=post_text,
                        parse_mode="HTML",
                    )
            else:
                await context.bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=post_text,
                    parse_mode="HTML",
                )
            # Отметить как использованное
            item = draft.get("item")
            if item:
                seen = load_seen()
                seen.add(item.url or item.title[:50])
                save_seen(seen)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("✅ Опубликовано в канал!")
        except Exception as e:
            logger.error(f"Publish failed: {e}")
            await query.message.reply_text(f"Ошибка публикации: {e}")
        return

    if data == "rewrite":
        draft = drafts.get(chat_id)
        if not draft:
            await query.message.reply_text("Черновик не найден.")
            return
        await query.message.reply_text("⏳ Переписываю...")
        loop = asyncio.get_event_loop()
        post_text = await loop.run_in_executor(None, ct.transform, draft["item"])
        if not post_text:
            await query.message.reply_text("Не удалось переписать.")
            return
        draft["post_text"] = post_text
        draft["card_path"] = None
        await context.bot.send_message(
            chat_id=chat_id,
            text=post_text,
            reply_markup=_draft_keyboard(),
            parse_mode="HTML",
        )
        return

    if data == "edit":
        context.user_data["awaiting"] = "edit_post"
        await query.message.reply_text(
            "✏️ Отправь отредактированный текст поста:"
        )
        return

    if data == "skip":
        draft = drafts.pop(chat_id, None)
        if draft and draft.get("item"):
            seen = load_seen()
            seen.add(draft["item"].url or draft["item"].title[:50])
            save_seen(seen)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Пропущено. Напиши /digest для нового дайджеста.")
        return

    # ── Карточка ──────────────────────────────────────────────────────────
    if data == "gen_card":
        draft = drafts.get(chat_id)
        if not draft:
            await query.message.reply_text("Черновик не найден.")
            return
        await query.message.reply_text("⏳ Генерирую карточку...")
        try:
            from card_generator import generate_card
            item = draft["item"]
            card_path = generate_card(
                title=item.title,
                hashtag=item.hashtag,
                source=item.source,
            )
            draft["card_path"] = card_path
            with open(card_path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=f,
                    caption="Карточка готова. Нажми «Опубликовать» чтобы отправить с карточкой.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📤 Опубликовать с карточкой", callback_data="approve"),
                        InlineKeyboardButton("📤 Без карточки", callback_data="approve_no_card"),
                    ]]),
                )
        except Exception as e:
            logger.error(f"Card generation failed: {e}")
            await query.message.reply_text(f"Не удалось создать карточку: {e}")
        return

    if data == "approve_no_card":
        draft = drafts.get(chat_id)
        if draft:
            draft["card_path"] = None
        # Переиспользуем approve
        query.data = "approve"
        await on_callback(update, context)
        return


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений и голосовых заметок."""
    if update.effective_chat.id != ADMIN_ID:
        return

    # Голосовое сообщение
    if update.message.voice or update.message.audio:
        voice = update.message.voice or update.message.audio
        await update.message.reply_text("🎤 Транскрибирую...")
        try:
            file = await context.bot.get_file(voice.file_id)
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                tmp_path = tmp.name
            result = subprocess.run(
                ["manus-speech-to-text", tmp_path],
                capture_output=True, text=True, timeout=120,
            )
            transcript = result.stdout.strip()
            os.unlink(tmp_path)
            if not transcript:
                await update.message.reply_text("Не удалось распознать речь.")
                return
            await update.message.reply_text(
                f"📝 Распознано:\n\n<i>{transcript}</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✍️ Написать пост", callback_data=f"voice_to_post_{add_thought(transcript)}"),
                        InlineKeyboardButton("💾 Сохранить мысль", callback_data="voice_saved"),
                    ],
                    [InlineKeyboardButton("📝 Мои мысли", callback_data="show_thoughts")],
                ]),
            )
        except Exception as e:
            logger.error(f"Voice transcription failed: {e}")
            await update.message.reply_text(f"Ошибка транскрипции: {e}")
        return

    # Ожидание ввода
    awaiting = context.user_data.get("awaiting")

    if awaiting == "manual_topic":
        context.user_data.pop("awaiting")
        topic = update.message.text.strip()
        await update.message.reply_text(f"⏳ Пишу пост по теме:\n<i>{topic}</i>", parse_mode="HTML")
        loop = asyncio.get_event_loop()
        post_text = await loop.run_in_executor(None, ct.transform_content_plan_topic, topic)
        if not post_text:
            await update.message.reply_text("Не удалось написать пост.")
            return
        from dataclasses import dataclass
        @dataclass
        class ManualItem:
            title: str
            url: str = ""
            summary: str = ""
            source: str = "Ручной ввод"
            post_format: str = "content_plan"
            hashtag: str = "#мысливслух"
        item = ManualItem(title=topic)
        drafts[update.effective_chat.id] = {"item": item, "post_text": post_text, "card_path": None}
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=post_text,
            reply_markup=_draft_keyboard(),
            parse_mode="HTML",
        )
        return

    if awaiting == "edit_post":
        context.user_data.pop("awaiting")
        chat_id = update.effective_chat.id
        new_text = update.message.text.strip()
        if chat_id in drafts:
            drafts[chat_id]["post_text"] = new_text
        await context.bot.send_message(
            chat_id=chat_id,
            text=new_text,
            reply_markup=_draft_keyboard(),
            parse_mode="HTML",
        )
        return


async def on_voice_to_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отдельный обработчик для voice_to_post_ чтобы не перегружать on_callback."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    if data.startswith("voice_to_post_"):
        thought_id = int(data.split("_")[-1])
        thoughts = load_thoughts()
        thought = next((t for t in thoughts if t["id"] == thought_id), None)
        if not thought:
            await query.message.reply_text("Заметка не найдена.")
            return
        await query.message.reply_text("⏳ Пишу пост из голосовой заметки...")
        loop = asyncio.get_event_loop()
        post_text = await loop.run_in_executor(None, ct.transform_voice_note, thought["text"])
        if not post_text:
            await query.message.reply_text("Не удалось написать пост.")
            return
        from dataclasses import dataclass
        @dataclass
        class VoiceItem:
            title: str
            url: str = ""
            summary: str = ""
            source: str = "Голосовая заметка"
            post_format: str = "voice_note"
            hashtag: str = "#мысливслух"
        item = VoiceItem(title=thought["text"][:80])
        drafts[chat_id] = {"item": item, "post_text": post_text, "card_path": None}
        await context.bot.send_message(
            chat_id=chat_id,
            text=post_text,
            reply_markup=_draft_keyboard(),
            parse_mode="HTML",
        )
        return

    if data == "voice_saved":
        await query.answer("💾 Сохранено в Мои мысли")
        return


# ─── Daily digest scheduler ───────────────────────────────────────────────

async def daily_digest_job(bot: Bot):
    """Ежедневный дайджест в 09:00 Бали (01:00 UTC)."""
    logger.info("Running daily digest job")
    await _send_digest(ADMIN_ID, bot)


# ─── Weekly plan scheduler ────────────────────────────────────────────────

async def weekly_plan_job(bot: Bot):
    """Генерация контент-плана в понедельник в 08:00 Бали (00:00 UTC)."""
    logger.info("Running weekly plan job")
    # Сбрасываем старый план
    if os.path.exists(cp.PLAN_FILE):
        os.remove(cp.PLAN_FILE)
    loop = asyncio.get_event_loop()
    plan = await loop.run_in_executor(None, cp.get_or_create_weekly_plan)
    await _send_plan(ADMIN_ID, bot)
    logger.info("Weekly plan sent")


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("thoughts", cmd_thoughts))

    # Callbacks
    app.add_handler(CallbackQueryHandler(on_voice_to_post_callback, pattern="^voice_to_post_|^voice_saved$"))
    app.add_handler(CallbackQueryHandler(on_callback))

    # Messages
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND | filters.VOICE | filters.AUDIO,
        on_message,
    ))

    # Scheduler — запускаем после старта event loop через post_init
    async def post_init(application):
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            daily_digest_job,
            CronTrigger(hour=1, minute=0),  # 09:00 Бали
            args=[application.bot],
            id="daily_digest",
            misfire_grace_time=3600,
        )
        scheduler.add_job(
            weekly_plan_job,
            CronTrigger(day_of_week="mon", hour=0, minute=0),  # Пн 08:00 Бали
            args=[application.bot],
            id="weekly_plan",
            misfire_grace_time=3600,
        )
        scheduler.start()
        logger.info("Scheduler started")

    app.post_init = post_init

    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
