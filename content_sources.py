"""
content_sources.py — модуль сбора контента из RSS-лент и AI-директорий.
Источники: Justin Welsh, Codie Sanchez, Sahil Bloom, Growth Unhinged,
           Alex Hormozi (YouTube RSS), Product Hunt, TheresAnAIForThat

Фильтрация: берём только посты за последние 7 дней.
"""

import requests
import feedparser
import logging
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import time

logger = logging.getLogger(__name__)

# Максимальный возраст поста в днях
MAX_AGE_DAYS = 7


@dataclass
class ContentItem:
    title: str
    url: str
    summary: str
    source: str
    post_format: str  # morning_insight | afternoon_practice | evening_case | tool
    hashtag: str
    published: Optional[str] = None
    published_dt: Optional[datetime] = None  # для сортировки по свежести


# ─── RSS-ленты по форматам ─────────────────────────────────────────────────

RSS_SOURCES = {
    "morning_insight": [
        {"name": "Sahil Bloom", "url": "https://www.sahilbloom.com/newsletter/rss.xml", "hashtag": "#мысливслух"},
        {"name": "Seth Godin", "url": "https://feeds.feedblitz.com/sethsblog", "hashtag": "#мысливслух"},
        {"name": "Duct Tape Marketing", "url": "https://ducttapemarketing.com/feed/", "hashtag": "#мысливслух"},
    ],
    "afternoon_practice": [
        {"name": "Neil Patel", "url": "https://neilpatel.com/blog/feed/", "hashtag": "#воронкиипродажи"},
        {"name": "HubSpot Sales", "url": "https://blog.hubspot.com/sales/rss.xml", "hashtag": "#воронкиипродажи"},
        {"name": "Smart Passive Income", "url": "https://www.smartpassiveincome.com/blog/feed/", "hashtag": "#операционка"},
        {"name": "Demand Curve", "url": "https://www.demandcurve.com/blog/rss.xml", "hashtag": "#воронкиипродажи"},
    ],
    "evening_case": [
        {"name": "Trends.vc", "url": "https://trends.vc/feed/", "hashtag": "#разборкейса"},
        {"name": "Inc Magazine", "url": "https://www.inc.com/rss/homepage.xml", "hashtag": "#разборкейса"},
        {"name": "Backlinko", "url": "https://backlinko.com/feed", "hashtag": "#разборкейса"},
    ],
    "tool": [
        {"name": "Zapier Blog", "url": "https://zapier.com/blog/feeds/latest/", "hashtag": "#полезняшка"},
        {"name": "Buffer Blog", "url": "https://buffer.com/resources/feed/", "hashtag": "#полезняшка"},
        {"name": "Product Hunt AI", "url": "https://www.producthunt.com/feed?category=artificial-intelligence", "hashtag": "#aiдлябизнеса"},
    ],
}

# Fallback RSS (всегда работают, тоже фильтруются по дате)
FALLBACK_RSS = {
    "morning_insight": [
        {
            "name": "Hacker News (Ask HN)",
            "url": "https://hnrss.org/ask",
            "hashtag": "#мысливслух",
        }
    ],
    "afternoon_practice": [
        {
            "name": "Zapier Blog",
            "url": "https://zapier.com/blog/feeds/latest/",
            "hashtag": "#операционка",
        }
    ],
    "evening_case": [
        {
            "name": "Hacker News (Show HN)",
            "url": "https://hnrss.org/show",
            "hashtag": "#разборкейса",
        }
    ],
    "tool": [
        {
            "name": "Product Hunt Daily",
            "url": "https://www.producthunt.com/feed",
            "hashtag": "#полезняшка",
        }
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ContentBot/1.0; +https://bazuevaconsalt.ru)"
}


def _parse_date(entry) -> Optional[datetime]:
    """Попытаться извлечь дату публикации из RSS-записи."""
    raw_date = entry.get("published", "") or entry.get("updated", "")

    # Метод 1: стандартный RFC 2822 (большинство RSS)
    if raw_date:
        try:
            return parsedate_to_datetime(raw_date).astimezone(timezone.utc)
        except Exception:
            pass

    # Метод 2: через published_parsed (feedparser struct_time)
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
        except Exception:
            pass

    return None


def _is_fresh(dt: Optional[datetime], max_age_days: int = MAX_AGE_DAYS) -> bool:
    """Вернуть True если пост не старше max_age_days дней."""
    if dt is None:
        # Если дата неизвестна — пропускаем (считаем устаревшим)
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    return dt >= cutoff


def _fetch_rss(source: dict, post_format: str, max_items: int = 10) -> list[ContentItem]:
    """Получить свежие записи из RSS-ленты (только за последние 7 дней)."""
    items = []
    try:
        resp = requests.get(source["url"], headers=HEADERS, timeout=10)
        feed = feedparser.parse(resp.content)

        skipped_old = 0
        for entry in feed.entries[:max_items * 3]:  # берём больше, т.к. будем фильтровать
            # Парсим дату
            dt = _parse_date(entry)

            # Фильтр по свежести
            if not _is_fresh(dt):
                skipped_old += 1
                continue

            # Форматируем дату для отображения
            published_fmt = dt.strftime("%d.%m.%Y") if dt else ""

            # Извлекаем текст
            summary = ""
            if hasattr(entry, "summary"):
                summary = entry.summary[:800]
            elif hasattr(entry, "content"):
                summary = entry.content[0].value[:800]

            items.append(ContentItem(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                summary=summary,
                source=source["name"],
                post_format=post_format,
                hashtag=source["hashtag"],
                published=published_fmt,
                published_dt=dt,
            ))

            if len(items) >= max_items:
                break

        if skipped_old:
            logger.debug(f"{source['name']}: skipped {skipped_old} posts older than {MAX_AGE_DAYS} days")

    except Exception as e:
        logger.warning(f"RSS fetch failed for {source['name']}: {e}")
    return items


def fetch_for_slot(post_format: str, max_items: int = 10) -> list[ContentItem]:
    """
    Собрать свежий контент (за последние 7 дней) для конкретного временного слота.
    post_format: morning_insight | afternoon_practice | evening_case | tool
    """
    items = []
    sources = RSS_SOURCES.get(post_format, [])
    fallbacks = FALLBACK_RSS.get(post_format, [])

    for source in sources:
        fetched = _fetch_rss(source, post_format, max_items=5)
        items.extend(fetched)
        time.sleep(0.5)

    # Если основные источники дали мало свежего — добираем из fallback
    if len(items) < 3:
        logger.info(f"Using fallback sources for {post_format} (only {len(items)} fresh items found)")
        for source in fallbacks:
            fetched = _fetch_rss(source, post_format, max_items=8)
            items.extend(fetched)

    # Убираем пустые записи
    items = [i for i in items if i.title and i.url]

    # Сортируем по дате — сначала самые свежие
    items.sort(key=lambda x: x.published_dt or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    fresh_count = len(items)
    logger.info(f"Fetched {fresh_count} fresh items (≤{MAX_AGE_DAYS}d) for slot '{post_format}'")

    return items[:max_items]


def fetch_all_slots() -> dict[str, list[ContentItem]]:
    """Собрать контент для всех слотов сразу."""
    result = {}
    for slot in ["morning_insight", "afternoon_practice", "evening_case", "tool"]:
        result[slot] = fetch_for_slot(slot)
    return result
