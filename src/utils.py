"""Utility functions for rate limiting, retries, and HTTP helpers."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Reddit rate limit: ~10 requests/minute unauthenticated = 1 every 6 seconds.
# We use 7 seconds to add a safety margin.
REQUEST_INTERVAL = 7.0

# Retry settings
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5.0  # seconds (was 30 — caused timeout cascade on 429)

# User agents to rotate through
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
]

BASE_URL = "https://www.reddit.com"


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
    """Return headers with a random User-Agent."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    rate_limiter: RateLimiter,
    params: dict[str, Any] | None = None,
    proxy_config: Any | None = None,
) -> dict[str, Any] | list[Any] | None:
    """Fetch JSON from a URL with rate limiting and retry logic.

    Returns the parsed JSON data, or None if all retries fail.
    """
    for attempt in range(MAX_RETRIES):
        await rate_limiter.wait()

        # Rotate proxy IP each attempt — get a fresh URL per try
        proxy_url = None
        if proxy_config:
            proxy_url = await proxy_config.new_url()

        try:
            # Create a per-attempt client so proxy URL rotates each retry
            async with httpx.AsyncClient(
                proxy=proxy_url,
                follow_redirects=True,
            ) as req_client:
                response = await req_client.get(
                    url,
                    params=params,
                    headers=_get_headers(),
                    timeout=30.0,
                )

            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception:
                    logger.warning(f"Non-JSON 200 response from {url}")
                    return None
                # Reddit sometimes sends 200 with {"error": 429} body instead of proper status
                if isinstance(data, dict) and "error" in data:
                    err_code = data.get("error")
                    logger.warning(
                        f"Reddit 200+error body (code={err_code}) on {url}. "
                        f"Attempt {attempt + 1}/{MAX_RETRIES}"
                    )
                    if err_code == 429:
                        delay = RETRY_BASE_DELAY * (2 ** attempt)
                        await asyncio.sleep(delay)
                        continue
                    return None
                return data

            if response.status_code == 429:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    f"Rate limited (429) on {url}. "
                    f"Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code == 403:
                logger.warning(
                    f"Forbidden (403) on {url}. "
                    f"IP may be blocked. Attempt {attempt + 1}/{MAX_RETRIES}"
                )
                # Short delay then retry -- proxy rotation should give a new IP
                await asyncio.sleep(5.0)
                continue

            if response.status_code == 404:
                logger.warning(f"Not found (404): {url}")
                return None

            if response.status_code >= 500:
                delay = 10.0 * (attempt + 1)
                logger.warning(
                    f"Server error ({response.status_code}) on {url}. "
                    f"Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
                )
                await asyncio.sleep(delay)
                continue

            logger.warning(
                f"Unexpected status {response.status_code} on {url}"
            )
            return None

        except httpx.TimeoutException:
            delay = 10.0 * (attempt + 1)
            logger.warning(
                f"Timeout on {url}. "
                f"Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
            )
            await asyncio.sleep(delay)
            continue

        except httpx.HTTPError as e:
            delay = 10.0 * (attempt + 1)
            logger.warning(
                f"HTTP error on {url}: {e}. "
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
    # Strip protocol and domain
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

    # Parse path: /r/{subreddit}/comments/{id}/...
    parts = [p for p in path.split("/") if p]

    if len(parts) >= 4 and parts[0] == "r" and parts[2] == "comments":
        return (parts[1], parts[3])

    logger.warning(f"Could not parse post URL: {url}")
    return None
