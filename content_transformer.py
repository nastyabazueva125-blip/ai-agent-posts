import anthropic
import config
from reddit_client import RedditPost

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Ты — контент-менеджер Telegram-канала. Твоя задача — переписывать посты из Reddit в стиле живого, уверенного предпринимателя.

Правила:
- Пиши от первого лица, как будто ты сам столкнулся с этой темой
- Убирай reddit-сленг и специфику ("OP said", "ETA", "IMO" и т.д.)
- Добавь практическую ценность — что читатель может применить прямо сейчас
- Длина: 150–300 слов
- Используй 1–2 эмодзи максимум
- Заканчивай CTA или вопросом к читателю
- НЕ упоминай Reddit как источник
- Пиши на русском языке
- Стиль: живой, конкретный, без воды"""


def transform_post(post: RedditPost) -> str | None:
    source_text = f"Заголовок: {post.title}\n\n{post.text}" if post.text else post.title

    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=1024,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Перепиши этот пост для Telegram-канала про бизнес, AI и digital:\n\n"
                    f"{source_text}\n\n"
                    f"Тема из сабреддита r/{post.subreddit}. "
                    f"Пост набрал {post.upvotes} upvotes."
                ),
            }
        ],
    ) as stream:
        message = stream.get_final_message()

    text_blocks = [b.text for b in message.content if b.type == "text"]
    return text_blocks[0].strip() if text_blocks else None
