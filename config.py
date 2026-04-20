import os
from dotenv import load_dotenv

load_dotenv()

# OpenAI API key — читается автоматически из OPENAI_API_KEY
# Telegram
TELEGRAM_BOT_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHANNEL_ID   = os.environ["TELEGRAM_CHANNEL_ID"]
TELEGRAM_ADMIN_CHAT_ID = int(os.environ["TELEGRAM_ADMIN_CHAT_ID"])
