import os
from dotenv import load_dotenv

load_dotenv()

# OpenAI API key (читается автоматически из переменной окружения OPENAI_API_KEY)
# Не нужно указывать явно — openai SDK читает её сам

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
TELEGRAM_ADMIN_CHAT_ID = int(os.environ["TELEGRAM_ADMIN_CHAT_ID"])

POST_INTERVAL_MINUTES = int(os.getenv("POST_INTERVAL_MINUTES", "60"))
MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "3"))
MIN_UPVOTES = int(os.getenv("MIN_UPVOTES", "50"))

KEYWORDS = [k.strip().lower() for k in os.getenv(
    "KEYWORDS",
    "AI,machine learning,startup,automation,SaaS,LLM,agent,business,productivity,tool"
).split(",")]
