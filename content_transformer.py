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

# ─── Тон голоса автора канала ──────────────────────────────────────────────
# Примеры реальных постов автора — используются для калибровки стиля
AUTHOR_VOICE_EXAMPLES = """
ПРИМЕР 1:
Основная ошибка в продажах — забыть про нашего клиента. Мы выделяем огромные бюджеты на поиск, но не на доведение до продажи. Часто на консультациях я сталкиваюсь именно с этим.

ПРИМЕР 2:
Вчера на консультации столкнулась с такой проблемой как неправильное распределение ролей. Часто ассистент выполняет роль друга, а ПМ роль ассистента.

ПРИМЕР 3:
Ошибка ограниченного майндсета. Я часто слышу "у меня точно не получится". Ну супер, значит вы проиграли. Выигрывает тот, кто думает, что всё возможно.

ПРИМЕР 4:
Как продать через оффер.
"""

AUTHOR_STYLE_DESCRIPTION = """
Стиль автора (Настя Базуева, консультант по бизнесу):
- Короткие рубленые фразы, без воды
- Говорит от первого лица: "я часто вижу", "на консультации столкнулась", "я слышу"
- Конкретные наблюдения из практики — не абстрактные советы
- Прямолинейность: называет ошибки прямо, без смягчений
- Разговорный язык: "ну супер", "вот именно", "это важно"
- Структура: тезис → наблюдение из практики → вывод
- Длина: 100-250 слов, не больше
- Хештег в конце
- Без "подписывайтесь", без призывов к действию
- Без официоза и корпоративного языка
"""


def _has_paywall(text: str) -> bool:
    """Проверить, является ли текст paywall-заглушкой."""
    text_lower = text.lower()
    for signal in PAYWALL_SIGNALS:
        if signal in text_lower:
            return True
    return False


def _fetch_full_text(url: str) -> str:
    """Загрузить полный текст статьи по URL через requests + BeautifulSoup."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, 'html.parser')

        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'button']):
            tag.decompose()

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

            if _has_paywall(text):
                logger.info(f"Paywall detected for {url[:60]} — falling back to RSS summary")
                return ""

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
    """Быстро перевести только заголовок и краткое описание для дайджеста."""
    try:
        prompt = TRANSLATE_TITLE_PROMPT.format(
            title=title,
            summary=summary[:500] if summary else "нет описания",
        )
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "ты переводчик. переводи точно и кратко."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
            temperature=0.2,
        )
        text = response.choices[0].message.content.strip()

        ru_title = title
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

POST_FROM_FULL_TEXT_PROMPT = """у тебя есть полный текст статьи. 
напиши на его основе пост для телеграм-канала в стиле автора.

{style}

примеры постов автора для ориентира по стилю:
{examples}

материал для поста:
ЗАГОЛОВОК: {title}
ИСТОЧНИК: {source}

ПОЛНЫЙ ТЕКСТ:
{full_text}

хештег в конце: {hashtag}
"""

POST_FROM_SUMMARY_PROMPT = """у тебя есть заголовок и краткое описание статьи.
напиши на их основе пост для телеграм-канала в стиле автора.

{style}

примеры постов автора для ориентира по стилю:
{examples}

материал:
ЗАГОЛОВОК: {title}
ИСТОЧНИК: {source}
ОПИСАНИЕ: {summary}

хештег в конце: {hashtag}
"""

POST_FROM_TG_PROMPT = """у тебя есть пост из русскоязычного телеграм-канала.
напиши на его основе пост для телеграм-канала @bazuevaconsalt в стиле автора.

{style}

примеры постов автора для ориентира по стилю:
{examples}

исходный пост:
АВТОР: {source}

ТЕКСТ:
{text}

хештег в конце: {hashtag}
"""

VOICE_NOTE_TO_POST_PROMPT = """у тебя есть голосовая заметка автора — сырая мысль, записанная на ходу.
переработай её в готовый пост для телеграм-канала, сохранив голос и стиль автора.

{style}

примеры постов автора для ориентира по стилю:
{examples}

важно:
- сохрани суть и личный опыт автора
- не добавляй ничего от себя — только развей и оформи то, что уже сказано
- если мысль незаконченная — логично дооформи её в рамках той же идеи
- пост должен звучать как будто автор сам его написал

голосовая заметка (транскрипция):
{transcript}

хештег в конце: {hashtag}
"""


def _is_tg_url(url: str) -> bool:
    """Проверить, является ли URL ссылкой на Telegram-пост."""
    return "t.me/" in url


def transform(item: ContentItem) -> str:
    """Загрузить полный текст статьи и написать пост для Telegram-канала."""

    if _is_tg_url(item.url) and item.summary and len(item.summary) >= 80:
        logger.info(f"TG post, using summary directly: {item.title[:50]}")
        prompt = POST_FROM_TG_PROMPT.format(
            style=AUTHOR_STYLE_DESCRIPTION,
            examples=AUTHOR_VOICE_EXAMPLES,
            source=item.source,
            text=item.summary[:3000],
            hashtag=item.hashtag,
        )
        max_tokens = 700
    else:
        full_text = _fetch_full_text(item.url)

        if full_text:
            prompt = POST_FROM_FULL_TEXT_PROMPT.format(
                style=AUTHOR_STYLE_DESCRIPTION,
                examples=AUTHOR_VOICE_EXAMPLES,
                title=item.title,
                source=item.source,
                full_text=full_text[:MAX_TEXT_CHARS],
                hashtag=item.hashtag,
            )
            max_tokens = 800
            logger.info(f"Using full text ({len(full_text)} chars) for: {item.title[:50]}")
        else:
            logger.info(f"Using RSS summary for: {item.title[:50]}")
            prompt = POST_FROM_SUMMARY_PROMPT.format(
                style=AUTHOR_STYLE_DESCRIPTION,
                examples=AUTHOR_VOICE_EXAMPLES,
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
                        "ты — редактор телеграм-канала Насти Базуевой о бизнесе для предпринимателей. "
                        "пишешь от её лица: живо, прямолинейно, из практики. "
                        "никакого официоза, никакой воды. только конкретные мысли."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.6,
        )
        text = response.choices[0].message.content.strip()
        logger.info(f"Post generated [{item.post_format}]: {item.title[:50]}...")
        return text
    except Exception as e:
        logger.error(f"Post generation failed: {e}")
        return ""


def transform_voice_note(transcript: str, hashtag: str = "#мысливслух") -> str:
    """Переработать транскрипцию голосовой заметки в готовый пост."""
    prompt = VOICE_NOTE_TO_POST_PROMPT.format(
        style=AUTHOR_STYLE_DESCRIPTION,
        examples=AUTHOR_VOICE_EXAMPLES,
        transcript=transcript[:3000],
        hashtag=hashtag,
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "ты — редактор телеграм-канала Насти Базуевой. "
                        "берёшь сырую голосовую заметку и превращаешь в готовый пост. "
                        "сохраняй её голос и личный опыт — не добавляй ничего лишнего."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=700,
            temperature=0.5,
        )
        text = response.choices[0].message.content.strip()
        logger.info(f"Voice note post generated: {transcript[:40]}...")
        return text
    except Exception as e:
        logger.error(f"Voice note transform failed: {e}")
        return ""
