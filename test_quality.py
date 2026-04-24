"""Тест качества генерации постов."""
import os
import sys
sys.path.insert(0, '.')

# GROQ_API_KEY must be set in environment
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("TELEGRAM_CHANNEL_ID", "dummy")
os.environ.setdefault("TELEGRAM_ADMIN_CHAT_ID", "0")

import content_transformer as ct
import content_plan as cp
from content_sources import ContentItem

print("=" * 60)
print("1. ТЕСТ: Генерация тем контент-плана")
print("=" * 60)
topics = cp.generate_weekly_plan()
for i, t in enumerate(topics, 1):
    print(f"  {i}. {t}")

print()
print("=" * 60)
print("2. ТЕСТ: Пост по теме контент-плана")
print("=" * 60)
topic = topics[0] if topics else "Почему предприниматель создаёт продукт ради продукта, а не для клиента"
item = ContentItem(
    title=topic,
    url="",
    summary="",
    source="Контент-план",
    post_format="content_plan",
    hashtag="#мысливслух",
)
post = ct.transform(item)
print(post)

print()
print("=" * 60)
print("3. ТЕСТ: Пост по посту конкурента (@grebenukm)")
print("=" * 60)
import telegram_scraper as ts
import content_sources as cs
comp_posts = ts.fetch_tg_channel(cs.TG_COMPETITORS[0], max_items=3)
if comp_posts:
    comp_posts[0].post_format = "competitors"
    post2 = ct.transform(comp_posts[0])
    print(f"Источник: {comp_posts[0].source}")
    print(f"Оригинал: {comp_posts[0].title[:100]}")
    print()
    print(post2)
else:
    print("Нет постов из TG-каналов конкурентов")
