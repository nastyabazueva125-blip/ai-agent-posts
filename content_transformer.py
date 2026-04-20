"""
content_transformer.py — перевод/адаптация статьи на русский язык для Telegram-канала.
Загружает полный текст через requests+BeautifulSoup.
Если текст недоступен (paywall, слишком короткий) — использует RSS summary.
"""

import logging
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from content_sources import ContentItem

logger = logging.getLogger(__name__)

client = OpenAI()  # API key и base_url из окружения

MAX_TEXT_CHARS = 6000  # ~4000 токенов — достаточно для полного поста

# Минимальная длина текста чтобы считать его полноценным (не paywall-заглушкой)
MIN_USEFUL_TEXT_CHARS = 800

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Признаки paywall / закрытого контента
PAYWALL_SIGNALS = [
    "subscribers only",
    "for subscribers",
    "paid subscribers",
    "subscribe to read",
    "subscribe to continue",
    "this post is for paying subscribers",
    "this post is for paid subscribers",
    "только для подписчиков",
    "платным подписчикам",
    "sign in to read",
    "login to read",
    "create a free account",
    "unlock this post",
    "members only",
    "premium content",
]


def _has_paywall(text: str) -> bool:
    """Проверить, является ли текст paywall-заглушкой."""
    text_lower = text.lower()
    for signal in PAYWALL_SIGNALS:
        if signal in text_lower:
            return True
    return False


def _fetch_full_text(url: str) -> str:
    """Загрузить полный текст статьи по URL через requests + BeautifulSoup.
    
    Возвращает пустую строку если:
    - не удалось загрузить
    - текст слишком короткий (paywall/заглушка)
    - обнаружены признаки paywall
    """
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
            soup.find('div', class_=lambda c: c and any(x in c.lower() for x in [
                'post-content', 'article-body', 'entry-content', 'post-body',
                'content-body', 'prose', 'article-content', 'post__content'
            ])) or
            soup.find('main') or
            soup.find('body')
        )

        if content:
            text = content.get_text(separator='\n', strip=True)
            lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
            text = '\n'.join(lines)

            # Проверяем на paywall
            if _has_paywall(text):
                logger.info(f"Paywall detected for {url[:60]} — falling back to RSS summary")
                return ""

            # Проверяем минимальную длину
            if len(text) < MIN_USEFUL_TEXT_CHARS:
                logger.info(f"Text too short ({len(text)} chars) for {url[:60]} — likely paywall/preview")
                return ""

            logger.info(f"Full text fetched: {len(text)} chars from {url[:60]}")
            return text

    except Exception as e:
        logger.warning(f"Full text fetch failed for {url[:60]}: {e}")
    return ""


TRANSLATE_TITLE_PROMPT = """переведи заголовок и краткое описание статьи на русский язык.

требования:
- язык живой и нативный, не официальный
- заголовок — одна строка, максимально близко к оригиналу
- описание — 1-2 предложения, суть статьи
- не добавляй ничего от себя

формат ответа (строго):
ЗАГОЛОВОК: <перевод заголовка>
ОПИСАНИЕ: <1-2 предложения о чём статья>

оригинал:
ЗАГОЛОВОК: {title}
ОПИСАНИЕ: {summary}
"""


def translate_title(title: str, summary: str) -> dict:
    """Быстро перевести только заголовок и краткое описание для дайджеста.
    
    Возвращает dict с ключами 'title' и 'description'.
    """
    try:
        prompt = TRANSLATE_TITLE_PROMPT.format(
            title=title,
            summary=summary[:500] if summary else "нет описания",
        )
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": "ты переводчик. переводи точно и кратко.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
            temperature=0.2,
        )
        text = response.choices[0].message.content.strip()

        ru_title = title  # fallback
        ru_desc = summary[:100] if summary else ""

        for line in text.splitlines():
            if line.startswith("ЗАГОЛОВОК:"):
                ru_title = line.removeprefix("ЗАГОЛОВОК:").strip()
            elif line.startswith("ОПИСАНИЕ:"):
                ru_desc = line.removeprefix("ОПИСАНИЕ:").strip()

        return {"title": ru_title, "description": ru_desc}

    except Exception as e:
        logger.error(f"translate_title failed: {e}")
        return {"title": title, "description": summary[:100] if summary else ""}


# ─── Промпты для генерации поста ──────────────────────────────────────────

POST_FROM_FULL_TEXT_PROMPT = """у тебя есть полный текст статьи на английском. 
напиши на его основе пост для телеграм-канала о бизнесе и маркетинге.

требования к посту:
- язык: живой разговорный русский, без официоза
- длина: 150-300 слов — не больше, не меньше
- структура: короткий цепляющий заход → главная мысль/идея → 2-3 конкретных тезиса или примера → вывод/мысль для читателя
- стиль: строчные буквы в начале абзацев (кроме имён собственных), рубленые фразы
- не пересказывай всё подряд — выбери самое ценное и интересное
- не добавляй "подписывайтесь" и призывы к действию
- в конце добавь хештег: {hashtag}

материал:
ЗАГОЛОВОК: {title}
ИСТОЧНИК: {source}

ПОЛНЫЙ ТЕКСТ:
{full_text}
"""

POST_FROM_SUMMARY_PROMPT = """у тебя есть заголовок и краткое описание статьи на английском.
напиши на их основе пост для телеграм-канала о бизнесе и маркетинге.

требования к посту:
- язык: живой разговорный русский, без официоза
- длина: 100-200 слов
- структура: короткий цепляющий заход → главная мысль → 2-3 тезиса → вывод
- стиль: строчные буквы в начале абзацев (кроме имён собственных), рубленые фразы
- раскрой тему максимально — домысли детали исходя из заголовка и описания
- не добавляй "подписывайтесь" и призывы к действию
- в конце добавь хештег: {hashtag}

материал:
ЗАГОЛОВОК: {title}
ИСТОЧНИК: {source}
ОПИСАНИЕ: {summary}
"""


def transform(item: ContentItem) -> str:
    """Загрузить полный текст статьи и написать пост для Telegram-канала."""

    # Пробуем загрузить полный текст по URL
    full_text = _fetch_full_text(item.url)

    if full_text:
        # Есть полный текст — пишем пост на его основе
        prompt = POST_FROM_FULL_TEXT_PROMPT.format(
            title=item.title,
            source=item.source,
            full_text=full_text[:MAX_TEXT_CHARS],
            hashtag=item.hashtag,
        )
        max_tokens = 800
        logger.info(f"Using full text ({len(full_text)} chars) for: {item.title[:50]}")
    else:
        # Нет полного текста (paywall/ошибка) — пишем по RSS summary
        logger.info(f"Using RSS summary for: {item.title[:50]}")
        prompt = POST_FROM_SUMMARY_PROMPT.format(
            title=item.title,
            source=item.source,
            summary=item.summary[:2000] if item.summary else "(нет описания)",
            hashtag=item.hashtag,
        )
        max_tokens = 600

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "ты — редактор телеграм-канала о бизнесе для предпринимателей. "
                        "пишешь живые, полезные посты на русском языке. "
                        "стиль: разговорный, без воды, конкретные мысли и примеры."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.5,
        )
        text = response.choices[0].message.content.strip()
        logger.info(f"Post generated [{item.post_format}]: {item.title[:50]}...")
        return text
    except Exception as e:
        logger.error(f"Post generation failed: {e}")
        return ""
