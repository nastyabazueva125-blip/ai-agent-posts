"""
content_sources.py — модуль сбора контента из RSS-лент и AI-директорий.
Источники: Justin Welsh, Codie Sanchez, Sahil Bloom, Growth Unhinged,
           Alex Hormozi (YouTube RSS), Product Hunt, TheresAnAIForThat
"""

import requests
import feedparser
import logging
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone
import time

logger = logging.getLogger(__name__)


@dataclass
class ContentItem:
    title: str
    url: str
    summary: str
    source: str
    post_format: str  # morning_insight | afternoon_practice | evening_case | tool
    hashtag: str
    published: Optional[str] = None


# ─── RSS-ленты по форматам ─────────────────────────────────────────────────

RSS_SOURCES = {
    # Утренний инсайт — мысли о бизнесе и мышлении
    "morning_insight": [
        {
            "name": "Sahil Bloom (Curiosity Chronicle)",
            "url": "https://www.sahilbloom.com/newsletter/rss.xml",
            "hashtag": "#мысливслух",
        },
        {
            "name": "James Clear (Atomic Habits)",
            "url": "https://jamesclear.com/feed",
            "hashtag": "#мысливслух",
        },
        {
            "name": "Paul Graham Essays",
            "url": "https://www.aaronsw.com/2002/feeds/pgessays.rss",
            "hashtag": "#мысливслух",
        },
    ],
    # Дневной пост — практика, воронки, операционка
    "afternoon_practice": [
        {
            "name": "Justin Welsh (Saturday Solopreneur)",
            "url": "https://www.justinwelsh.me/rss",
            "hashtag": "#воронкиипродажи",
        },
        {
            "name": "Growth Unhinged",
            "url": "https://www.growthunhinged.com/feed",
            "hashtag": "#воронкиипродажи",
        },
        {
            "name": "Lenny's Newsletter",
            "url": "https://www.lennysnewsletter.com/feed",
            "hashtag": "#операционка",
        },
        {
            "name": "HubSpot Marketing Blog",
            "url": "https://blog.hubspot.com/marketing/rss.xml",
            "hashtag": "#воронкиипродажи",
        },
    ],
    # Вечерний кейс — разборы бизнесов и стратегий
    "evening_case": [
        {
            "name": "Codie Sanchez (Contrarian Thinking)",
            "url": "https://www.contrarianthinking.co/feed",
            "hashtag": "#разборкейса",
        },
        {
            "name": "Indie Hackers",
            "url": "https://www.indiehackers.com/feed.rss",
            "hashtag": "#разборкейса",
        },
        {
            "name": "First Round Review",
            "url": "https://review.firstround.com/feed.xml",
            "hashtag": "#разборкейса",
        },
    ],
    # Полезняшка — AI-инструменты и сервисы
    "tool": [
        {
            "name": "Product Hunt (AI Tools)",
            "url": "https://www.producthunt.com/feed?category=artificial-intelligence",
            "hashtag": "#полезняшка",
        },
        {
            "name": "Ben's Bites (AI Newsletter)",
            "url": "https://bensbites.beehiiv.com/feed",
            "hashtag": "#aiдлябизнеса",
        },
        {
            "name": "The Rundown AI",
            "url": "https://www.therundown.ai/rss",
            "hashtag": "#aiдлябизнеса",
        },
    ],
}

# Fallback RSS (всегда работают)
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


def _fetch_rss(source: dict, post_format: str, max_items: int = 5) -> list[ContentItem]:
    """Получить последние записи из RSS-ленты."""
    items = []
    try:
        resp = requests.get(source["url"], headers=HEADERS, timeout=10)
        feed = feedparser.parse(resp.content)
        for entry in feed.entries[:max_items]:
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
                published=entry.get("published", ""),
            ))
    except Exception as e:
        logger.warning(f"RSS fetch failed for {source['name']}: {e}")
    return items


def fetch_for_slot(post_format: str, max_items: int = 10) -> list[ContentItem]:
    """
    Собрать контент для конкретного временного слота.
    post_format: morning_insight | afternoon_practice | evening_case | tool
    """
    items = []
    sources = RSS_SOURCES.get(post_format, [])
    fallbacks = FALLBACK_RSS.get(post_format, [])

    for source in sources:
        fetched = _fetch_rss(source, post_format, max_items=3)
        items.extend(fetched)
        time.sleep(0.5)

    # Если основные источники дали мало — добираем из fallback
    if len(items) < 3:
        logger.info(f"Using fallback sources for {post_format}")
        for source in fallbacks:
            fetched = _fetch_rss(source, post_format, max_items=5)
            items.extend(fetched)

    # Фильтрация: убираем пустые записи
    items = [i for i in items if i.title and i.url]
    logger.info(f"Fetched {len(items)} items for slot '{post_format}'")
    return items[:max_items]


def fetch_all_slots() -> dict[str, list[ContentItem]]:
    """Собрать контент для всех слотов сразу."""
    result = {}
    for slot in ["morning_insight", "afternoon_practice", "evening_case", "tool"]:
        result[slot] = fetch_for_slot(slot)
    return result
