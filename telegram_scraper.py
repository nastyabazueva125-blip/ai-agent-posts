"""
telegram_scraper.py — парсинг публичных постов из Telegram-каналов через t.me/s/

Каналы-референсы:
  Бизнес/продажи: @grebenukm, @big_bad_coach
  AI/нейросети:   @prompt_design, @llm_under_hood, @promtolog, @ai_for_business
"""

import re
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

MAX_AGE_DAYS = 90  # TG-каналы: смотрим за последние 3 месяца
MIN_TEXT_LEN = 80   # минимальная длина поста (игнорируем слишком короткие)
MAX_TEXT_LEN = 3000 # обрезаем слишком длинные

# Каналы-референсы с метаданными
TG_CHANNELS = [
    {
        "username": "grebenukm",
        "name": "Михаил Гребенюк",
        "hashtag": "#мысливслух",
        "post_format": "morning_insight",
    },
    {
        "username": "big_bad_coach",
        "name": "Big Bad Coach",
        "hashtag": "#воронкиипродажи",
        "post_format": "afternoon_practice",
    },
    {
        "username": "prompt_design",
        "name": "Силиконовый Мешок",
        "hashtag": "#aiдлябизнеса",
        "post_format": "tool",
    },
    {
        "username": "llm_under_hood",
        "name": "LLM под капотом",
        "hashtag": "#aiдлябизнеса",
        "post_format": "tool",
    },
    {
        "username": "promtolog",
        "name": "Промтолог",
        "hashtag": "#tools",
        "post_format": "tool",
    },
    {
        "username": "ai_for_business",
        "name": "AI для бизнеса",
        "hashtag": "#aiдлябизнеса",
        "post_format": "tool",
    },
]


def _parse_tg_date(date_str: Optional[str]) -> Optional[datetime]:
    """Парсит дату из атрибута datetime тега <time>."""
    if not date_str:
        return None
    try:
        # Формат: 2024-04-18T12:34:56+00:00
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _clean_text(text: str) -> str:
    """Очистить текст поста от лишних пробелов и артефактов."""
    text = re.sub(r'\s+', ' ', text).strip()
    # Убрать типичные служебные фразы
    for phrase in ["Channel created", "Канал создан", "Forwarded from"]:
        text = text.replace(phrase, "").strip()
    return text


def fetch_tg_channel(channel: dict, max_items: int = 10) -> list:
    """
    Получить свежие посты из публичного Telegram-канала через t.me/s/{username}.
    Возвращает список ContentItem-совместимых словарей.
    """
    from content_sources import ContentItem

    username = channel.get("username") or channel.get("handle")
    url = f"https://t.me/s/{username}"
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"TG @{username}: HTTP {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        messages = soup.find_all("div", class_="tgme_widget_message_wrap")

        for msg in messages:
            # Дата поста
            time_tag = msg.find("time")
            dt = _parse_tg_date(time_tag.get("datetime") if time_tag else None)

            # Фильтр по возрасту
            if dt and dt < cutoff:
                continue

            # Текст поста
            text_div = msg.find("div", class_="tgme_widget_message_text")
            if not text_div:
                continue

            raw_text = text_div.get_text(separator=" ", strip=True)
            text = _clean_text(raw_text)

            if len(text) < MIN_TEXT_LEN:
                continue

            # Ссылка на пост
            post_link = msg.find("a", class_="tgme_widget_message_date")
            post_url = post_link.get("href", url) if post_link else url

            # Обрезаем текст для summary
            summary = text[:MAX_TEXT_LEN]

            # Заголовок = первые 100 символов текста
            title = text[:100].rstrip(".,!?…") + ("…" if len(text) > 100 else "")

            published_fmt = dt.strftime("%d.%m.%Y") if dt else ""

            items.append(ContentItem(
                title=title,
                url=post_url,
                summary=summary,
                source=channel["name"],
                post_format=channel.get("post_format", "useful"),
                hashtag=channel["hashtag"],
                published=published_fmt,
                published_dt=dt,
            ))

            if len(items) >= max_items:
                break

        logger.info(f"TG @{username}: {len(items)} fresh posts (≤{MAX_AGE_DAYS}d)")

    except Exception as e:
        logger.error(f"TG @{username}: fetch error — {e}")

    return items


def fetch_all_tg_channels(max_per_channel: int = 5) -> list:
    """
    Собрать свежие посты из всех Telegram-каналов-референсов.
    Возвращает перемешанный список ContentItem.
    """
    import random
    all_items = []

    for channel in TG_CHANNELS:
        try:
            items = fetch_tg_channel(channel, max_items=max_per_channel)
            all_items.extend(items)
            time.sleep(0.5)  # небольшая пауза между запросами
        except Exception as e:
            logger.error(f"TG channel {channel['username']} failed: {e}")

    # Сортировка по дате — сначала свежие
    all_items.sort(
        key=lambda x: x.published_dt or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    logger.info(f"TG channels total: {len(all_items)} fresh posts from {len(TG_CHANNELS)} channels")
    return all_items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    items = fetch_all_tg_channels(max_per_channel=3)
    print(f"\nВсего постов: {len(items)}\n")
    for i, item in enumerate(items[:6], 1):
        print(f"{i}. [{item.source}] {item.title[:80]}")
        print(f"   {item.url}")
        print(f"   {item.published} | {item.hashtag}")
        print()
