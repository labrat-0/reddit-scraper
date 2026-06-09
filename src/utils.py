"""Utility functions: rate limiting and Playwright-based HTML fetching."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any
from urllib.parse import urlencode, urlparse

from playwright.async_api import Browser, async_playwright

logger = logging.getLogger(__name__)

# old.reddit.com serves parseable server-rendered HTML with data-* attributes.
BASE_URL = "https://old.reddit.com"

# Playwright page loads are heavier than raw HTTP — give more breathing room.
REQUEST_INTERVAL = 1.5
REQUEST_JITTER = 0.5

MAX_RETRIES = 3
RETRY_BASE_DELAY = 5.0

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
]


class RateLimiter:
    """Minimum-interval rate limiter with jitter."""

    def __init__(self, interval: float = REQUEST_INTERVAL) -> None:
        self._interval = interval
        self._last_request: float = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request
            target = self._interval + random.uniform(0, REQUEST_JITTER)
            if elapsed < target:
                await asyncio.sleep(target - elapsed)
            self._last_request = asyncio.get_event_loop().time()


class PageFetcher:
    """Playwright-based HTML fetcher backed by a shared Chromium instance.

    A real browser bypasses Cloudflare bot challenges that block plain HTTP
    clients. Use as an async context manager so the browser is properly torn
    down after scraping completes.

    One persistent browser context is reused across all fetches to avoid
    re-establishing a proxy tunnel on every request (major cost saving).
    The context is recreated only if a fatal error forces it.
    """

    def __init__(
        self,
        rate_limiter: RateLimiter,
        proxy_config: Any = None,
    ) -> None:
        self.rate_limiter = rate_limiter
        self.proxy_config = proxy_config
        self._playwright = None
        self._browser: Browser | None = None
        self._context: Any = None
        self._proxy_settings: dict[str, Any] | None = None

    async def __aenter__(self) -> "PageFetcher":
        self._playwright = await async_playwright().start()
        # Apify runs the container as root — Chromium needs --no-sandbox to launch.
        # --disable-dev-shm-usage avoids crashes from the small /dev/shm in containers.
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        await self._init_context()
        return self

    async def _init_context(self) -> None:
        """Create (or recreate) the shared browser context."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        if self.proxy_config:
            proxy_url = await self.proxy_config.new_url()
            # Apify's proxy URL embeds credentials (http://user:pass@host:port).
            # Playwright ignores creds in `server` — they must be split out, or the
            # CONNECT hangs and page.goto times out.
            p = urlparse(proxy_url)
            self._proxy_settings = {
                "server": f"{p.scheme}://{p.hostname}:{p.port}",
                "username": p.username,
                "password": p.password,
            }

        ua = random.choice(USER_AGENTS)
        self._context = await self._browser.new_context(
            user_agent=ua,
            proxy=self._proxy_settings,
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        await self._context.add_cookies([
            {
                "name": "over18",
                "value": "1",
                "domain": "old.reddit.com",
                "path": "/",
            },
            {
                "name": "_options",
                "value": '{%22pref_quarantine_optin%22:true}',
                "domain": "old.reddit.com",
                "path": "/",
            },
        ])

    async def __aexit__(self, *_: Any) -> None:
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def fetch(
        self, url: str, params: dict[str, Any] | None = None
    ) -> str | None:
        """Navigate to a URL and return the page HTML, or None on failure."""
        if params:
            url = f"{url}?{urlencode(params)}"

        for attempt in range(MAX_RETRIES):
            await self.rate_limiter.wait()
            page = None
            try:
                page = await self._context.new_page()
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                status = response.status if response else 0

                if status == 200:
                    return await page.content()

                if status == 404:
                    logger.warning(f"Not found (404): {url}")
                    return None

                if status == 429:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Rate limited (429) on {url}. "
                        f"Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.warning(
                    f"HTTP {status} on {url}. Attempt {attempt + 1}/{MAX_RETRIES}"
                )
                await asyncio.sleep(RETRY_BASE_DELAY)
                continue

            except Exception as e:
                delay = RETRY_BASE_DELAY * (attempt + 1)
                logger.warning(
                    f"Playwright error on {url}: {e}. "
                    f"Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
                )
                # Recreate context on error — it may be in a bad state.
                try:
                    await self._init_context()
                except Exception as reinit_err:
                    logger.error(f"Failed to reinit context: {reinit_err}")
                await asyncio.sleep(delay)
                continue

            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass

        logger.error(f"All {MAX_RETRIES} retries exhausted for {url}")
        return None


def parse_post_url(url: str) -> tuple[str, str] | None:
    """Parse a Reddit post URL and return (subreddit, post_id).

    Handles formats:
        https://www.reddit.com/r/python/comments/abc123/title_slug/
        https://old.reddit.com/r/python/comments/abc123/
        https://reddit.com/r/python/comments/abc123/title_slug
        /r/python/comments/abc123/

    Returns None if the URL can't be parsed.
    """
    path = url.strip()
    for prefix in [
        "https://www.reddit.com",
        "https://old.reddit.com",
        "https://reddit.com",
        "http://www.reddit.com",
        "http://old.reddit.com",
        "http://reddit.com",
    ]:
        if path.startswith(prefix):
            path = path[len(prefix):]
            break

    parts = [p for p in path.split("/") if p]

    if len(parts) >= 4 and parts[0] == "r" and parts[2] == "comments":
        return (parts[1], parts[3])

    logger.warning(f"Could not parse post URL: {url}")
    return None
