"""Pydantic models for Reddit Scraper input validation and output formatting."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# --- Input Models ---


class ScrapingMode(str, Enum):
    SUBREDDIT_POSTS = "subreddit_posts"
    SEARCH = "search"
    USER_PROFILE = "user_profile"
    POST_COMMENTS = "post_comments"


class SortOrder(str, Enum):
    HOT = "hot"
    NEW = "new"
    TOP = "top"
    RISING = "rising"


class TimeFilter(str, Enum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    ALL = "all"


class SearchSort(str, Enum):
    RELEVANCE = "relevance"
    HOT = "hot"
    TOP = "top"
    NEW = "new"
    COMMENTS = "comments"


class UserContentType(str, Enum):
    OVERVIEW = "overview"
    SUBMITTED = "submitted"
    COMMENTS = "comments"


class ScraperInput(BaseModel):
    """Validated scraper input from Apify."""

    mode: ScrapingMode = ScrapingMode.SUBREDDIT_POSTS

    # Subreddit posts mode
    subreddits: list[str] = Field(default_factory=list)
    sort: SortOrder = SortOrder.HOT
    time_filter: TimeFilter = TimeFilter.WEEK

    # Search mode
    search_query: str = ""
    search_queries_list: list[str] = Field(default_factory=list)
    search_subreddit: str = ""
    search_sort: SearchSort = SearchSort.RELEVANCE

    # User profile mode
    usernames: list[str] = Field(default_factory=list)
    user_content_type: UserContentType = UserContentType.OVERVIEW

    # Post comments mode
    post_urls: list[str] = Field(default_factory=list)
    max_comments_per_post: int = 100

    # General settings
    max_results: int = 100
    include_comments: bool = False

    @field_validator("subreddits", mode="before")
    @classmethod
    def clean_subreddits(cls, v: list[str] | None) -> list[str]:
        if not v:
            return []
        cleaned = []
        for sub in v:
            s = sub.strip().lstrip("/")
            if s.lower().startswith("r/"):
                s = s[2:]
            s = s.strip("/").strip()
            if s:
                cleaned.append(s)
        return cleaned

    @field_validator("usernames", mode="before")
    @classmethod
    def clean_usernames(cls, v: list[str] | None) -> list[str]:
        if not v:
            return []
        cleaned = []
        for user in v:
            u = user.strip().lstrip("/")
            if u.lower().startswith("u/"):
                u = u[2:]
            u = u.strip("/").strip()
            if u:
                cleaned.append(u)
        return cleaned

    @field_validator("post_urls", mode="before")
    @classmethod
    def clean_post_urls(cls, v: list[str] | None) -> list[str]:
        if not v:
            return []
        return [url.strip() for url in v if url.strip()]

    @classmethod
    def from_actor_input(cls, raw: dict[str, Any]) -> ScraperInput:
        """Map Apify input schema field names to model field names."""
        return cls(
            mode=raw.get("mode", "subreddit_posts"),
            subreddits=raw.get("subreddits", []),
            sort=raw.get("sort", "hot"),
            time_filter=raw.get("timeFilter", "week"),
            search_query=raw.get("searchQuery", ""),
            search_queries_list=raw.get("searchQueriesList", []),
            search_subreddit=raw.get("searchSubreddit", ""),
            search_sort=raw.get("searchSort", "relevance"),
            usernames=raw.get("usernames", []),
            user_content_type=raw.get("userContentType", "overview"),
            post_urls=raw.get("postUrls", []),
            max_comments_per_post=raw.get("maxCommentsPerPost", 100),
            max_results=raw.get("maxResults", 100),
            include_comments=raw.get("includeComments", False),
        )

    def validate_for_mode(self) -> str | None:
        """Return an error message if input is invalid for the selected mode."""
        if self.mode == ScrapingMode.SUBREDDIT_POSTS and not self.subreddits:
            return "At least one subreddit is required for 'Subreddit Posts' mode."
        if self.mode == ScrapingMode.SEARCH and not self.search_query and not self.search_queries_list:
            return "A search query or queries list is required for 'Search Reddit' mode."
        if self.mode == ScrapingMode.USER_PROFILE and not self.usernames:
            return "At least one username is required for 'User Profile' mode."
        if self.mode == ScrapingMode.POST_COMMENTS and not self.post_urls:
            return "At least one post URL is required for 'Post Comments' mode."
        return None


# --- Output Formatters ---


def _utc_from_ts(ts: Any) -> str:
    """Convert a Unix seconds timestamp to ISO 8601 UTC string."""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def format_post_from_json(data: dict[str, Any]) -> dict[str, Any]:
    """Format a post from Reddit OAuth JSON API response data."""
    permalink = data.get("permalink", "")
    is_self = data.get("is_self", False)

    thumbnail = data.get("thumbnail", "")
    if thumbnail in ("self", "default", "nsfw", "spoiler", "image", ""):
        thumbnail = ""

    return {
        "type": "post",
        "id": data.get("id", ""),
        "subreddit": data.get("subreddit", ""),
        "title": data.get("title", ""),
        "author": data.get("author") or "[deleted]",
        "selftext": data.get("selftext", ""),
        "url": f"https://www.reddit.com{permalink}" if permalink else "",
        "externalUrl": "" if is_self else data.get("url", ""),
        "score": int(data.get("score") or 0),
        "numComments": int(data.get("num_comments") or 0),
        "created": _utc_from_ts(data.get("created_utc")),
        "isNSFW": bool(data.get("over_18", False)),
        "isSpoiler": bool(data.get("spoiler", False)),
        "isPinned": bool(data.get("stickied", False)),
        "flair": data.get("link_flair_text") or "",
        "awards": int(data.get("total_awards_received") or 0),
        "domain": data.get("domain", ""),
        "isVideo": bool(data.get("is_video", False)),
        "thumbnail": thumbnail,
        "isPromoted": bool(data.get("promoted", False)),
    }


def format_comment_from_json(data: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Format a comment from Reddit OAuth JSON API response data."""
    link_id = data.get("link_id", "")
    post_id = link_id.replace("t3_", "") if link_id else ""
    permalink = data.get("permalink", "")

    return {
        "type": "comment",
        "id": data.get("id", ""),
        "postId": post_id,
        "subreddit": data.get("subreddit", ""),
        "author": data.get("author") or "[deleted]",
        "body": data.get("body", "[deleted]"),
        "score": int(data.get("score") or 0),
        "created": _utc_from_ts(data.get("created_utc")),
        "depth": depth,
        "isSubmitter": bool(data.get("is_submitter", False)),
        "awards": int(data.get("total_awards_received") or 0),
        "url": f"https://www.reddit.com{permalink}" if permalink else "",
    }
