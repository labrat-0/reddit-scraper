"""Utility functions for rate limiting, retries, and Reddit OAuth."""

from __future__ import annotations

import asyncio
import base64
import logging
import random
from typing import Any

from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

OAUTH_BASE_URL = "https://oauth.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"

# ~85 req/min: safely under the 100 req/min OAuth limit
REQUEST_INTERVAL = 0.7
REQUEST_JITTER = 0.3

MAX_RETRIES = 3
RETRY_BASE_DELAY = 5.0

# Reddit requires a descriptive bot User-Agent for OAuth API access.
OAUTH_USER_AGENT = "python:apify-reddit-scraper:v1.3.0 (by /u/labrat-0)"


class RateLimiter:
    """Simple rate limiter that ensures a minimum interval between requests."""

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


async def get_oauth_token(client_id: str, client_secret: str) -> str | None:
    """Get an app-only bearer token via client_credentials grant."""
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        async with AsyncSession() as session:
            response = await session.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {credentials}",
                    "User-Agent": OAUTH_USER_AGENT,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                impersonate="chrome136",
                timeout=15,
            )
        if response.status_code == 200:
            token = response.json().get("access_token")
            logger.info("OAuth token obtained successfully")
            return token
        logger.error(f"OAuth token request failed: HTTP {response.status_code} — {response.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"OAuth token request error: {e}")
        return None


async def fetch_json(
    url: str,
    rate_limiter: RateLimiter,
    params: dict[str, Any] | None = None,
    oauth_token: str | None = None,
) -> Any | None:
    """Fetch JSON from the Reddit OAuth API with rate limiting and retry logic."""
    headers: dict[str, str] = {"User-Agent": OAUTH_USER_AGENT}
    if oauth_token:
        headers["Authorization"] = f"Bearer {oauth_token}"

    for attempt in range(MAX_RETRIES):
        await rate_limiter.wait()
        try:
            async with AsyncSession() as session:
                response = await session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=30,
                    impersonate="chrome136",
                )

            status = response.status_code

            if status == 200:
                return response.json()

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
