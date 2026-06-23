"""Pydantic models for Reddit Scraper input validation and output formatting."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from urllib.parse import urlparse

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


def _utc_from_ms(ts_ms: Any) -> str:
    """Convert a millisecond timestamp string/int to ISO 8601 UTC string."""
    try:
        return datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def _utc_from_sec(ts_sec: Any) -> str:
    """Convert a second-precision epoch (Reddit's created_utc) to ISO 8601 UTC."""
    try:
        return datetime.fromtimestamp(float(ts_sec), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _leading_int(text: str, default: int = 0) -> int:
    """Extract the first integer from a string like '3 points' or '51 comments'."""
    if not text:
        return default
    m = re.search(r"-?\d[\d,]*", text)
    return int(m.group().replace(",", "")) if m else default


def _thumbnail_url(value: Any) -> str:
    """Reddit's `thumbnail` is a URL or a sentinel (self/default/nsfw/spoiler/'')."""
    if isinstance(value, str) and value.startswith("http"):
        return value
    return ""


def format_post_from_json(d: dict[str, Any]) -> dict[str, Any]:
    """Format a post (t3) from a Reddit JSON `data` object.

    Output keys match `format_post_from_thing` so the dataset schema is stable
    across the HTML→JSON migration.
    """
    permalink = d.get("permalink", "")
    is_self = bool(d.get("is_self"))
    return {
        "type": "post",
        "id": d.get("id", ""),
        "subreddit": d.get("subreddit", ""),
        "title": d.get("title", ""),
        "author": d.get("author", "[deleted]"),
        "selftext": d.get("selftext", "") or "",
        "url": f"https://www.reddit.com{permalink}" if permalink else "",
        "externalUrl": "" if is_self else (d.get("url", "") or ""),
        "score": _int(d.get("score")),
        "numComments": _int(d.get("num_comments")),
        "created": _utc_from_sec(d.get("created_utc")),
        "isNSFW": bool(d.get("over_18")),
        "isSpoiler": bool(d.get("spoiler")),
        "isPinned": bool(d.get("stickied")),
        "flair": d.get("link_flair_text") or "",
        "awards": _int(d.get("total_awards_received")),
        "domain": d.get("domain", ""),
        "isVideo": bool(d.get("is_video")),
        "thumbnail": _thumbnail_url(d.get("thumbnail")),
        "isPromoted": False,
    }


def format_comment_from_json(d: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Format a comment (t1) from a Reddit JSON `data` object."""
    permalink = d.get("permalink", "")
    return {
        "type": "comment",
        "id": d.get("id", ""),
        "postId": (d.get("link_id", "") or "").replace("t3_", ""),
        "subreddit": d.get("subreddit", ""),
        "author": d.get("author", "[deleted]"),
        "body": d.get("body", "") or "[deleted]",
        "score": _int(d.get("score")),
        "created": _utc_from_sec(d.get("created_utc")),
        "depth": _int(d.get("depth"), depth),
        "isSubmitter": bool(d.get("is_submitter")),
        "awards": _int(d.get("total_awards_received")),
        "url": f"https://www.reddit.com{permalink}" if permalink else "",
    }


def format_post_from_thing(thing: Any) -> dict[str, Any]:
    """Format a post from an old.reddit `<div class="thing">` BeautifulSoup tag."""
    attrs = thing.attrs
    classes = attrs.get("class", [])
    fullname = attrs.get("data-fullname", "")
    post_id = fullname.replace("t3_", "")
    permalink = attrs.get("data-permalink", "")
    domain = attrs.get("data-domain", "")
    is_self = domain.startswith("self.")

    title_el = thing.select_one("a.title")
    title = title_el.get_text(strip=True) if title_el else ""

    selftext_el = thing.select_one(".expando .usertext-body")
    selftext = selftext_el.get_text("\n", strip=True) if selftext_el else ""

    flair_el = thing.select_one(".linkflairlabel")
    flair = flair_el.get_text(strip=True) if flair_el else ""

    thumb_img = thing.select_one("a.thumbnail img")
    thumbnail = ""
    if thumb_img and thumb_img.get("src"):
        src = thumb_img["src"]
        thumbnail = f"https:{src}" if src.startswith("//") else src

    is_video = domain in ("v.redd.it", "youtube.com", "youtu.be") or (
        attrs.get("data-url", "").endswith((".mp4", ".gifv"))
    )

    return {
        "type": "post",
        "id": post_id,
        "subreddit": attrs.get("data-subreddit", ""),
        "title": title,
        "author": attrs.get("data-author", "[deleted]"),
        "selftext": selftext,
        "url": f"https://www.reddit.com{permalink}",
        "externalUrl": "" if is_self else attrs.get("data-url", ""),
        "score": _int(attrs.get("data-score")),
        "numComments": _int(attrs.get("data-comments-count")),
        "created": _utc_from_ms(attrs.get("data-timestamp")),
        "isNSFW": attrs.get("data-nsfw") == "true",
        "isSpoiler": attrs.get("data-spoiler") == "true",
        "isPinned": "stickied" in classes,
        "flair": flair,
        "awards": _int(attrs.get("data-gildings")),
        "domain": domain,
        "isVideo": is_video,
        "thumbnail": thumbnail,
        "isPromoted": attrs.get("data-promoted") == "true",
    }


def format_post_from_search_result(result: Any) -> dict[str, Any]:
    """Format a post from an old.reddit `div.search-result-link` BeautifulSoup tag.

    Search pages use a different markup than listings: data lives in child elements
    (`.search-score`, `a.search-comments`, ...) rather than `data-*` attributes.
    Output keys match `format_post_from_thing` so the dataset schema stays consistent.
    """
    fullname = result.attrs.get("data-fullname", "")
    post_id = fullname.replace("t3_", "")

    title_el = result.select_one("a.search-title")
    title = title_el.get_text(strip=True) if title_el else ""
    title_href = title_el.get("href", "") if title_el else ""

    comments_el = result.select_one("a.search-comments")
    num_comments = _leading_int(comments_el.get_text()) if comments_el else 0

    # Permalink: search-comments href is always the /comments/ URL; fall back to thumbnail.
    permalink = ""
    for candidate in (
        comments_el.get("href") if comments_el else "",
        (result.select_one("a.thumbnail") or {}).get("href")
        if result.select_one("a.thumbnail")
        else "",
    ):
        if candidate and "/comments/" in candidate:
            permalink = urlparse(candidate).path or candidate
            break

    sub_el = result.select_one("a.search-subreddit-link")
    subreddit = sub_el.get_text(strip=True) if sub_el else ""
    if subreddit.lower().startswith("r/"):
        subreddit = subreddit[2:]
    if not subreddit:
        parts = [p for p in permalink.split("/") if p]
        if len(parts) >= 2 and parts[0] == "r":
            subreddit = parts[1]

    author_el = result.select_one(".search-author a.author")
    author = author_el.get_text(strip=True) if author_el else "[deleted]"

    score_el = result.select_one(".search-score")
    score = _leading_int(score_el.get_text()) if score_el else 0

    time_el = result.select_one(".search-time time")
    created = time_el.get("datetime", "") if time_el else ""

    body_el = result.select_one(".search-result-body .md")
    selftext = body_el.get_text("\n", strip=True) if body_el else ""

    flair_el = result.select_one(".linkflairlabel")
    flair = flair_el.get_text(strip=True) if flair_el else ""

    # A title link that isn't a /comments/ URL means it's an external link post.
    external_url = ""
    domain = ""
    if title_href and "/comments/" not in title_href:
        external_url = title_href
        domain = urlparse(title_href).netloc

    thumb_img = result.select_one("a.thumbnail img")
    thumbnail = ""
    if thumb_img and thumb_img.get("src"):
        src = thumb_img["src"]
        thumbnail = f"https:{src}" if src.startswith("//") else src

    is_video = domain in ("v.redd.it", "youtube.com", "youtu.be")

    return {
        "type": "post",
        "id": post_id,
        "subreddit": subreddit,
        "title": title,
        "author": author,
        "selftext": selftext,
        "url": f"https://www.reddit.com{permalink}" if permalink else title_href,
        "externalUrl": external_url,
        "score": score,
        "numComments": num_comments,
        "created": created,
        "isNSFW": False,
        "isSpoiler": False,
        "isPinned": False,
        "flair": flair,
        "awards": 0,
        "domain": domain,
        "isVideo": is_video,
        "thumbnail": thumbnail,
        "isPromoted": False,
    }


def format_comment_from_thing(thing: Any, depth: int = 0) -> dict[str, Any]:
    """Format a comment from an old.reddit `<div class="thing">` BeautifulSoup tag."""
    attrs = thing.attrs
    classes = attrs.get("class", [])
    fullname = attrs.get("data-fullname", "")
    comment_id = fullname.replace("t1_", "")
    permalink = attrs.get("data-permalink", "")

    post_id = ""
    parts = [p for p in permalink.split("/") if p]
    if len(parts) >= 4 and parts[2] == "comments":
        post_id = parts[3]

    body_el = thing.select_one(".entry .usertext-body")
    body = body_el.get_text("\n", strip=True) if body_el else "[deleted]"

    score_el = thing.select_one(".score.unvoted")
    score = _int(score_el.get("title")) if score_el else 0

    time_el = thing.select_one(".tagline time")
    created = time_el.get("datetime", "") if time_el else ""

    return {
        "type": "comment",
        "id": comment_id,
        "postId": post_id,
        "subreddit": attrs.get("data-subreddit", ""),
        "author": attrs.get("data-author", "[deleted]"),
        "body": body,
        "score": score,
        "created": created,
        "depth": depth,
        "isSubmitter": "submitter" in classes,
        "awards": _int(attrs.get("data-gildings")),
        "url": f"https://www.reddit.com{permalink}",
    }
