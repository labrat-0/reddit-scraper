"""Core Reddit scraping logic. All 4 modes: subreddit_posts, search, user_profile, post_comments."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

import httpx

from .models import (
    ScraperInput,
    ScrapingMode,
    format_comment,
    format_post,
    format_user_item,
)
from .utils import BASE_URL, RateLimiter, fetch_json, parse_post_url

logger = logging.getLogger(__name__)


class RedditScraper:
    """Scrapes Reddit using www.reddit.com JSON endpoints."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        rate_limiter: RateLimiter,
        config: ScraperInput,
        proxy_config: Any = None,
    ) -> None:
        self.client = client
        self.rate_limiter = rate_limiter
        self.config = config
        self.proxy_config = proxy_config

    async def scrape(self) -> AsyncIterator[dict[str, Any]]:
        """Main entry point -- dispatches to the correct mode."""
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

    # --- Mode 1: Subreddit Posts ---

    async def _scrape_subreddit_posts(self) -> AsyncIterator[dict[str, Any]]:
        """Scrape posts from one or more subreddits."""
        for subreddit in self.config.subreddits:
            logger.info(f"Scraping r/{subreddit} ({self.config.sort.value})")

            url = f"{BASE_URL}/r/{subreddit}/{self.config.sort.value}.json"
            params: dict[str, Any] = {"limit": 25, "raw_json": 1}

            if self.config.sort.value == "top":
                params["t"] = self.config.time_filter.value

            async for post in self._paginate_listing(url, params):
                formatted = format_post(post)
                yield formatted

                # Optionally fetch comments for each post
                if self.config.include_comments:
                    async for comment in self._fetch_comments_for_post(
                        subreddit, post.get("id", "")
                    ):
                        yield comment

    # --- Mode 2: Search ---

    async def _scrape_search(self) -> AsyncIterator[dict[str, Any]]:
        """Search Reddit for posts matching one or more queries."""
        # Build the list of queries to run
        queries = self.config.search_queries_list or [self.config.search_query]
        seen_ids: set[str] = set()

        for query in queries:
            logger.info(f"Searching Reddit for: '{query}'")

            if self.config.search_subreddit:
                url = f"{BASE_URL}/r/{self.config.search_subreddit}/search.json"
                params: dict[str, Any] = {
                    "q": query,
                    "restrict_sr": "on",
                    "sort": self.config.search_sort.value,
                    "limit": 25,
                    "raw_json": 1,
                }
            else:
                url = f"{BASE_URL}/search.json"
                params = {
                    "q": query,
                    "sort": self.config.search_sort.value,
                    "limit": 25,
                    "raw_json": 1,
                }

            if self.config.search_sort.value == "top":
                params["t"] = self.config.time_filter.value

            async for post in self._paginate_listing(url, params):
                post_id = post.get("id", "")
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                formatted = format_post(post)
                yield formatted

                if self.config.include_comments:
                    subreddit = post.get("subreddit", "")
                    if subreddit and post_id:
                        async for comment in self._fetch_comments_for_post(
                            subreddit, post_id
                        ):
                            yield comment

    # --- Mode 3: User Profiles ---

    async def _scrape_user_profiles(self) -> AsyncIterator[dict[str, Any]]:
        """Scrape posts and/or comments from user profiles."""
        for username in self.config.usernames:
            content_type = self.config.user_content_type.value
            logger.info(f"Scraping u/{username} ({content_type})")

            if content_type == "overview":
                url = f"{BASE_URL}/user/{username}/.json"
            elif content_type == "submitted":
                url = f"{BASE_URL}/user/{username}/submitted.json"
            else:  # comments
                url = f"{BASE_URL}/user/{username}/comments.json"

            params: dict[str, Any] = {"limit": 25, "raw_json": 1}

            async for item in self._paginate_listing(url, params, is_user=True):
                item_data = dict(item)
                formatted = format_user_item(item_data)
                if formatted:
                    yield formatted

    # --- Mode 4: Post Comments ---

    async def _scrape_post_comments(self) -> AsyncIterator[dict[str, Any]]:
        """Scrape comments from specific Reddit posts."""
        for post_url in self.config.post_urls:
            parsed = parse_post_url(post_url)
            if not parsed:
                logger.warning(f"Skipping invalid post URL: {post_url}")
                continue

            subreddit, post_id = parsed
            logger.info(f"Scraping comments from r/{subreddit} post {post_id}")

            url = f"{BASE_URL}/r/{subreddit}/comments/{post_id}.json"
            params: dict[str, Any] = {"limit": 500, "raw_json": 1}

            data = await fetch_json(self.client, url, self.rate_limiter, params, self.proxy_config)
            if not data or not isinstance(data, list) or len(data) < 2:
                logger.warning(f"No data returned for post {post_id}")
                continue

            # First element is the post itself
            post_listing = data[0]
            if (
                isinstance(post_listing, dict)
                and "data" in post_listing
                and "children" in post_listing["data"]
            ):
                for child in post_listing["data"]["children"]:
                    if child.get("kind") == "t3":
                        yield format_post(child["data"])

            # Second element is the comment tree
            comment_listing = data[1]
            comment_count = 0
            max_comments = self.config.max_comments_per_post

            if (
                isinstance(comment_listing, dict)
                and "data" in comment_listing
                and "children" in comment_listing["data"]
            ):
                for comment in self._walk_comment_tree(
                    comment_listing["data"]["children"], depth=0
                ):
                    if max_comments > 0 and comment_count >= max_comments:
                        break
                    yield comment
                    comment_count += 1

    # --- Helpers ---

    async def _paginate_listing(
        self,
        url: str,
        params: dict[str, Any],
        is_user: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """Paginate through a Reddit listing endpoint using after cursors."""
        after: str | None = None
        page = 0

        while True:
            current_params = dict(params)
            if after:
                current_params["after"] = after

            data = await fetch_json(
                self.client, url, self.rate_limiter, current_params, self.proxy_config
            )

            if not data or not isinstance(data, dict):
                logger.warning(f"Unexpected response type from {url}: {type(data)}")
                break

            listing = data.get("data", {})
            children = listing.get("children", [])

            if not children:
                if not listing:
                    logger.warning(
                        f"Unexpected response structure from {url}: "
                        f"top-level keys={list(data.keys())[:8]}"
                    )
                break

            for child in children:
                kind = child.get("kind", "")
                child_data = child.get("data", {})

                if is_user:
                    # Tag with kind so format_user_item knows the type
                    child_data["_kind"] = kind

                yield child_data

            # Check for next page
            after = listing.get("after")
            if not after:
                break

            page += 1
            # Reddit caps pagination at ~4 pages of 100 (roughly 400 items)
            if page >= 40:
                logger.info("Reached pagination limit")
                break

    async def _fetch_comments_for_post(
        self, subreddit: str, post_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Fetch comments for a single post."""
        url = f"{BASE_URL}/r/{subreddit}/comments/{post_id}.json"
        params: dict[str, Any] = {"limit": 500, "raw_json": 1}

        data = await fetch_json(self.client, url, self.rate_limiter, params, self.proxy_config)
        if not data or not isinstance(data, list) or len(data) < 2:
            return

        comment_listing = data[1]
        comment_count = 0
        max_comments = self.config.max_comments_per_post

        if (
            isinstance(comment_listing, dict)
            and "data" in comment_listing
            and "children" in comment_listing["data"]
        ):
            for comment in self._walk_comment_tree(
                comment_listing["data"]["children"], depth=0
            ):
                if max_comments > 0 and comment_count >= max_comments:
                    break
                yield comment
                comment_count += 1

    def _walk_comment_tree(
        self, children: list[dict[str, Any]], depth: int = 0
    ) -> list[dict[str, Any]]:
        """Recursively walk a comment tree and return flattened comments."""
        results = []

        for child in children:
            kind = child.get("kind", "")

            if kind == "t1":
                comment_data = child.get("data", {})
                results.append(format_comment(comment_data, depth=depth))

                # Recurse into replies
                replies = comment_data.get("replies", "")
                if isinstance(replies, dict):
                    reply_children = (
                        replies.get("data", {}).get("children", [])
                    )
                    results.extend(
                        self._walk_comment_tree(reply_children, depth=depth + 1)
                    )

            elif kind == "more":
                # "Load more comments" nodes -- we skip these to avoid
                # additional API calls. Could be implemented later.
                pass

        return results
