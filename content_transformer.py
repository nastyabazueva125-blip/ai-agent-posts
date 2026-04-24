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
from groq import Groq

logger = logging.getLogger(__name__)

client = Groq()

MAX_TEXT_CHARS = 6000
PAYWALL_MARKERS = [
    "subscribe to read", "subscribers only", "this is a subscriber",
    "только для подписчиков", "это письмо только для", "платных подписчиков",
    "sign in to read", "create a free account", "get full access",
    "unlock this article", "premium content", "member-only",
]

AUTHOR_STYLE = """
стиль автора — Настя Базуева, консультант по бизнесу для онлайн-предпринимателей:
- пишет от первого лица: "я заметила", "когда нам кладут плитку", "сегодня читала"
- использует метафоры и аналогии из обычной жизни для объяснения бизнес-процессов
- любит точные цифры и формулы (например: "наценка x4", "25% на налоги, 25% на команду")
- глубокие, нишевые инсайты, а не банальные советы "как важно продавать"
- короткие абзацы, часто по одному предложению
- живой разговорный язык, без академической воды, но с глубоким смыслом
- посты 150-250 слов. не длиннее
- хештег в самом конце, отдельной строкой
"""

AUTHOR_EXAMPLES = """
пример 1 (аналогия из жизни -> бизнес):
Предпринимателю не нужна скорость. Ему нужна быстрота.
Когда нам кладут плитку в ванной в новой квартире - нам не важно с какой скоростью ее будут класть: 10 плиток в час или 40. Нам важно - когда закончат всю плитку.
Если мы будем ставить цели по скорости укладки плитки - мы ее побьем, положим криво, и, в итоге, сделаем ремонт еще дольше.
Так и в бизнесе. Предприниматель может чувствовать себя неэффективным, когда вокруг нет 127 задач, нет движняка. Он фанат скорости. Но эта скорость порождает хаос. Ключевое теряется в мешанине микро-задач.
Чтобы достигать цели быстрее - надо стать фанатом быстроты, а не скорости.
#мысливслух

пример 2 (инсайт из книги + личный вывод):
Сегодня читала книгу одну про выход на новый уровень. Там классная мысль была.
Есть зона некомпетентности - это то, в чем мы не шарим и не хотим изучать.
Есть зона компетентности - это то, что мы понимаем, но не очень любим.
Есть зона мастерства - это то, что мы делаем очень хорошо, нам за это платят деньги.
А есть зона гениальности - сосредоточение истинного дара, поток, радость.
И мысль, что зона мастерства - коварная ловушка. Там есть иллюзия, что ты уже всего добился, монетизация, признание. Но именно тут рождается состояние внутренней пустоты.
Чтобы жить в потоке - надо запретить себе развиваться в чем либо, кроме зоны своей гениальности.
#мысливслух

пример 3 (конкретные цифры и жесткая правда):
Нормальные бизнесы - это где наценка от себестоимости товара х4.
Вот сделали вы компанию - 25% уйдут на себес, 25% отдадите налогов, еще 25% сожрет команда, маркетинг и менеджмент. И вот, хотя бы 20-25% себе на макароны останется.
Посчитайте вашу наценку прямо сейчас.
#воронкиипродажи

пример 4 (наблюдение с консультаций):
я заметила, что многие бизнесы, кто ко мне приходят, пропускают одну самую ключевую мысль в создании своего продукта. Это понимание клиента и его реальных болей.
нам всем нравятся "идеи". Нам нравится придумывать продукт и натягивать на него рынок. Но хороший бизнес строится от обратного.
В начале нужно понять клиента и уже потом продумать как решить его боль теми инструментами, которые вы знаете.
#продуктология
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
3. Зачем это онлайн-бизнесу — 1-2 предложения от себя
4. Ссылка на продукт

КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО:
- длинные абзацы по 4+ предложения
- вводные слова: "я думаю", "мы можем", "важно отметить"
- академический стиль и вода

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
- аудитория — онлайн-предприниматели, не крупный корпорат

КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО:
- абзацы длиннее 3 предложений
- вводные слова: "я думаю", "важно отметить", "необходимо понять"
- академическая вода и обобщения

ЕСЛИ исходный пост не связан с бизнесом, продажами, маркетингом, операционкой, наймом или мышлением предпринимателя — ответь только: SKIP
ИНАЧЕ — напиши пост по инструкциям выше.

исходный пост от {source}:
{text}

хештег в конце: {hashtag}
"""

