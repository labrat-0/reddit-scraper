"""Reddit Scraper -- Apify Actor entry point."""

from __future__ import annotations

import logging
import os

import httpx
from apify import Actor

from .models import ScraperInput
from .scraper import RedditScraper
from .utils import RateLimiter, get_oauth_token

logger = logging.getLogger(__name__)

# Free tier limit
FREE_TIER_LIMIT = 25


async def main() -> None:
    """Main actor function."""
    async with Actor:
        # 1. Get and validate input
        raw_input = await Actor.get_input() or {}
        config = ScraperInput.from_actor_input(raw_input)

        validation_error = config.validate_for_mode()
        if validation_error:
            await Actor.fail(status_message=validation_error)
            return

        # 2. Handle free user limits
        is_paying = os.environ.get("APIFY_IS_AT_HOME") == "1" and os.environ.get(
            "APIFY_USER_IS_PAYING"
        ) == "1"

        max_results = config.max_results
        if not is_paying and os.environ.get("APIFY_IS_AT_HOME") == "1":
            max_results = min(max_results, FREE_TIER_LIMIT)
            Actor.log.info(
                f"Free tier: limited to {FREE_TIER_LIMIT} results. "
                "Subscribe to the actor for unlimited results."
            )

        Actor.log.info(
            f"Starting Reddit Scraper | mode={config.mode.value} | "
            f"max_results={max_results}"
        )

        # 3. Reddit OAuth credentials — env vars set by actor owner, optional user override
        client_id = (
            raw_input.get("redditClientId")
            or os.environ.get("REDDIT_CLIENT_ID", "")
        )
        client_secret = (
            raw_input.get("redditClientSecret")
            or os.environ.get("REDDIT_CLIENT_SECRET", "")
        )
        oauth_token: str | None = None
        if client_id and client_secret:
            oauth_token = await get_oauth_token(client_id, client_secret)
            if not oauth_token:
                Actor.log.warning(
                    "Reddit OAuth failed — falling back to unauthenticated requests. "
                    "Check REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET env vars."
                )
        else:
            Actor.log.warning(
                "No Reddit API credentials found. Requests may be blocked by Reddit. "
                "Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET actor env vars."
            )

        # 4. Set up proxy — default to residential; Reddit blocks datacenter IPs
        proxy_input = raw_input.get("proxyConfiguration") or {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"],
        }
        proxy_config = await Actor.create_proxy_configuration(
            actor_proxy_input=proxy_input
        )

        # 5. Resume state (survives migrations)
        state = await Actor.use_state(
            default_value={"scraped": 0, "failed": 0}
        )

        await Actor.set_status_message("Connecting to Reddit...")

        async with httpx.AsyncClient() as client:
            rate_limiter = RateLimiter()
            scraper = RedditScraper(client, rate_limiter, config, proxy_config, oauth_token)

            count = state["scraped"]
            batch: list[dict] = []
            batch_size = 25  # Push in batches for efficiency

            try:
                async for item in scraper.scrape():
                    if count >= max_results:
                        break

                    batch.append(item)
                    count += 1
                    state["scraped"] = count

                    # Push in batches
                    if len(batch) >= batch_size:
                        await Actor.push_data(batch)
                        batch = []

                        await Actor.set_status_message(
                            f"Scraped {count}/{max_results} items"
                        )

                # Push remaining items
                if batch:
                    await Actor.push_data(batch)

            except Exception as e:
                state["failed"] += 1
                Actor.log.error(f"Scraping error: {e}")
                # Push whatever we have so far
                if batch:
                    await Actor.push_data(batch)

        # 6. Final status message
        msg = f"Done. Scraped {count} items."
        if state["failed"] > 0:
            msg += f" {state['failed']} errors encountered."
        if (
            not is_paying
            and os.environ.get("APIFY_IS_AT_HOME") == "1"
            and count >= FREE_TIER_LIMIT
        ):
            msg += (
                f" Free tier limit ({FREE_TIER_LIMIT}) reached."
                " Subscribe for unlimited results."
            )

        Actor.log.info(msg)
        await Actor.set_status_message(msg)
