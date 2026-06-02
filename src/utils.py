"""Utility functions for rate limiting, retries, and HTTP helpers.

Reddit killed its public `.json` API endpoints (403 since ~May 29 2026).
We now scrape the server-rendered HTML from old.reddit.com, which exposes
all post/comment data as `data-*` attributes on `<div class="thing">`.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

# old.reddit.com serves parseable server-rendered HTML. www/new reddit is a JS
# shell with no data in the initial HTML, and the .json API now returns 403.
BASE_URL = "https://old.reddit.com"

# old.reddit HTML tolerates a few requests/sec. Keep a small margin.
REQUEST_INTERVAL = 2.0

# Retry settings
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5.0  # seconds

# Browser UAs (paired with curl_cffi Chrome TLS impersonation)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


class RateLimiter:
    """Simple rate limiter that ensures a minimum interval between requests."""

    def __init__(self, interval: float = REQUEST_INTERVAL) -> None:
        self._interval = interval
        self._last_request: float = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        """Wait until it's safe to make another request."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request
            if elapsed < self._interval:
                wait_time = self._interval - elapsed
                logger.debug(f"Rate limiter: waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
            self._last_request = asyncio.get_event_loop().time()


def _get_headers() -> dict[str, str]:
    """Return browser-like headers for an old.reddit HTML request."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


# old.reddit gates NSFW/quarantined content behind these cookies.
_COOKIES = {"over18": "1", "_options": '{%22pref_quarantine_optin%22:true}'}


async def fetch_html(
    url: str,
    rate_limiter: RateLimiter,
    params: dict[str, Any] | None = None,
    proxy_config: Any | None = None,
) -> str | None:
    """Fetch a page of HTML with rate limiting and retry logic.

    Uses curl_cffi to impersonate Chrome's TLS fingerprint. Returns the
    HTML text, or None if all retries fail.
    """
    for attempt in range(MAX_RETRIES):
        await rate_limiter.wait()

        proxy_url: str | None = None
        if proxy_config:
            proxy_url = await proxy_config.new_url()
        proxies = {"https": proxy_url, "http": proxy_url} if proxy_url else None

        try:
            async with AsyncSession() as session:
                response = await session.get(
                    url,
                    params=params,
                    headers=_get_headers(),
                    cookies=_COOKIES,
                    timeout=30,
                    impersonate="chrome124",
                    proxies=proxies,
                    allow_redirects=True,
                )

            status = response.status_code

            if status == 200:
                return response.text

            if status == 429:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    f"Rate limited (429) on {url}. "
                    f"Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
                )
                await asyncio.sleep(delay)
                continue

            if status == 403:
                logger.warning(
                    f"Forbidden (403) on {url}. Attempt {attempt + 1}/{MAX_RETRIES}"
                )
                await asyncio.sleep(5.0)
                continue

            if status == 404:
                logger.warning(f"Not found (404): {url}")
                return None

            if status >= 500:
                delay = 10.0 * (attempt + 1)
                logger.warning(
                    f"Server error ({status}) on {url}. "
                    f"Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
                )
                await asyncio.sleep(delay)
                continue

            logger.warning(f"Unexpected status {status} on {url}")
            return None

        except Exception as e:
            delay = 10.0 * (attempt + 1)
            logger.warning(
                f"Request error on {url}: {e}. "
                f"Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
            )
            await asyncio.sleep(delay)
            continue

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
