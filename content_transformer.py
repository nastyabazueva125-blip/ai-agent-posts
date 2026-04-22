"""
Генерация постов для @bazuevaconsalt.

4 рубрики с разными промптами:
  - tools       : обзор нового инструмента (Product Hunt)
  - competitors : адаптация поста конкурента/коллеги под свою аудиторию
  - useful      : полезный пост из TG-канала (AI, инструменты)
  - content_plan: учебный пост по теме из контент-плана (разбор кейса, ошибки, инсайт)
  - voice_note  : переработка голосовой заметки в пост
"""

import json
import logging

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

logger = logging.getLogger(__name__)

client = OpenAI()

MAX_TEXT_CHARS = 6000
PAYWALL_MARKERS = [
    "subscribe to read", "subscribers only", "this is a subscriber",
    "только для подписчиков", "это письмо только для", "платных подписчиков",
    "sign in to read", "create a free account", "get full access",
    "unlock this article", "premium content", "member-only",
]

AUTHOR_STYLE = """
стиль автора — Настя Базуева, консультант по бизнесу для предпринимателей малого бизнеса:
- пишет от первого лица: "я часто вижу", "на консультации столкнулась", "мой клиент"
- короткие рубленые фразы. без воды и официоза
- прямолинейно: называет ошибки ошибками, не смягчает
- конкретные примеры из практики, не абстрактные советы
- живой разговорный язык, иногда с юмором
- посты 150-250 слов. не длиннее
- хештег в самом конце, отдельной строкой
"""

AUTHOR_EXAMPLES = """
пример 1:
Основная ошибка в продажах — забыть про существующего клиента.
Мы выделяем огромные бюджеты на поиск новых, но не на доведение до продажи тех, кто уже есть.
Часто на консультациях я сталкиваюсь именно с этим.
CRM пустая. Follow-up не настроен. Клиент написал — и тишина.
А потом удивляемся, почему конверсия низкая.
Работайте с теми, кто уже поднял руку. Это дешевле и быстрее.
#воронкиипродажи

пример 2:
Вчера на консультации — неправильное распределение ролей.
Ассистент выполняет роль друга. PM — роль ассистента.
В итоге никто не делает свою работу.
Когда нет чёткого разграничения — всё смешивается. И бизнес буксует.
Пропишите роли. Буквально на бумаге. Кто за что отвечает и что НЕ делает.
#операционка

пример 3:
Ошибка ограниченного майндсета.
Я часто слышу: "у меня точно не получится".
Ну супер, значит вы уже проиграли.
Выигрывает тот, кто думает что всё возможно — и идёт пробовать.
Мышление определяет результат. Это не мотивашка, это факт.
#мысливслух
"""

TOOLS_PROMPT = """напиши пост-обзор нового инструмента для телеграм-канала предпринимателей.

{style}

данные о продукте:
НАЗВАНИЕ: {title}
ОПИСАНИЕ: {summary}
ССЫЛКА: {url}

структура поста:
1. Что это за инструмент — одно предложение
2. Что умеет — 3-4 конкретных пункта (коротко)
3. Зачем это малому бизнесу — 1-2 предложения от себя
4. Ссылка на продукт

тон: нейтральный, информативный, без восторгов
хештег в конце: {hashtag}
"""

COMPETITORS_PROMPT = """у тебя есть пост из телеграм-канала коллеги/конкурента.
перепиши его для канала @bazuevaconsalt — возьми идею, но подай через свой опыт и аудиторию.

{style}

примеры постов автора:
{examples}

важно:
- не копируй дословно — возьми суть и переосмысли
- добавь свой угол зрения: "я тоже с этим сталкиваюсь", "у моих клиентов такая же история"
- аудитория — предприниматели малого бизнеса, не крупный корпорат

исходный пост от {source}:
{text}

хештег в конце: {hashtag}
"""

USEFUL_PROMPT = """у тебя есть пост из телеграм-канала про AI и инструменты для бизнеса.
адаптируй его для канала @bazuevaconsalt — сделай понятным для предпринимателей малого бизнеса.

{style}

примеры постов автора:
{examples}

важно:
- объясни простым языком, без технического жаргона
- покажи практическую пользу для малого бизнеса
- если это инструмент — как его использовать конкретно

исходный пост от {source}:
{text}

хештег в конце: {hashtag}
"""

CONTENT_PLAN_PROMPT = """напиши учебный пост для телеграм-канала предпринимателей на заданную тему.

{style}

примеры постов автора:
{examples}

тема поста: {topic}

структура:
- начни с конкретного наблюдения или ситуации ("часто вижу на консультациях...", "недавно клиент...")
- назови проблему прямо
- дай 2-3 конкретных совета или шага
- заверши сильным выводом

пиши от первого лица, как будто это реальный кейс из практики.
хештег в конце: {hashtag}
"""

VOICE_NOTE_PROMPT = """у тебя есть голосовая заметка автора — сырая мысль, записанная на ходу.
переработай её в готовый пост для телеграм-канала, сохранив голос автора.

{style}

примеры постов автора:
{examples}

важно:
- сохрани суть и личный опыт автора
- не добавляй ничего от себя — только развей и оформи то, что уже сказано
- если мысль незаконченная — логично дооформи в рамках той же идеи
- пост должен звучать как будто автор сам его написал

голосовая заметка (транскрипция):
{transcript}

хештег в конце: {hashtag}
"""


