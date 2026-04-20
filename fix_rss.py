import sys

with open("content_sources.py", "r", encoding="utf-8") as f:
    content = f.read()

new_rss = """RSS_SOURCES = {
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
}"""

import re
# Найти всё от RSS_SOURCES = { до } и заменить
content = re.sub(r'RSS_SOURCES = \{.*?\n\}', new_rss, content, flags=re.DOTALL)

with open("content_sources.py", "w", encoding="utf-8") as f:
    f.write(content)
