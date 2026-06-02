"""Core Reddit scraping logic. All 4 modes: subreddit_posts, search, user_profile, post_comments.

Reddit's `.json` API now returns 403. We scrape old.reddit.com's server-rendered
HTML instead, parsing `<div class="thing">` elements with BeautifulSoup.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from bs4 import BeautifulSoup

from .models import (
    ScraperInput,
    ScrapingMode,
    format_comment_from_thing,
    format_post_from_thing,
)
from .utils import BASE_URL, RateLimiter, fetch_html, parse_post_url

logger = logging.getLogger(__name__)

# How many listing pages to follow before stopping (Reddit caps ~1000 items).
MAX_PAGES = 40


class RedditScraper:
    """Scrapes Reddit by parsing old.reddit.com HTML."""

    def __init__(
        self,
        rate_limiter: RateLimiter,
        config: ScraperInput,
        proxy_config: Any = None,
    ) -> None:
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

    # --- HTML helpers ---

    async def _get_soup(
        self, url: str, params: dict[str, Any] | None = None
    ) -> BeautifulSoup | None:
        html = await fetch_html(url, self.rate_limiter, params, self.proxy_config)
        if not html:
            return None
        return BeautifulSoup(html, "lxml")

    @staticmethod
    def _post_things(soup: BeautifulSoup) -> list[Any]:
        """Return non-promoted link `thing` elements from a listing page."""
        things = []
        for thing in soup.select('div.thing[data-fullname^="t3_"]'):
            if thing.get("data-promoted") == "true":
                continue
            things.append(thing)
        return things

    @staticmethod
    def _next_url(soup: BeautifulSoup) -> str | None:
        """Return the 'next page' URL from a listing's pagination, if any."""
        next_link = soup.select_one(".next-button a")
        if next_link and next_link.get("href"):
            return next_link["href"]
        return None

    async def _paginate_posts(
        self, url: str, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield formatted posts across paginated listing pages."""
        page = 0
        current_url = url
        current_params: dict[str, Any] | None = params

        while True:
            soup = await self._get_soup(current_url, current_params)
            if soup is None:
                break

            things = self._post_things(soup)
            if not things:
                logger.warning(f"No posts found on {current_url}")
                break

            for thing in things:
                yield format_post_from_thing(thing)

            next_url = self._next_url(soup)
            if not next_url:
                break

            page += 1
            if page >= MAX_PAGES:
                logger.info("Reached pagination limit")
                break

            # The next URL already carries count/after query params.
            current_url = next_url
            current_params = None

    # --- Mode 1: Subreddit Posts ---

    async def _scrape_subreddit_posts(self) -> AsyncIterator[dict[str, Any]]:
        for subreddit in self.config.subreddits:
            sort = self.config.sort.value
            logger.info(f"Scraping r/{subreddit} ({sort})")

            url = f"{BASE_URL}/r/{subreddit}/{sort}/"
            params: dict[str, Any] = {"limit": 25}
            if sort == "top":
                params["t"] = self.config.time_filter.value

            async for post in self._paginate_posts(url, params):
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
                url = f"{BASE_URL}/r/{self.config.search_subreddit}/search/"
                params: dict[str, Any] = {
                    "q": query,
                    "restrict_sr": "on",
                    "sort": self.config.search_sort.value,
                    "limit": 25,
                }
            else:
                url = f"{BASE_URL}/search/"
                params = {
                    "q": query,
                    "sort": self.config.search_sort.value,
                    "limit": 25,
                }

            if self.config.search_sort.value == "top":
                params["t"] = self.config.time_filter.value

            async for post in self._paginate_posts(url, params):
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
                url = f"{BASE_URL}/user/{username}/submitted/"
            elif content_type == "comments":
                url = f"{BASE_URL}/user/{username}/comments/"
            else:  # overview
                url = f"{BASE_URL}/user/{username}/"

            params: dict[str, Any] = {"limit": 25}
            page = 0
            current_url = url
            current_params: dict[str, Any] | None = params

            while True:
                soup = await self._get_soup(current_url, current_params)
                if soup is None:
                    break

                things = soup.select("div.thing[data-fullname]")
                if not things:
                    break

                for thing in things:
                    fullname = thing.get("data-fullname", "")
                    if fullname.startswith("t3_"):
                        if thing.get("data-promoted") == "true":
                            continue
                        yield format_post_from_thing(thing)
                    elif fullname.startswith("t1_"):
                        yield format_comment_from_thing(thing)

                next_url = self._next_url(soup)
                if not next_url:
                    break
                page += 1
                if page >= MAX_PAGES:
                    break
                current_url = next_url
                current_params = None

    # --- Mode 4: Post Comments ---

    async def _scrape_post_comments(self) -> AsyncIterator[dict[str, Any]]:
        for post_url in self.config.post_urls:
            parsed = parse_post_url(post_url)
            if not parsed:
                logger.warning(f"Skipping invalid post URL: {post_url}")
                continue

            subreddit, post_id = parsed
            logger.info(f"Scraping comments from r/{subreddit} post {post_id}")

            url = f"{BASE_URL}/r/{subreddit}/comments/{post_id}/"
            soup = await self._get_soup(url, {"limit": 500})
            if soup is None:
                logger.warning(f"No data returned for post {post_id}")
                continue

            # Yield the post itself (the single t3_ thing on the page)
            post_thing = soup.select_one('div.thing[data-fullname^="t3_"]')
            if post_thing is not None:
                yield format_post_from_thing(post_thing)

            for comment in self._parse_comments(soup):
                yield comment

    # --- Helpers ---

    async def _fetch_comments_for_post(
        self, post_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Fetch comments for a single post by id (subreddit inferred by Reddit)."""
        if not post_id:
            return
        url = f"{BASE_URL}/comments/{post_id}/"
        soup = await self._get_soup(url, {"limit": 500})
        if soup is None:
            return
        for comment in self._parse_comments(soup):
            yield comment

    def _parse_comments(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Parse all comment things from a post page into flat output.

        Depth is derived from how many `.child` wrappers a comment nests inside.
        """
        results: list[dict[str, Any]] = []
        max_comments = self.config.max_comments_per_post

        for thing in soup.select('div.thing[data-fullname^="t1_"]'):
            depth = len(thing.find_parents("div", class_="child"))
            results.append(format_comment_from_thing(thing, depth=depth))
            if max_comments > 0 and len(results) >= max_comments:
                break

        return results
