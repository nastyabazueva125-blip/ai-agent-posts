"""
Источники контента для бота @bazuevaconsalt.

4 рубрики:
  - tools       : Product Hunt (RSS) — новые инструменты для бизнеса
  - competitors : TG-каналы конкурентов/коллег (@grebenukm, @big_bad_coach, @llm_under_hood)
  - useful      : TG-каналы полезного контента (@promtolog, @ai_for_business, @prompt_design)

Рубрика "observations" (Мои наблюдения) — только голосовые заметки / ручной ввод, здесь не нужна.
Рубрика "content_plan" — генерируется агентом в content_plan.py, здесь не нужна.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import feedparser
import requests

logger = logging.getLogger(__name__)

MAX_AGE_DAYS = 7   # RSS (Product Hunt) — только свежее за неделю

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ContentBot/1.0; +https://bazuevaconsalt.ru)"
}


@dataclass
class ContentItem:
    title: str
    url: str
    summary: str
    source: str
    post_format: str          # tools | competitors | useful | content_plan | voice_note
    hashtag: str
    published: str = ""
    published_dt: Optional[datetime] = field(default=None, repr=False)


# ─── Product Hunt RSS (рубрика Tools) ─────────────────────────────────────

TOOLS_RSS = [
    {
        "name": "Product Hunt",
        "url": "https://www.producthunt.com/feed",
        "hashtag": "#tools",
    },
]


# ─── TG-каналы конкурентов/коллег (рубрика Конкуренты) ────────────────────

TG_COMPETITORS = [
    {"handle": "grebenukm",    "name": "Михаил Гребенюк",  "hashtag": "#воронкиипродажи"},
    {"handle": "big_bad_coach","name": "Big Bad Coach",     "hashtag": "#мысливслух"},
    {"handle": "llm_under_hood","name": "LLM под капотом",  "hashtag": "#aiдлябизнеса"},
]

# ─── TG-каналы полезного контента (рубрика Полезное/Tools AI) ─────────────

TG_USEFUL = [
    {"handle": "promtolog",      "name": "Промтолог",         "hashtag": "#tools"},
    {"handle": "ai_for_business","name": "AI для бизнеса",    "hashtag": "#aiдлябизнеса"},
    {"handle": "prompt_design",  "name": "Силиконовый Мешок", "hashtag": "#aiдлябизнеса"},
]


# ─── RSS helpers ──────────────────────────────────────────────────────────

def _parse_date(entry) -> Optional[datetime]:
    raw_date = entry.get("published", "") or entry.get("updated", "")
    if raw_date:
        try:
            return parsedate_to_datetime(raw_date).astimezone(timezone.utc)
        except Exception:
            pass
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def _is_fresh(dt: Optional[datetime], max_age_days: int = MAX_AGE_DAYS) -> bool:
    if dt is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    return dt >= cutoff


def _fetch_rss(source: dict, post_format: str, max_items: int = 10) -> list:
    items = []
    try:
        resp = requests.get(source["url"], headers=HEADERS, timeout=10)
        feed = feedparser.parse(resp.content)
        for entry in feed.entries[:max_items * 3]:
            dt = _parse_date(entry)
            if not _is_fresh(dt):
                continue
            published_fmt = dt.strftime("%d.%m.%Y") if dt else ""
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
    except Exception as e:
        logger.warning(f"RSS fetch failed for {source['name']}: {e}")
    return items


def fetch_tools_rss(max_items: int = 5) -> list:
    """Получить свежие продукты с Product Hunt."""
    items = []
    for source in TOOLS_RSS:
        fetched = _fetch_rss(source, "tools", max_items=max_items)
        items.extend(fetched)
        time.sleep(0.3)
    items = [i for i in items if i.title and i.url]
    items.sort(
        key=lambda x: x.published_dt or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    logger.info(f"Product Hunt: {len(items)} fresh items")
    return items[:max_items]


# ─── Backward compat: fetch_for_slot (используется в on_rewrite) ──────────

def fetch_for_slot(post_format: str, max_items: int = 10) -> list:
    """Совместимость со старым кодом — теперь только tools через Product Hunt."""
    if post_format == "tools" or post_format == "tool":
        return fetch_tools_rss(max_items=max_items)
    return []
