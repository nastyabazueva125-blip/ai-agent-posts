import os
from dotenv import load_dotenv

load_dotenv()

REDDIT_CLIENT_ID = os.environ["REDDIT_CLIENT_ID"]
REDDIT_CLIENT_SECRET = os.environ["REDDIT_CLIENT_SECRET"]
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "ai-content-curator/1.0")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]

POST_INTERVAL_MINUTES = int(os.getenv("POST_INTERVAL_MINUTES", "60"))
MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "3"))
MIN_UPVOTES = int(os.getenv("MIN_UPVOTES", "50"))

SUBREDDITS = [s.strip() for s in os.getenv(
    "SUBREDDITS",
    "smallbusiness,Entrepreneur,artificial,MachineLearning,webdev,SideProject"
).split(",")]

KEYWORDS = [k.strip().lower() for k in os.getenv(
    "KEYWORDS",
    "SMB,small business,AI agent,neural network,website,automation,startup"
).split(",")]
