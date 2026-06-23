"""Core Reddit scraping logic. All 4 modes: subreddit_posts, search, user_profile, post_comments.

Fetches Reddit `.json` endpoints (www.reddit.com) via Playwright after a one-time
network-security warm-up, then parses the standard Listing JSON.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from .models import (
    ScraperInput,
    ScrapingMode,
    format_comment_from_json,
    format_post_from_json,
)
from .utils import BASE_URL, PageFetcher, parse_post_url

logger = logging.getLogger(__name__)

MAX_PAGES = 40
MAX_PAGES_FREE = 1
EMPTY_PAGE_ABORT = 2


class RedditScraper:
    """Scrapes Reddit by fetching www.reddit.com `.json` endpoints."""

    def __init__(
        self,
        fetcher: PageFetcher,
        config: ScraperInput,
        max_pages: int = MAX_PAGES,
    ) -> None:
        self.fetcher = fetcher
        self.config = config
        self.max_pages = max_pages

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

    # --- JSON listing helpers ---

    @staticmethod
    def _children(listing: Any) -> list[dict[str, Any]]:
        """Return the children array from a Listing object, or []."""
        if not isinstance(listing, dict):
            return []
        return listing.get("data", {}).get("children", []) or []

    @staticmethod
    def _after(listing: Any) -> str | None:
        """Return the pagination cursor (data.after) from a Listing, or None."""
        if not isinstance(listing, dict):
            return None
        return listing.get("data", {}).get("after")

    async def _paginate_listing(
        self,
        url: str,
        params: dict[str, Any],
        kinds: tuple[str, ...] = ("t3",),
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield formatted items across a paginated Listing endpoint.

        `kinds` selects which child kinds to emit: t3 (posts), t1 (comments).
        Pagination follows the `after` cursor until exhausted or max_pages.
        """
        page = 0
        empty_streak = 0
        after: str | None = None

        while True:
            p = dict(params)
            if after:
                p["after"] = after

            listing = await self.fetcher.fetch_json(url, p)
            children = self._children(listing)

            if not children:
                empty_streak += 1
                logger.warning(
                    f"No items on {url} (after={after}, empty streak: {empty_streak})"
                )
                next_after = self._after(listing)
                if empty_streak >= EMPTY_PAGE_ABORT or not next_after:
                    break
                after = next_after
                continue
            empty_streak = 0

            for child in children:
                kind = child.get("kind")
                data = child.get("data", {})
                if kind == "t3" and "t3" in kinds:
                    yield format_post_from_json(data)
                elif kind == "t1" and "t1" in kinds:
                    yield format_comment_from_json(data)

            after = self._after(listing)
            if not after:
                break
            page += 1
            if page >= self.max_pages:
                logger.info("Reached pagination limit")
                break

    # --- Mode 1: Subreddit Posts ---

    async def _scrape_subreddit_posts(self) -> AsyncIterator[dict[str, Any]]:
        for subreddit in self.config.subreddits:
            sort = self.config.sort.value
            logger.info(f"Scraping r/{subreddit} ({sort})")

            url = f"{BASE_URL}/r/{subreddit}/{sort}/.json"
            params: dict[str, Any] = {"limit": 25, "raw_json": 1}
            if sort == "top":
                params["t"] = self.config.time_filter.value

            async for post in self._paginate_listing(url, params, kinds=("t3",)):
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
                url = f"{BASE_URL}/r/{self.config.search_subreddit}/search/.json"
                params: dict[str, Any] = {
                    "q": query,
                    "restrict_sr": "on",
                    "sort": self.config.search_sort.value,
                    "limit": 25,
                    "raw_json": 1,
                }
            else:
                url = f"{BASE_URL}/search/.json"
                params = {
                    "q": query,
                    "sort": self.config.search_sort.value,
                    "limit": 25,
                    "raw_json": 1,
                }

            if self.config.search_sort.value == "top":
                params["t"] = self.config.time_filter.value

            async for post in self._paginate_listing(url, params, kinds=("t3",)):
                post_id = post["id"]
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                yield post
                if self.config.include_comments and post_id:
                    async for comment in self._fetch_comments_for_post(post_id):
                        yield comment

    # --- Mode 3: User Profiles ---

    async def _scrape_user_profiles(self) -> AsyncIterator[dict[str, Any]]:
        for username in self.config.usernames:
            content_type = self.config.user_content_type.value
            logger.info(f"Scraping u/{username} ({content_type})")

            if content_type == "submitted":
                url = f"{BASE_URL}/user/{username}/submitted/.json"
                kinds: tuple[str, ...] = ("t3",)
            elif content_type == "comments":
                url = f"{BASE_URL}/user/{username}/comments/.json"
                kinds = ("t1",)
            else:  # overview
                url = f"{BASE_URL}/user/{username}/.json"
                kinds = ("t3", "t1")

            params: dict[str, Any] = {"limit": 25, "raw_json": 1}
            async for item in self._paginate_listing(url, params, kinds=kinds):
                yield item

    # --- Mode 4: Post Comments ---

    async def _scrape_post_comments(self) -> AsyncIterator[dict[str, Any]]:
        for post_url in self.config.post_urls:
            parsed = parse_post_url(post_url)
            if not parsed:
                logger.warning(f"Skipping invalid post URL: {post_url}")
                continue

            subreddit, post_id = parsed
            logger.info(f"Scraping comments from r/{subreddit} post {post_id}")

            url = f"{BASE_URL}/r/{subreddit}/comments/{post_id}/.json"
            data = await self.fetcher.fetch_json(url, {"limit": 500, "raw_json": 1})
            if not data:
                logger.warning(f"No data returned for post {post_id}")
                continue

            # Comment endpoints return [post_listing, comments_listing].
            post_children = self._children(data[0]) if isinstance(data, list) and data else []
            if post_children:
                yield format_post_from_json(post_children[0].get("data", {}))

            comment_listing = data[1] if isinstance(data, list) and len(data) > 1 else None
            results: list[dict[str, Any]] = []
            self._flatten_comments(self._children(comment_listing), 0, results)
            for comment in results:
                yield comment

    # --- Helpers ---

    async def _fetch_comments_for_post(
        self, post_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        if not post_id:
            return
        url = f"{BASE_URL}/comments/{post_id}/.json"
        data = await self.fetcher.fetch_json(url, {"limit": 500, "raw_json": 1})
        if not data or not isinstance(data, list) or len(data) < 2:
            return
        results: list[dict[str, Any]] = []
        self._flatten_comments(self._children(data[1]), 0, results)
        for comment in results:
            yield comment

    def _flatten_comments(
        self,
        children: list[dict[str, Any]],
        depth: int,
        results: list[dict[str, Any]],
    ) -> None:
        """Depth-first flatten a comment tree into `results`, honoring the cap."""
        max_comments = self.config.max_comments_per_post
        for child in children:
            if child.get("kind") != "t1":  # skip "more" placeholders
                continue
            data = child.get("data", {})
            results.append(format_comment_from_json(data, depth=depth))
            if max_comments > 0 and len(results) >= max_comments:
                return

            replies = data.get("replies")
            if isinstance(replies, dict):
                self._flatten_comments(self._children(replies), depth + 1, results)
                if max_comments > 0 and len(results) >= max_comments:
                    return
