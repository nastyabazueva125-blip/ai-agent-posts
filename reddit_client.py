import praw
import config
from dataclasses import dataclass


@dataclass
class RedditPost:
    title: str
    text: str
    url: str
    subreddit: str
    upvotes: int
    post_id: str


def get_reddit_client() -> praw.Reddit:
    return praw.Reddit(
        client_id=config.REDDIT_CLIENT_ID,
        client_secret=config.REDDIT_CLIENT_SECRET,
        user_agent=config.REDDIT_USER_AGENT,
    )


def _is_relevant(post: praw.models.Submission) -> bool:
    text = (post.title + " " + (post.selftext or "")).lower()
    return any(kw in text for kw in config.KEYWORDS)


def fetch_posts(seen_ids: set[str]) -> list[RedditPost]:
    reddit = get_reddit_client()
    results: list[RedditPost] = []

    for subreddit_name in config.SUBREDDITS:
        subreddit = reddit.subreddit(subreddit_name)
        for post in subreddit.hot(limit=25):
            if post.id in seen_ids:
                continue
            if post.score < config.MIN_UPVOTES:
                continue
            if post.is_self and not post.selftext:
                continue
            if not _is_relevant(post):
                continue

            results.append(RedditPost(
                title=post.title,
                text=post.selftext[:2000] if post.selftext else "",
                url=f"https://reddit.com{post.permalink}",
                subreddit=subreddit_name,
                upvotes=post.score,
                post_id=post.id,
            ))

            if len(results) >= config.MAX_POSTS_PER_RUN * 3:
                return results

    return results
