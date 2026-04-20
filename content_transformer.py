"""
content_transformer.py — перевод оригинального контента на нативный русский.
Использует GPT-4.1-mini через OpenAI API.
Задача: точный, живой перевод без переосмысления и творческой переработки.
"""

import logging
from openai import OpenAI
from content_sources import ContentItem

logger = logging.getLogger(__name__)

client = OpenAI()  # API key и base_url из окружения

TRANSLATE_PROMPT = """переведи этот материал на русский язык.

требования к переводу:
- переводи максимально точно и близко к оригиналу, не переосмысляй
- язык должен быть живым и нативным — не "машинным" и не "официальным"
- сохраняй структуру оригинала: абзацы, списки, заголовки
- термины переводи по смыслу (например: "funnel" → "воронка", "churn" → "отток клиентов")
- если в оригинале есть цифры, примеры, кейсы — сохраняй их все
- не добавляй ничего от себя, не делай выводов которых нет в оригинале
- не сокращай текст
- в самом конце добавь хештег: {hashtag}

материал для перевода:
ЗАГОЛОВОК: {title}
ИСТОЧНИК: {source}
ТЕКСТ: {summary}
"""


def transform(item: ContentItem) -> str:
    """Перевести ContentItem на нативный русский язык."""
    prompt = TRANSLATE_PROMPT.format(
        title=item.title,
        source=item.source,
        summary=item.summary[:1200],  # берём больше текста для точного перевода
        hashtag=item.hashtag,
    )

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
            max_tokens=1200,
            temperature=0.3,  # низкая температура = точность перевода
        )
        text = response.choices[0].message.content.strip()
        logger.info(f"Translated [{item.post_format}]: {item.title[:50]}...")
        return text
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return ""