USEFUL_PROMPT = """у тебя есть пост из телеграм-канала про AI и инструменты для бизнеса.
адаптируй его для канала @bazuevaconsalt — сделай понятным для онлайн-предпринимателей.

{style}

примеры постов автора:
{examples}

важно:
- объясни простым языком, без технического жаргона
- покажи практическую пользу для онлайн-бизнеса
- если это инструмент — как его использовать конкретно

КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО:
- абзацы длиннее 3 предложений
- вводные слова: "я думаю", "важно отметить", "необходимо понять"
- академическая вода

исходный пост от {source}:
{text}

хештег в конце: {hashtag}
"""

CONTENT_PLAN_PROMPT = """напиши пост для телеграм-канала @bazuevaconsalt на заданную тему.

{style}

примеры постов автора (повторяй этот стиль точно):
{examples}

ТЕМА ПОСТА: {topic}

СТРУКТУРА (выбери один из вариантов):
Вариант А (аналогия из жизни): начни с бытовой ситуации (ремонт, плитка, такси), перенеси в бизнес, дай вывод.
Вариант Б (инсайт из книги/практики): "сегодня читала...", "заметила на консультациях...", разбери концепцию, дай вывод.
Вариант В (цифры/формула): начни с конкретной цифры, объясни математику, дай действие.

КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО:
- абзацы длиннее 3 предложений
- вводные слова: "я думаю", "важно отметить", "необходимо понять", "рекомендую три простых шага"
- академическая вода и банальные советы
- перечисления в формате "во-первых, во-вторых, в-третьих"

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
            model="llama-3.3-70b-versatile",
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


BUSINESS_KEYWORDS = [
    "продаж", "клиент", "бизнес", "деньги", "выручка", "прибыль", "маркетинг", "воронка",
    "оффер", "продукт", "команда", "найм", "делегир", "операционка", "предприниматель",
    "стратегия", "рост", "масштаб", "заработать", "запуск", "курс", "услуга", "покупать",
    "цена", "сделка", "время", "эффективность", "результат", "цель", "задача",
    "мышление", "ошибка", "кейс", "консультация", "аудитория", "подписчик", "канал",
]


NON_BUSINESS_KEYWORDS = [
    "благотворитель", "школьник", "студент", "дети", "деть", "семья", "семейный",
    "политик", "выбор", "война", "религия", "церковь", "спорт", "футбол",
    "путешествие", "отдых", "бали", "серф", "отпуск",
]


def _is_business_relevant(text: str) -> bool:
    """Проверить, связан ли текст с бизнес-тематикой."""
    text_lower = text.lower()
    # Если есть стоп-слова — нерелевантно
    if any(kw in text_lower for kw in NON_BUSINESS_KEYWORDS):
        return False
    return any(kw in text_lower for kw in BUSINESS_KEYWORDS)


def transform(item) -> str:
    """Написать пост по ContentItem. Выбирает промпт по post_format."""
    fmt = item.post_format

    system = (
        "ты — редактор телеграм-канала Насти Базуевой. "
        "ПИШЕШЬ КОРОТКО: каждый абзац максимум 2-3 предложения. "
        "БЕЗ воды, без официоза, без вводных слов. "
        "ТОЛЬКО конкретные мысли, цифры, аналогии. "
        "Пишешь от первого лица: живо, прямолинейно, из практики."
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
        # Предварительная проверка релевантности без обращения к LLM
        if not _is_business_relevant(post_text):
            logger.info(f"Competitors post pre-filtered (not business): {item.title[:50]}")
            return ""
        prompt = COMPETITORS_PROMPT.format(
            style=AUTHOR_STYLE,
            examples=AUTHOR_EXAMPLES,
            source=item.source,
            text=post_text[:3000],
            hashtag=item.hashtag,
        )
        text = _call_gpt(system, prompt, max_tokens=700)
        # Если модель решила что пост нерелевантен — возвращаем пустую строку
        if text.strip().upper() == "SKIP" or text.strip().startswith("SKIP"):
            logger.info(f"Competitors post skipped (not business-related): {item.title[:50]}")
            return ""

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
            model="llama-3.3-70b-versatile",
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
