"""Core Reddit scraping logic using the OAuth JSON API (oauth.reddit.com)."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from .models import (
    ScraperInput,
    ScrapingMode,
    format_comment_from_json,
    format_post_from_json,
)
from .utils import OAUTH_BASE_URL, RateLimiter, fetch_json, parse_post_url

logger = logging.getLogger(__name__)

MAX_PAGES = 40


class RedditScraper:
    """Scrapes Reddit via the OAuth JSON API (oauth.reddit.com)."""

    def __init__(
        self,
        rate_limiter: RateLimiter,
        config: ScraperInput,
        oauth_token: str | None = None,
    ) -> None:
        self.rate_limiter = rate_limiter
        self.config = config
        self.oauth_token = oauth_token

    async def _get_json(
        self, url: str, params: dict[str, Any] | None = None
    ) -> Any | None:
        return await fetch_json(url, self.rate_limiter, params, self.oauth_token)

    async def scrape(self) -> AsyncIterator[dict[str, Any]]:
        """Main entry point — dispatches to the correct mode."""
        mode = self.config.mode
        if mode == ScrapingMode.SUBREDDIT_POSTS:
            async for item in self._scrape_subreddit_posts():
                yield item
        elif mode == ScrapingMode.SEARCH:
            async for item in self._scrape_search():
                yield item
        elif mode == ScrapingMode.USER_PROFILE:
            async for item in self._scrape_user_profiles():
                yield item
        elif mode == ScrapingMode.POST_COMMENTS:
            async for item in self._scrape_post_comments():
                yield item

    async def _paginate_listing(
        self, url: str, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield posts across paginated listing pages using the `after` cursor."""
        current_params = dict(params)
        for _page in range(MAX_PAGES):
            data = await self._get_json(url, current_params)
            if not data or not isinstance(data, dict):
                break

            listing = data.get("data", {})
            children = listing.get("children", [])
            if not children:
                logger.warning(f"No items found on {url}")
                break

            for child in children:
                if child.get("kind") != "t3":
                    continue
                child_data = child.get("data", {})
                if child_data.get("promoted"):
                    continue
                yield format_post_from_json(child_data)

            after = listing.get("after")
            if not after:
                break
            current_params["after"] = after

    # --- Mode 1: Subreddit Posts ---

    async def _scrape_subreddit_posts(self) -> AsyncIterator[dict[str, Any]]:
        for subreddit in self.config.subreddits:
            sort = self.config.sort.value
            logger.info(f"Scraping r/{subreddit} ({sort})")

            url = f"{OAUTH_BASE_URL}/r/{subreddit}/{sort}"
            params: dict[str, Any] = {"limit": 100, "raw_json": 1}
            if sort == "top":
                params["t"] = self.config.time_filter.value

            async for post in self._paginate_listing(url, params):
                yield post
                if self.config.include_comments:
                    async for comment in self._fetch_comments_for_post(post["id"]):
                        yield comment

    # --- Mode 2: Search ---

    async def _scrape_search(self) -> AsyncIterator[dict[str, Any]]:
        queries = self.config.search_queries_list or [self.config.search_query]
        seen_ids: set[str] = set()

        for query in queries:
            logger.info(f"Searching Reddit for: '{query}'")

            if self.config.search_subreddit:
                url = f"{OAUTH_BASE_URL}/r/{self.config.search_subreddit}/search"
                params: dict[str, Any] = {
                    "q": query,
                    "restrict_sr": "on",
                    "sort": self.config.search_sort.value,
                    "limit": 100,
                    "raw_json": 1,
                }
            else:
                url = f"{OAUTH_BASE_URL}/search"
                params = {
                    "q": query,
                    "sort": self.config.search_sort.value,
                    "limit": 100,
                    "raw_json": 1,
                }

            if self.config.search_sort.value == "top":
                params["t"] = self.config.time_filter.value

            async for post in self._paginate_listing(url, params):
                if post["id"] in seen_ids:
                    continue
                seen_ids.add(post["id"])
                yield post
                if self.config.include_comments and post["id"]:
                    async for comment in self._fetch_comments_for_post(post["id"]):
                        yield comment

    # --- Mode 3: User Profiles ---

    async def _scrape_user_profiles(self) -> AsyncIterator[dict[str, Any]]:
        for username in self.config.usernames:
            content_type = self.config.user_content_type.value
            logger.info(f"Scraping u/{username} ({content_type})")

            if content_type == "submitted":
                url = f"{OAUTH_BASE_URL}/user/{username}/submitted"
            elif content_type == "comments":
                url = f"{OAUTH_BASE_URL}/user/{username}/comments"
            else:  # overview
                url = f"{OAUTH_BASE_URL}/user/{username}/overview"

            current_params: dict[str, Any] = {"limit": 100, "raw_json": 1}

            for _page in range(MAX_PAGES):
                data = await self._get_json(url, current_params)
                if not data or not isinstance(data, dict):
                    break

                listing = data.get("data", {})
                children = listing.get("children", [])
                if not children:
                    break

                for child in children:
                    kind = child.get("kind")
                    child_data = child.get("data", {})
                    if kind == "t3" and not child_data.get("promoted"):
                        yield format_post_from_json(child_data)
                    elif kind == "t1":
                        yield format_comment_from_json(child_data)

                after = listing.get("after")
                if not after:
                    break
                current_params["after"] = after

    # --- Mode 4: Post Comments ---

    async def _scrape_post_comments(self) -> AsyncIterator[dict[str, Any]]:
        for post_url in self.config.post_urls:
            parsed = parse_post_url(post_url)
            if not parsed:
                logger.warning(f"Skipping invalid post URL: {post_url}")
                continue

            subreddit, post_id = parsed
            logger.info(f"Scraping comments from r/{subreddit} post {post_id}")

            url = f"{OAUTH_BASE_URL}/r/{subreddit}/comments/{post_id}"
            data = await self._get_json(url, {"limit": 500, "raw_json": 1})

            if not data or not isinstance(data, list) or len(data) < 2:
                logger.warning(f"No data returned for post {post_id}")
                continue

            # First element: the post itself
            post_children = data[0].get("data", {}).get("children", [])
            for child in post_children:
                if child.get("kind") == "t3":
                    yield format_post_from_json(child.get("data", {}))

            # Second element: nested comment tree — flatten it
            comment_children = data[1].get("data", {}).get("children", [])
            max_comments = self.config.max_comments_per_post
            count = 0
            for comment in self._walk_comments(comment_children):
                yield comment
                count += 1
                if max_comments > 0 and count >= max_comments:
                    break

    # --- Helpers ---

    async def _fetch_comments_for_post(
        self, post_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Fetch comments for a post by ID (no subreddit needed)."""
        url = f"{OAUTH_BASE_URL}/comments/{post_id}"
        data = await self._get_json(url, {"limit": 500, "raw_json": 1})
        if not data or not isinstance(data, list) or len(data) < 2:
            return
        comment_children = data[1].get("data", {}).get("children", [])
        for comment in self._walk_comments(comment_children):
            yield comment

    def _walk_comments(
        self, children: list[dict], depth: int = 0
    ) -> list[dict[str, Any]]:
        """Recursively flatten a nested comment tree into a list."""
        results: list[dict[str, Any]] = []
        for child in children:
            if child.get("kind") != "t1":
                continue
            data = child.get("data", {})
            results.append(format_comment_from_json(data, depth=depth))
            replies = data.get("replies")
            if isinstance(replies, dict):
                reply_children = replies.get("data", {}).get("children", [])
                results.extend(self._walk_comments(reply_children, depth=depth + 1))
        return results
