"""
content_transformer.py — перевод полного текста статьи на нативный русский.
Использует newspaper3k для извлечения полного текста по URL,
затем GPT-4.1-mini для точного перевода.
"""

import logging
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from content_sources import ContentItem

logger = logging.getLogger(__name__)

client = OpenAI()  # API key и base_url из окружения

MAX_TEXT_CHARS = 6000  # ~4000 токенов — достаточно для полного поста


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def _fetch_full_text(url: str) -> str:
    """Загрузить полный текст статьи по URL через requests + BeautifulSoup."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, 'html.parser')

        # Убираем мусор
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'button']):
            tag.decompose()

        # Ищем основной контент
        content = (
            soup.find('article') or
            soup.find('div', class_=lambda c: c and any(x in c.lower() for x in ['post-content', 'article-body', 'entry-content', 'post-body', 'content-body', 'prose'])) or
            soup.find('main') or
            soup.find('body')
        )

        if content:
            text = content.get_text(separator='\n', strip=True)
            # Убираем пустые строки
            lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
            text = '\n'.join(lines)
            if len(text) > 300:
                logger.info(f"Full text fetched: {len(text)} chars from {url[:60]}")
                return text
    except Exception as e:
        logger.warning(f"Full text fetch failed for {url[:60]}: {e}")
    return ""


TRANSLATE_PROMPT = """переведи этот материал на русский язык.

требования к переводу:
- переводи максимально точно и близко к оригиналу, не переосмысляй
- язык должен быть живым и нативным — не "машинным" и не "официальным"
- сохраняй структуру оригинала: абзацы, списки, заголовки
- термины переводи по смыслу (например: "funnel" → "воронка", "churn" → "отток клиентов", "revenue" → "выручка")
- если в оригинале есть цифры, примеры, кейсы — сохраняй их все
- не добавляй ничего от себя, не делай выводов которых нет в оригинале
- не сокращай текст — переводи полностью
- в самом конце добавь хештег: {hashtag}

материал для перевода:
ЗАГОЛОВОК: {title}
ИСТОЧНИК: {source}

ПОЛНЫЙ ТЕКСТ:
{full_text}
"""

TRANSLATE_SUMMARY_PROMPT = """переведи этот материал на русский язык.

требования к переводу:
- переводи максимально точно и близко к оригиналу, не переосмысляй
- язык должен быть живым и нативным — не "машинным" и не "официальным"
- сохраняй структуру оригинала: абзацы, списки, заголовки
- термины переводи по смыслу
- если в оригинале есть цифры, примеры, кейсы — сохраняй их все
- не добавляй ничего от себя
- в самом конце добавь хештег: {hashtag}

материал для перевода:
ЗАГОЛОВОК: {title}
ИСТОЧНИК: {source}
ТЕКСТ: {summary}
"""


def transform(item: ContentItem) -> str:
    """Загрузить полный текст статьи и перевести его на русский язык."""

    # Пробуем загрузить полный текст по URL
    full_text = _fetch_full_text(item.url)

    if full_text:
        # Есть полный текст — переводим его
        prompt = TRANSLATE_PROMPT.format(
            title=item.title,
            source=item.source,
            full_text=full_text[:MAX_TEXT_CHARS],
            hashtag=item.hashtag,
        )
        max_tokens = 3000
    else:
        # Нет полного текста — переводим summary из RSS
        logger.info(f"Falling back to RSS summary for: {item.title[:50]}")
        prompt = TRANSLATE_SUMMARY_PROMPT.format(
            title=item.title,
            source=item.source,
            summary=item.summary[:2000],
            hashtag=item.hashtag,
        )
        max_tokens = 1500

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "ты — профессиональный переводчик. твоя задача — точно и живо переводить "
                        "тексты с английского на русский язык. не добавляй ничего от себя, "
                        "не переосмысляй, не сокращай. только точный нативный перевод."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        text = response.choices[0].message.content.strip()
        logger.info(f"Translated [{item.post_format}]: {item.title[:50]}...")
        return text
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return ""