def _fetch_full_text(url: str) -> str:
    if not url or "t.me/" in url:
        return ""
    try:
        resp = requests.get(url, timeout=12, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ContentBot/1.0)",
        })
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        text_lower = text.lower()
        if any(marker in text_lower for marker in PAYWALL_MARKERS):
            if len(text) < 1500:
                logger.info(f"Paywall detected, skipping full text: {url[:60]}")
                return ""
        return text if len(text) > 200 else ""
    except Exception as e:
        logger.warning(f"Full text fetch failed for {url[:60]}: {e}")
        return ""


def _call_gpt(system: str, user: str, max_tokens: int = 700, temperature: float = 0.6) -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"GPT call failed: {e}")
        return ""


def transform(item) -> str:
    """Написать пост по ContentItem. Выбирает промпт по post_format."""
    fmt = item.post_format

    system = (
        "ты — редактор телеграм-канала Насти Базуевой о бизнесе для предпринимателей. "
        "пишешь от её лица: живо, прямолинейно, из практики. "
        "никакого официоза, никакой воды. только конкретные мысли."
    )

    if fmt == "tools":
        prompt = TOOLS_PROMPT.format(
            style=AUTHOR_STYLE,
            title=item.title,
            summary=item.summary[:1500] if item.summary else "",
            url=item.url,
            hashtag=item.hashtag,
        )
        text = _call_gpt(system, prompt, max_tokens=600)

    elif fmt == "competitors":
        post_text = item.summary or item.title
        prompt = COMPETITORS_PROMPT.format(
            style=AUTHOR_STYLE,
            examples=AUTHOR_EXAMPLES,
            source=item.source,
            text=post_text[:3000],
            hashtag=item.hashtag,
        )
        text = _call_gpt(system, prompt, max_tokens=700)

    elif fmt == "useful":
        post_text = item.summary or item.title
        prompt = USEFUL_PROMPT.format(
            style=AUTHOR_STYLE,
            examples=AUTHOR_EXAMPLES,
            source=item.source,
            text=post_text[:3000],
            hashtag=item.hashtag,
        )
        text = _call_gpt(system, prompt, max_tokens=700)

    elif fmt == "content_plan":
        prompt = CONTENT_PLAN_PROMPT.format(
            style=AUTHOR_STYLE,
            examples=AUTHOR_EXAMPLES,
            topic=item.title,
            hashtag=item.hashtag,
        )
        text = _call_gpt(system, prompt, max_tokens=700, temperature=0.7)

    else:
        # Fallback
        full_text = _fetch_full_text(item.url)
        if full_text:
            user_prompt = (
                f"напиши пост для телеграм-канала предпринимателей.\n"
                f"{AUTHOR_STYLE}\nпримеры:\n{AUTHOR_EXAMPLES}\n"
                f"ЗАГОЛОВОК: {item.title}\nИСТОЧНИК: {item.source}\n"
                f"ТЕКСТ:\n{full_text[:MAX_TEXT_CHARS]}\n"
                f"хештег в конце: {item.hashtag}"
            )
            text = _call_gpt(system, user_prompt, max_tokens=700)
        else:
            user_prompt = (
                f"напиши пост для телеграм-канала предпринимателей.\n"
                f"{AUTHOR_STYLE}\nпримеры:\n{AUTHOR_EXAMPLES}\n"
                f"ЗАГОЛОВОК: {item.title}\nИСТОЧНИК: {item.source}\n"
                f"ОПИСАНИЕ: {item.summary[:1500] if item.summary else ''}\n"
                f"хештег в конце: {item.hashtag}"
            )
            text = _call_gpt(system, user_prompt, max_tokens=600)

    logger.info(f"Post generated [{fmt}]: {item.title[:50]}")
    return text


def transform_voice_note(transcript: str, hashtag: str = "#мысливслух") -> str:
    """Переработать транскрипцию голосовой заметки в готовый пост."""
    prompt = VOICE_NOTE_PROMPT.format(
        style=AUTHOR_STYLE,
        examples=AUTHOR_EXAMPLES,
        transcript=transcript[:3000],
        hashtag=hashtag,
    )
    system = (
        "ты — редактор телеграм-канала Насти Базуевой. "
        "берёшь сырую голосовую заметку и превращаешь в готовый пост. "
        "сохраняй её голос и личный опыт — не добавляй ничего лишнего."
    )
    text = _call_gpt(system, prompt, max_tokens=700, temperature=0.5)
    logger.info(f"Voice note post generated: {transcript[:40]}...")
    return text


def transform_content_plan_topic(topic: str, hashtag: str = "#мысливслух") -> str:
    """Написать учебный пост по теме из контент-плана."""
    prompt = CONTENT_PLAN_PROMPT.format(
        style=AUTHOR_STYLE,
        examples=AUTHOR_EXAMPLES,
        topic=topic,
        hashtag=hashtag,
    )
    system = (
        "ты — редактор телеграм-канала Насти Базуевой. "
        "пишешь учебные посты из практики консультанта для предпринимателей малого бизнеса. "
        "конкретно, живо, от первого лица."
    )
    text = _call_gpt(system, prompt, max_tokens=700, temperature=0.7)
    logger.info(f"Content plan post generated: {topic[:50]}")
    return text


def translate_title(title: str, summary: str = "") -> dict:
    """Быстро перевести заголовок и сделать краткое описание на русском."""
    prompt = (
        f"переведи заголовок на русский язык и сделай краткое описание (1 предложение).\n"
        f"заголовок: {title}\n"
        f"описание (если есть): {summary[:300] if summary else ''}\n\n"
        f"ответь строго в формате JSON:\n"
        '{ "title": "...", "description": "..." }'
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.3,
        )
        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        logger.warning(f"translate_title failed: {e}")
        return {"title": title, "description": summary[:100] if summary else ""}
