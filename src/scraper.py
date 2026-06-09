"""Core Reddit scraping logic. All 4 modes: subreddit_posts, search, user_profile, post_comments.

Fetches old.reddit.com server-rendered HTML via Playwright (real Chromium browser),
then parses `<div class="thing">` elements with BeautifulSoup.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from bs4 import BeautifulSoup

from .models import (
    ScraperInput,
    ScrapingMode,
    format_comment_from_thing,
    format_post_from_search_result,
    format_post_from_thing,
)
from .utils import BASE_URL, PageFetcher, parse_post_url

logger = logging.getLogger(__name__)

MAX_PAGES = 40
MAX_PAGES_FREE = 1
EMPTY_PAGE_ABORT = 2


class RedditScraper:
    """Scrapes Reddit by parsing old.reddit.com HTML via a headless browser."""

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

    # --- HTML helpers ---

    async def _get_soup(
        self, url: str, params: dict[str, Any] | None = None
    ) -> BeautifulSoup | None:
        html = await self.fetcher.fetch(url, params)
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

    @staticmethod
    def _search_things(soup: BeautifulSoup) -> list[Any]:
        """Return link search-result elements from a search page."""
        return soup.select('div.search-result-link[data-fullname^="t3_"]')

    @staticmethod
    def _next_search_url(soup: BeautifulSoup) -> str | None:
        """Return the 'next page' URL for search results.

        Search pages render two paginators (subreddit matches via `type=sr`, and link
        results via `after=t3_`). Prefer the link-results one.
        """
        next_links = soup.select('.nextprev a[rel~="next"]')
        for link in next_links:
            href = link.get("href", "")
            if "after=t3_" in href:
                return href
        if next_links and next_links[0].get("href"):
            return next_links[0]["href"]
        return None

    async def _paginate_search(
        self, url: str, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield formatted posts across paginated search-result pages."""
        page = 0
        empty_streak = 0
        current_url = url
        current_params: dict[str, Any] | None = params

        while True:
            soup = await self._get_soup(current_url, current_params)
            if soup is None:
                break

            results = self._search_things(soup)
            if not results:
                empty_streak += 1
                logger.warning(f"No posts found on {current_url} (empty streak: {empty_streak})")
                if empty_streak >= EMPTY_PAGE_ABORT:
                    logger.warning("Consecutive empty pages — aborting search pagination")
                    break
                continue
            empty_streak = 0

            for result in results:
                yield format_post_from_search_result(result)

            next_url = self._next_search_url(soup)
            if not next_url:
                break

            page += 1
            if page >= self.max_pages:
                logger.info("Reached pagination limit")
                break

            current_url = next_url
            current_params = None

    async def _paginate_posts(
        self, url: str, params: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield formatted posts across paginated listing pages."""
        page = 0
        empty_streak = 0
        current_url = url
        current_params: dict[str, Any] | None = params

        while True:
            soup = await self._get_soup(current_url, current_params)
            if soup is None:
                break

            things = self._post_things(soup)
            if not things:
                empty_streak += 1
                logger.warning(f"No posts found on {current_url} (empty streak: {empty_streak})")
                if empty_streak >= EMPTY_PAGE_ABORT:
                    logger.warning("Consecutive empty pages — aborting post pagination")
                    break
                continue
            empty_streak = 0

            for thing in things:
                yield format_post_from_thing(thing)

            next_url = self._next_url(soup)
            if not next_url:
                break

            page += 1
            if page >= self.max_pages:
                logger.info("Reached pagination limit")
                break

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

            async for post in self._paginate_search(url, params):
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
            empty_streak = 0
            current_url = url
            current_params: dict[str, Any] | None = params

            while True:
                soup = await self._get_soup(current_url, current_params)
                if soup is None:
                    break

                things = soup.select("div.thing[data-fullname]")
                if not things:
                    empty_streak += 1
                    if empty_streak >= EMPTY_PAGE_ABORT:
                        logger.warning("Consecutive empty pages — aborting user pagination")
                        break
                    continue
                empty_streak = 0

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
                if page >= self.max_pages:
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

            post_thing = soup.select_one('div.thing[data-fullname^="t3_"]')
            if post_thing is not None:
                yield format_post_from_thing(post_thing)

            for comment in self._parse_comments(soup):
                yield comment

    # --- Helpers ---

    async def _fetch_comments_for_post(
        self, post_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        if not post_id:
            return
        url = f"{BASE_URL}/comments/{post_id}/"
        soup = await self._get_soup(url, {"limit": 500})
        if soup is None:
            return
        for comment in self._parse_comments(soup):
            yield comment

    def _parse_comments(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Parse all comment things from a post page into a flat list."""
        results: list[dict[str, Any]] = []
        max_comments = self.config.max_comments_per_post

        for thing in soup.select('div.thing[data-fullname^="t1_"]'):
            depth = len(thing.find_parents("div", class_="child"))
            results.append(format_comment_from_thing(thing, depth=depth))
            if max_comments > 0 and len(results) >= max_comments:
                break

        return results
