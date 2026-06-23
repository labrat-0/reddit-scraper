"""Utility functions: rate limiting and Playwright-based HTML fetching."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any
from urllib.parse import urlencode, urlparse

from playwright.async_api import Browser, async_playwright

logger = logging.getLogger(__name__)

# www.reddit.com/<path>/.json returns standard Reddit Listing JSON. old.reddit
# is now hard-blocked ("whoa there"); www serves JSON once the network-security
# JS challenge is solved by a one-time warm-up visit to the site root.
BASE_URL = "https://www.reddit.com"

# Playwright page loads are heavier than raw HTTP — give more breathing room.
REQUEST_INTERVAL = 1.5
REQUEST_JITTER = 0.5

# 3 (not 2): a failed warm-up + IP rotation can consume an attempt before the
# first real fetch, so give the fetch itself headroom.
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5.0

# Navigation timeout. With heavy resources blocked (see BLOCKED_RESOURCE_TYPES),
# old.reddit pages load fast — a tight ceiling caps the timeout-burn failure mode.
NAV_TIMEOUT_MS = 25_000

# Resource types aborted before they hit the proxy. images/fonts/media are the
# bulk of bandwidth and old.reddit HTML parsing never needs them — blocking cuts
# residential proxy cost ~85%. CSS is deliberately NOT blocked: a real browser
# always fetches stylesheets, and their absence makes the request graph look
# non-human, which trips Reddit's 2026 bot detection (403). Scripts are kept so
# any Cloudflare JS challenge can still solve.
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}

# Each profile pairs a UA with a matching Sec-Ch-Ua-Platform + Sec-Ch-Ua so the
# client hints stay self-consistent. A UA/platform mismatch is itself a bot tell.
# (user_agent, sec_ch_ua_platform, sec_ch_ua)
BROWSER_PROFILES = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        '"Windows"',
        '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        '"macOS"',
        '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        '"Linux"',
        '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    ),
]

# Injected before any page script runs to mask the obvious headless-Chromium
# tells Reddit fingerprints: navigator.webdriver, empty plugins, missing
# window.chrome, and the languages array.
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5].map(i => ({name: 'Plugin ' + i})),
});
window.chrome = window.chrome || {runtime: {}};
const _query = window.navigator.permissions && window.navigator.permissions.query;
if (_query) {
    window.navigator.permissions.query = (p) =>
        p && p.name === 'notifications'
            ? Promise.resolve({state: Notification.permission})
            : _query(p);
}
"""


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
        # Whether the network-security challenge has been solved for the current
        # context/IP. Reset on every context (re)init so a fresh IP re-warms.
        self._warmed: bool = False
        # Cost-tracking: bytes of HTML returned + wall-clock start, read by the
        # main loop's circuit breaker to abort runaway runs.
        self.total_bytes: int = 0
        self.start_time: float = 0.0
        # Instrumentation: confirm resource blocking is working in production logs.
        self.blocked_requests: int = 0
        self.allowed_requests: int = 0

    async def __aenter__(self) -> "PageFetcher":
        self.start_time = asyncio.get_event_loop().time()
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
        self._warmed = False
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

        user_agent, ua_platform, sec_ch_ua = random.choice(BROWSER_PROFILES)
        self._context = await self._browser.new_context(
            user_agent=user_agent,
            proxy=self._proxy_settings,
            # Full Chrome header set. old.reddit/Reddit flags requests whose
            # headers don't match a real browser, so send the same Accept,
            # client-hint, and Sec-Fetch headers Chrome sends on a top-level nav.
            extra_http_headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8,"
                    "application/signed-exchange;v=b3;q=0.7"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Ch-Ua": sec_ch_ua,
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": ua_platform,
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
        )
        # Mask headless tells before any page script runs.
        await self._context.add_init_script(STEALTH_INIT_SCRIPT)
        await self._context.add_cookies([
            {
                "name": "over18",
                "value": "1",
                "domain": ".reddit.com",
                "path": "/",
            },
            {
                "name": "_options",
                "value": '{%22pref_quarantine_optin%22:true}',
                "domain": ".reddit.com",
                "path": "/",
            },
        ])

        # Abort heavy resources at the context level so the route survives the
        # per-page new_page()/close() cycle in fetch(). Biggest proxy-cost lever.
        await self._context.route("**/*", self._route_handler)

    async def _route_handler(self, route: Any) -> None:
        if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
            self.blocked_requests += 1
            await route.abort()
        else:
            self.allowed_requests += 1
            await route.continue_()

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

    async def warmup(self) -> int:
        """Visit the reddit.com root cold so the network-security JS challenge
        can run and drop its clearance cookie into the shared context. Returns
        the number of cookies the context holds afterward (a jump means the
        challenge set something). Best-effort — never raises."""
        page = None
        try:
            page = await self._context.new_page()
            await page.goto(
                "https://www.reddit.com/",
                wait_until="domcontentloaded",
                timeout=NAV_TIMEOUT_MS,
            )
            # Give the challenge JS time to execute, post its token, reload, and
            # set the clearance cookie. These solvers typically take a few sec.
            await page.wait_for_timeout(6000)
            try:
                await page.reload(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                await page.wait_for_timeout(3000)
            except Exception:
                pass
            cookies = await self._context.cookies()
            return len(cookies)
        except Exception as e:  # noqa: BLE001 - diagnostic
            logger.warning(f"warmup error: {e}")
            return -1
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    def _classify(self, body: str) -> dict[str, Any]:
        lower = body.lower()
        marks = [n for n in (
            'network security', 'shreddit', '__r', 'whoa there',
            'cloudflare', 'challenge', '"kind"', '<!doctype html',
        ) if n in lower]
        return {
            "len": len(body),
            "listing": '"kind": "Listing"' in body or '"kind":"Listing"' in body,
            "blocked": "<title>Blocked</title>" in body,
            "head": "|".join(marks) or " ".join(body.split())[:160],
        }

    async def probe(self, urls: list[str]) -> list[dict[str, Any]]:
        """Diagnostic: warm up (solve challenge), then GET each URL and report
        what came back. If a target still shows the network-security wall, wait
        and reload once — these challenges often clear on the second pass."""
        warm_cookies = await self.warmup()
        logger.info(f"warmup complete — context holds {warm_cookies} cookies")

        out: list[dict[str, Any]] = []
        for url in urls:
            await self.rate_limiter.wait()
            page = None
            entry: dict[str, Any] = {"url": url, "status": 0, "listing": False,
                                     "blocked": False, "len": 0, "head": ""}
            try:
                page = await self._context.new_page()
                resp = await page.goto(
                    url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS
                )
                entry["status"] = resp.status if resp else 0
                body = await page.content()
                cls = self._classify(body)
                # Still challenged? wait for the solver, reload once, re-read.
                if "network security" in cls["head"] or "challenge" in cls["head"]:
                    await page.wait_for_timeout(6000)
                    try:
                        resp = await page.reload(
                            wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS
                        )
                        entry["status"] = resp.status if resp else entry["status"]
                        body = await page.content()
                        cls = self._classify(body)
                    except Exception:
                        pass
                entry.update(cls)
            except Exception as e:  # noqa: BLE001 - diagnostic, log and continue
                entry["status"] = -1
                logger.warning(f"probe error on {url}: {e}")
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
            out.append(entry)
        return out

    async def fetch_json(
        self, url: str, params: dict[str, Any] | None = None
    ) -> Any | None:
        """Fetch a Reddit `.json` endpoint and return the parsed object, or None.

        Solves the network-security challenge once per context (warm-up), then
        navigates to the JSON URL and parses the raw response body. On a 403/503
        (challenge re-armed or IP flagged) it rotates to a fresh proxy IP and
        re-warms before retrying.
        """
        if params:
            url = f"{url}?{urlencode(params)}"

        for attempt in range(MAX_RETRIES):
            await self.rate_limiter.wait()
            if not self._warmed:
                # Only mark warmed if the challenge actually set cookies; a failed
                # warm-up (e.g. dead proxy tunnel) should not burn a fetch attempt
                # on a context that was never cleared.
                cookies = await self.warmup()
                if cookies > 0:
                    self._warmed = True
                else:
                    logger.warning("warmup set no cookies — rotating IP")
                    try:
                        await self._init_context()
                    except Exception as reinit_err:
                        logger.error(f"Failed to reinit context: {reinit_err}")
                    continue

            page = None
            try:
                page = await self._context.new_page()
                response = await page.goto(
                    url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS
                )
                status = response.status if response else 0

                if status == 200:
                    body = await response.text()
                    self.total_bytes += len(body)
                    try:
                        return json.loads(body)
                    except json.JSONDecodeError:
                        logger.warning(f"JSON parse failed on {url}")
                        return None

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
                # 403/503 = challenge re-armed or IP flagged — rotate IP + re-warm.
                if status in (403, 503):
                    try:
                        await self._init_context()
                    except Exception as reinit_err:
                        logger.error(f"Failed to reinit context: {reinit_err}")
                await asyncio.sleep(RETRY_BASE_DELAY)
                continue

            except Exception as e:
                delay = RETRY_BASE_DELAY * (attempt + 1)
                logger.warning(
                    f"Playwright error on {url}: {e}. "
                    f"Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
                )
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
                    timeout=NAV_TIMEOUT_MS,
                )
                status = response.status if response else 0

                if status == 200:
                    html = await page.content()
                    self.total_bytes += len(html)
                    return html

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
                # 403/503 = blocked by bot detection, usually IP-reputation tied.
                # Retrying the same proxy IP just earns another block, so rotate
                # to a fresh IP + UA/headers before the next attempt.
                if status in (403, 503):
                    try:
                        await self._init_context()
                    except Exception as reinit_err:
                        logger.error(f"Failed to reinit context: {reinit_err}")
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
