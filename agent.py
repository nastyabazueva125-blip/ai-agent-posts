#!/usr/bin/env python3
"""
AI Content Curator Agent
Finds trending Reddit posts → rewrites with Claude → publishes to Telegram.
"""

import json
import logging
import os
import schedule
import time

import config
from reddit_client import fetch_posts
from content_transformer import transform_post
from telegram_client import publish_to_channel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

SEEN_IDS_FILE = "seen_ids.json"


def load_seen_ids() -> set[str]:
    if os.path.exists(SEEN_IDS_FILE):
        with open(SEEN_IDS_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen_ids(seen_ids: set[str]) -> None:
    with open(SEEN_IDS_FILE, "w") as f:
        json.dump(list(seen_ids), f)


def run_agent() -> None:
    logger.info("Agent run started")
    seen_ids = load_seen_ids()

    posts = fetch_posts(seen_ids)
    logger.info("Fetched %d candidate posts", len(posts))

    published = 0
    for post in posts:
        if published >= config.MAX_POSTS_PER_RUN:
            break

        logger.info("Transforming: %s (r/%s, %d upvotes)", post.title[:60], post.subreddit, post.upvotes)
        transformed = transform_post(post)

        if not transformed:
            logger.warning("Transformation returned empty result, skipping")
            seen_ids.add(post.post_id)
            continue

        success = publish_to_channel(transformed)
        if success:
            logger.info("Published post %s", post.post_id)
            seen_ids.add(post.post_id)
            published += 1
        else:
            logger.error("Failed to publish post %s", post.post_id)

    save_seen_ids(seen_ids)
    logger.info("Agent run finished. Published %d/%d posts", published, config.MAX_POSTS_PER_RUN)


def main() -> None:
    logger.info(
        "Starting AI Content Curator. Interval: %d min, max %d posts/run",
        config.POST_INTERVAL_MINUTES,
        config.MAX_POSTS_PER_RUN,
    )
    logger.info("Subreddits: %s", config.SUBREDDITS)
    logger.info("Keywords: %s", config.KEYWORDS)

    run_agent()

    schedule.every(config.POST_INTERVAL_MINUTES).minutes.do(run_agent)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
