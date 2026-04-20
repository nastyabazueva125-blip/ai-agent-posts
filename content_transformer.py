import anthropic
import config
from hn_client import HNPost

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Ты — контент-менеджер Telegram-канала. Твоя задача — переписывать посты из Hacker News в стиле живого, уверенного предпринимателя.

Правила:
- Пиши от первого лица, как будто ты сам столкнулся с этой темой
- Убирай HN-сленг и специфику ("OP said", "throwaway", "YC", "HN" и т.д.)
- Добавь практическую ценность — что читатель может применить прямо сейчас
- Длина: 150–300 слов
- Используй 1–2 эмодзи максимум
- Заканчивай CTA или вопросом к читателю
- НЕ упоминай Hacker News как источник
- Пиши на русском языке
- Стиль: живой, конкретный, без воды"""


def transform_post(post: HNPost) -> str | None:
    source_text = (
        f"Заголовок: {post.title}\n\n{post.text}"
        if post.text
        else post.title
    )

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Перепиши этот пост для Telegram-канала про бизнес, AI и digital:\n\n"
                    f"{source_text}\n\n"
                    f"Категория: {post.source}. "
                    f"Пост набрал {post.upvotes} очков на Hacker News.\n"
                    f"Ссылка на оригинал: {post.url}"
                ),
            }
        ],
    )

    text_blocks = [b.text for b in message.content if b.type == "text"]
    return text_blocks[0].strip() if text_blocks else None
