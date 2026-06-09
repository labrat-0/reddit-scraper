"""Reddit Scraper -- Apify Actor entry point."""

from __future__ import annotations

import logging
import os

from apify import Actor

from .models import ScraperInput
from .scraper import MAX_PAGES, MAX_PAGES_FREE, RedditScraper
from .utils import PageFetcher, RateLimiter

logger = logging.getLogger(__name__)

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

        # Free users need at most 1 page (25 posts) — cap pagination to avoid
        # burning proxy budget for users who will never see more than 25 results.
        max_pages = MAX_PAGES_FREE if not is_paying and os.environ.get("APIFY_IS_AT_HOME") == "1" else MAX_PAGES

        Actor.log.info(
            f"Starting Reddit Scraper | mode={config.mode.value} | "
            f"max_results={max_results}"
        )

        # 3. Set up proxy — residential IPs avoid Reddit datacenter blocks
        proxy_input = raw_input.get("proxyConfiguration") or {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"],
        }
        proxy_config = await Actor.create_proxy_configuration(
            actor_proxy_input=proxy_input
        )

        # 4. Resume state (survives migrations)
        state = await Actor.use_state(default_value={"scraped": 0, "failed": 0})

        await Actor.set_status_message("Starting browser...")

        rate_limiter = RateLimiter()

        count = state["scraped"]
        batch: list[dict] = []
        batch_size = 25

        async with PageFetcher(rate_limiter, proxy_config) as fetcher:
            scraper = RedditScraper(fetcher, config, max_pages=max_pages)

            try:
                async for item in scraper.scrape():
                    if count >= max_results:
                        break

                    batch.append(item)
                    count += 1
                    state["scraped"] = count

                    if len(batch) >= batch_size:
                        await Actor.push_data(batch)
                        batch = []
                        await Actor.set_status_message(
                            f"Scraped {count}/{max_results} items"
                        )

                if batch:
                    await Actor.push_data(batch)

            except Exception as e:
                state["failed"] += 1
                Actor.log.error(f"Scraping error: {e}")
                if batch:
                    await Actor.push_data(batch)

        # 5. Fail loud on 0 results — almost always means Reddit changed something.
        if count == 0:
            await Actor.fail(
                status_message=(
                    "Scraped 0 results. Either the targets are empty/invalid, "
                    "or Reddit changed its HTML and the scraper needs updating. "
                    "Check the logs for warnings."
                )
            )
            return

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
