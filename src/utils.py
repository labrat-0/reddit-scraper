"""Utility functions for rate limiting, retries, and HTTP helpers."""

from __future__ import annotations

import asyncio
import base64
import logging
import random
from typing import Any

import httpx
from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

# Authenticated requests go to oauth.reddit.com (bypasses Fastly CDN blocking).
# Unauthenticated fallback uses www.reddit.com with Chrome TLS impersonation.
OAUTH_BASE_URL = "https://oauth.reddit.com"
BASE_URL = "https://www.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"

# Reddit OAuth rate limit: 100 req/min = 1 every 0.6s.
# Unauthenticated: ~10 req/min = 1 every 6s.
REQUEST_INTERVAL = 0.7  # used when authenticated; scraper falls back to 7s without token

# Retry settings
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5.0  # seconds

# Reddit requires this exact User-Agent format for OAuth API access.
OAUTH_USER_AGENT = "python:apify-reddit-scraper:1.2.0 (by /u/labrat011)"

# Browser UAs for unauthenticated requests (paired with Chrome TLS impersonation)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


async def get_oauth_token(client_id: str, client_secret: str) -> str | None:
    """Fetch a Reddit app-only OAuth2 access token (valid 1 hour)."""
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                TOKEN_URL,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "User-Agent": OAUTH_USER_AGENT,
                },
                data={"grant_type": "client_credentials"},
                timeout=30.0,
            )
            if response.status_code == 200:
                token = response.json().get("access_token")
                logger.info("Reddit OAuth token acquired")
                return token
            logger.error(f"OAuth token request failed: {response.status_code} {response.text[:200]}")
        except Exception as e:
            logger.error(f"OAuth token request error: {e}")
    return None


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


def _get_headers(oauth_token: str | None = None) -> dict[str, str]:
    """Return request headers. OAuth token takes precedence over browser UA."""
    if oauth_token:
        return {
            "Authorization": f"Bearer {oauth_token}",
            "User-Agent": OAUTH_USER_AGENT,
            "Accept": "application/json",
        }
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
    }


async def fetch_json(
    client: Any,
    url: str,
    rate_limiter: RateLimiter,
    params: dict[str, Any] | None = None,
    proxy_config: Any | None = None,
    oauth_token: str | None = None,
) -> dict[str, Any] | list[Any] | None:
    """Fetch JSON from a URL with rate limiting and retry logic.

    Uses curl_cffi to impersonate Chrome's TLS fingerprint, bypassing
    Reddit's JA3/TLS-based bot detection. Falls back gracefully.

    Returns the parsed JSON data, or None if all retries fail.
    """
    for attempt in range(MAX_RETRIES):
        await rate_limiter.wait()

        # OAuth goes direct — no proxy cost or fingerprint concern.
        # Unauthenticated mode rotates residential IPs as extra layer.
        proxy_url: str | None = None
        if proxy_config and not oauth_token:
            proxy_url = await proxy_config.new_url()

        proxies = {"https": proxy_url, "http": proxy_url} if proxy_url else None

        try:
            async with AsyncSession() as session:
                response = await session.get(
                    url,
                    params=params,
                    headers=_get_headers(oauth_token),
                    timeout=30,
                    impersonate="chrome124",
                    proxies=proxies,
                    allow_redirects=True,
                )

            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception:
                    logger.warning(f"Non-JSON 200 response from {url}")
                    return None
                # Reddit sometimes sends 200 with {"error": 429} body
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
                    f"Forbidden (403) on {url}. Attempt {attempt + 1}/{MAX_RETRIES}"
                )
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

            logger.warning(f"Unexpected status {response.status_code} on {url}")
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
