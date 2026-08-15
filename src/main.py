"""Reddit Scraper -- Apify Actor entry point."""

from __future__ import annotations

import asyncio
import logging
import os

from apify import Actor

from .models import ScraperInput
from .scraper import MAX_PAGES, MAX_PAGES_FREE, RedditScraper
from .utils import PageFetcher, RateLimiter

logger = logging.getLogger(__name__)

FREE_TIER_LIMIT = 25

# Runaway-cost breaker: abort a run once its estimated compute + proxy spend
# exceeds the budget its results have earned (with a small floor). This stops
# wedged or timing-out runs that burn resources for little output, without
# truncating large efficient runs, whose budget scales with result count.
BUDGET_PER_RESULT_USD = 0.0015
MIN_COST_ALLOWANCE_USD = 0.05  # headroom before the breaker can ever trip
CU_RATE_USD_PER_HR = 0.20  # compute unit hour (1GB for 1hr)
RESIDENTIAL_USD_PER_GB = 8.0


def _estimate_run_cost_usd(elapsed_s: float, total_bytes: int) -> float:
    """Rough run cost = compute (mem·time) + residential proxy bandwidth."""
    mem_gb = int(os.environ.get("ACTOR_MEMORY_MBYTES", "2048")) / 1024
    compute_usd = (elapsed_s / 3600) * mem_gb * CU_RATE_USD_PER_HR
    proxy_usd = (total_bytes / 1e9) * RESIDENTIAL_USD_PER_GB
    return compute_usd + proxy_usd


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

        # Free users need at most 1 page (25 posts), cap pagination to avoid
        # burning proxy budget for users who will never see more than 25 results.
        max_pages = MAX_PAGES_FREE if not is_paying and os.environ.get("APIFY_IS_AT_HOME") == "1" else MAX_PAGES

        Actor.log.info(
            f"Starting Reddit Scraper | mode={config.mode.value} | "
            f"max_results={max_results}"
        )

        # 3. Set up proxy: residential IPs avoid Reddit datacenter blocks
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
        cost_exceeded = False

        async with PageFetcher(rate_limiter, proxy_config) as fetcher:
            scraper = RedditScraper(fetcher, config, max_pages=max_pages)

            try:
                async for item in scraper.scrape():
                    if count >= max_results:
                        break

                    # NSFW filter: skip adult content unless explicitly opted in
                    if not config.include_nsfw and item.get("isNSFW"):
                        continue

                    batch.append(item)
                    count += 1
                    state["scraped"] = count

                    if len(batch) >= batch_size:
                        await Actor.push_data(batch)
                        batch = []
                        await Actor.set_status_message(
                            f"Scraped {count}/{max_results} items"
                        )

                    # Cost breaker, checked per item (not per batch) so wedged
                    # low-yield runs that never fill a batch are still caught.
                    elapsed = asyncio.get_event_loop().time() - fetcher.start_time
                    est_cost = _estimate_run_cost_usd(elapsed, fetcher.total_bytes)
                    budget = max(MIN_COST_ALLOWANCE_USD, count * BUDGET_PER_RESULT_USD)
                    if est_cost > budget:
                        cost_exceeded = True
                        Actor.log.warning(
                            f"Cost breaker tripped: est resource cost ~${est_cost:.3f} > "
                            f"budget ${budget:.3f} after {count} items. Stopping."
                        )
                        await Actor.set_status_message(
                            f"Stopped at {count} items, run resource budget exceeded."
                        )
                        break

                if batch:
                    await Actor.push_data(batch)

            except Exception as e:
                state["failed"] += 1
                Actor.log.error(f"Scraping error: {e}")
                if batch:
                    await Actor.push_data(batch)

        # 5. Report 0 results without hard-failing, almost always means Reddit changed something.
        if count == 0:
            await Actor.set_status_message(
                status_message=(
                    "Scraped 0 results. Either the targets are empty/invalid, "
                    "or Reddit changed its HTML and the scraper needs updating. "
                    "Check the logs for warnings."
                )
            )
            return

        # Instrumentation: confirms resource blocking is working on real runs.
        elapsed = asyncio.get_event_loop().time() - fetcher.start_time
        total_reqs = fetcher.blocked_requests + fetcher.allowed_requests
        blocked_pct = (fetcher.blocked_requests / total_reqs * 100) if total_reqs else 0
        Actor.log.info(
            f"Resource report | requests: {fetcher.blocked_requests} blocked "
            f"({blocked_pct:.0f}%) / {fetcher.allowed_requests} allowed | "
            f"data: {fetcher.total_bytes / 1024:.0f} KB | "
            f"elapsed: {elapsed:.1f}s"
        )

        msg = f"Done. Scraped {count} items."
        if cost_exceeded:
            msg += " Stopped early at run cost cap."
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
