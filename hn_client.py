"""
Hacker News client — замена reddit_client.py.
Использует официальный Firebase REST API (без ключей, без регистрации).
"""
from __future__ import annotations

import requests
from dataclasses import dataclass
from typing import Optional

import config

HN_BASE = "https://hacker-news.firebaseio.com/v0"
TIMEOUT = 10


@dataclass
class HNPost:
    title: str
    text: str
    url: str
    source: str          # аналог subreddit — категория/тег
    upvotes: int
    post_id: str


def _get_json(url: str) -> Optional[dict]:
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _is_relevant(post: dict) -> bool:
    """Проверяем заголовок на ключевые слова из config."""
    title = (post.get("title") or "").lower()
    text  = (post.get("text")  or "").lower()
    combined = title + " " + text
    return any(kw.lower() in combined for kw in config.KEYWORDS)


def _fetch_story(story_id: int) -> Optional[HNPost]:
    data = _get_json(f"{HN_BASE}/item/{story_id}.json")
    if not data:
        return None
    if data.get("type") != "story":
        return None
    if data.get("dead") or data.get("deleted"):
        return None

    score = data.get("score", 0)
    if score < config.MIN_UPVOTES:
        return None

    title = data.get("title", "")
    text  = data.get("text", "") or ""          # только у Ask HN есть текст
    url   = data.get("url") or f"https://news.ycombinator.com/item?id={story_id}"

    # Определяем «категорию» по типу поста
    if title.startswith("Ask HN"):
        source = "Ask HN"
    elif title.startswith("Show HN"):
        source = "Show HN"
    else:
        source = "HN Top"

    return HNPost(
        title=title,
        text=text[:2000],
        url=url,
        source=source,
        upvotes=score,
        post_id=str(story_id),
    )


def fetch_posts(seen_ids: set[str]) -> list[HNPost]:
    """
    Загружает топ-500 историй HN, фильтрует по ключевым словам и MIN_UPVOTES.
    Возвращает не более MAX_POSTS_PER_RUN * 3 релевантных постов.
    """
    ids = _get_json(f"{HN_BASE}/topstories.json") or []
    results: list[HNPost] = []
    limit = config.MAX_POSTS_PER_RUN * 3

    for story_id in ids[:500]:
        if str(story_id) in seen_ids:
            continue
        data = _get_json(f"{HN_BASE}/item/{story_id}.json")
        if not data:
            continue
        if not _is_relevant(data):
            continue
        post = _fetch_story(story_id)
        if post:
            results.append(post)
        if len(results) >= limit:
            break

    return results
