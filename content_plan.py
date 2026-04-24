"""
Еженедельный контент-план для рубрики «Мои наблюдения / Учебные посты».

Логика:
  - В понедельник агент генерирует 5 тем на неделю (по одной на день пн-пт)
  - Темы сохраняются в weekly_plan.json
  - Каждый день бот берёт тему дня и включает её в дайджест
  - Пользователь может утвердить или отредактировать план через /plan

Формат тем: разборы кейсов с консультаций, ошибки предпринимателей,
инсайты из практики, учебные посты для аудитории малого бизнеса.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from groq import Groq

logger = logging.getLogger(__name__)

client = Groq()

PLAN_FILE = "weekly_plan.json"

# Примеры тем в нужном стиле
TOPIC_EXAMPLES = """
- Почему предприниматель часто создает продукт ради продукта, а не для клиента
- Какие скрипты работают по необычным кейсам в продажах
- Как правильно проводить кастдевы (custdev), чтобы не получать социально ожидаемые ответы
- Скорость vs Быстрота: почему 127 задач в день ведут к хаосу, а не к результату
- Зона мастерства как коварная ловушка: почему там рождается внутренняя пустота
- Наценка x4: математика нормального бизнеса и куда уходят 75% выручки
- Как выбирать ассистента: почему нельзя брать на эту роль "друга"
- Почему продажи — ключевое звено, и всё остальное неважно, если они плохие
- Иллюзия делегирования: почему мы скидываем задачи, а потом переделываем сами
- Как закрывать сделки, когда клиент "ушел подумать"
"""

GENERATE_PLAN_PROMPT = """ты — контент-стратег телеграм-канала Насти Базуевой @bazuevaconsalt.
канал для онлайн-предпринимателей — про продажи, маркетинг, операционку, найм, мышление.

сгенерируй 5 тем для учебных постов на неделю (пн-пт).
каждая тема — это глубокое, нишевое наблюдение или кейс из практики бизнес-консультанта.

требования к темам:
- ОЧЕНЬ конкретные и нишевые. НЕ БЕРИ банальные темы вроде "как важны продажи" или "почему надо делегировать".
- бери неочевидные углы: "почему зона мастерства — ловушка", "почему скорость вредит, а нужна быстрота".
- темы должны цеплять реальные, глубокие боли онлайн-бизнеса.
- разные по тематике: продажи, продуктология, мышление, команда, финансы.

примеры отличных, нишевых тем:
{examples}

верни ровно 5 тем — по одной на строку, без нумерации и лишних символов.
только сами темы, ничего больше.
"""


def _load_plan() -> dict:
    if os.path.exists(PLAN_FILE):
        with open(PLAN_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_plan(plan: dict) -> None:
    with open(PLAN_FILE, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)


def get_current_week_monday() -> str:
    """Вернуть дату понедельника текущей недели в формате YYYY-MM-DD."""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y-%m-%d")


def generate_weekly_plan() -> list[str]:
    """Сгенерировать 5 тем на неделю через GPT."""
    prompt = GENERATE_PLAN_PROMPT.format(examples=TOPIC_EXAMPLES)
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "ты — контент-стратег. генерируешь темы для телеграм-канала предпринимателя. "
                        "темы должны быть конкретными, практичными, из реального опыта консультанта."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=0.8,
        )
        text = response.choices[0].message.content.strip()
        topics = [line.strip() for line in text.split("\n") if line.strip()]
        topics = topics[:5]
        logger.info(f"Generated {len(topics)} weekly topics")
        return topics
    except Exception as e:
        logger.error(f"Weekly plan generation failed: {e}")
        return []


def get_or_create_weekly_plan() -> dict:
    """
    Вернуть текущий план недели.
    Если плана нет или он устарел — сгенерировать новый.
    
    Возвращает dict:
    {
        "week_start": "2026-04-21",
        "topics": ["тема 1", "тема 2", ...],
        "approved": False,
        "used_indices": []
    }
    """
    plan = _load_plan()
    current_week = get_current_week_monday()

    if plan.get("week_start") == current_week and plan.get("topics"):
        return plan

    # Новая неделя — генерируем план
    logger.info(f"Generating new weekly plan for week {current_week}")
    topics = generate_weekly_plan()

    if not topics:
        # Fallback — базовые темы
        topics = [
            "Основная ошибка в продажах — забыть про существующего клиента",
            "Как выстроить воронку продаж без рекламного бюджета",
            "Почему предприниматели боятся делегировать",
            "Как продать через оффер — разбор структуры",
            "Ошибка ограниченного майндсета в бизнесе",
        ]

    new_plan = {
        "week_start": current_week,
        "topics": topics,
        "approved": False,
        "used_indices": [],
    }
    _save_plan(new_plan)
    return new_plan


def get_today_topic() -> Optional[str]:
    """
    Вернуть тему дня из контент-плана.
    Берёт первую неиспользованную тему.
    Если все использованы — None.
    """
    plan = get_or_create_weekly_plan()
    topics = plan.get("topics", [])
    used = set(plan.get("used_indices", []))

    for i, topic in enumerate(topics):
        if i not in used:
            return topic

    return None


def mark_topic_used(topic: str) -> None:
    """Отметить тему как использованную."""
    plan = _load_plan()
    topics = plan.get("topics", [])
    used = plan.get("used_indices", [])

    for i, t in enumerate(topics):
        if t == topic and i not in used:
            used.append(i)
            break

    plan["used_indices"] = used
    _save_plan(plan)


def update_plan_topics(new_topics: list[str]) -> None:
    """Обновить темы плана (после редактирования пользователем)."""
    plan = _load_plan()
    plan["topics"] = new_topics[:5]
    plan["approved"] = True
    plan["used_indices"] = []
    _save_plan(plan)
    logger.info("Weekly plan updated by user")


def approve_plan() -> None:
    """Утвердить текущий план."""
    plan = _load_plan()
    plan["approved"] = True
    _save_plan(plan)


def format_plan_message(plan: dict) -> str:
    """Сформировать текст сообщения с планом недели."""
    week_start = plan.get("week_start", "")
    topics = plan.get("topics", [])
    approved = plan.get("approved", False)
    used = set(plan.get("used_indices", []))

    # Дни недели
    days = ["Пн", "Вт", "Ср", "Чт", "Пт"]

    status = "✅ Утверждён" if approved else "⏳ Ожидает утверждения"
    lines = [
        f"📅 <b>Контент-план на неделю</b>",
        f"<i>Неделя с {week_start} · {status}</i>",
        "",
    ]

    for i, topic in enumerate(topics):
        day = days[i] if i < len(days) else f"День {i+1}"
        check = "✅" if i in used else "◻️"
        lines.append(f"{check} <b>{day}:</b> {topic}")

    lines.append("")
    lines.append("Нажми на день чтобы написать пост по этой теме.")

    return "\n".join(lines)
