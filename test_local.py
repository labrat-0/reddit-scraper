"""Local test script -- tests all 4 scraping modes against live Reddit.

Run: .venv/bin/python test_local.py

This bypasses the Apify Actor wrapper and tests the core scraping logic directly.
"""

import asyncio
import json
import sys
import time

import httpx

# Add src to path so we can import directly
sys.path.insert(0, ".")

from src.models import ScraperInput, ScrapingMode
from src.scraper import RedditScraper
from src.utils import RateLimiter


async def test_mode(name: str, config: ScraperInput, max_items: int = 5) -> bool:
    """Test a single scraping mode. Returns True on success."""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")

    rate_limiter = RateLimiter(interval=7.0)

    async with httpx.AsyncClient() as client:
        scraper = RedditScraper(client, rate_limiter, config)

        items = []
        try:
            async for item in scraper.scrape():
                items.append(item)
                if len(items) >= max_items:
                    break
        except Exception as e:
            print(f"  FAIL: {e}")
            return False

    if not items:
        print(f"  FAIL: No items returned")
        return False

    print(f"  OK: Got {len(items)} items")
    # Print first item as sample
    print(f"  Sample item:")
    print(f"  {json.dumps(items[0], indent=2, default=str)[:500]}")

    # Validate structure
    first = items[0]
    if first.get("type") in ("post", "comment"):
        print(f"  Type: {first['type']}")
        if first["type"] == "post":
            required = ["id", "subreddit", "title", "author", "score", "url", "created"]
            missing = [k for k in required if k not in first]
            if missing:
                print(f"  FAIL: Missing fields: {missing}")
                return False
            print(f"  All required post fields present")
        elif first["type"] == "comment":
            required = ["id", "author", "body", "score", "url", "created"]
            missing = [k for k in required if k not in first]
            if missing:
                print(f"  FAIL: Missing fields: {missing}")
                return False
            print(f"  All required comment fields present")
    else:
        print(f"  WARN: Unexpected item type: {first.get('type')}")

    return True


async def main():
    results = {}
    start = time.time()

    # Test 1: Subreddit Posts (hot)
    config = ScraperInput(
        mode=ScrapingMode.SUBREDDIT_POSTS,
        subreddits=["python"],
        sort="hot",
        max_results=5,
    )
    results["subreddit_posts"] = await test_mode("Subreddit Posts (r/python hot)", config, max_items=5)

    # Test 2: Search
    config = ScraperInput(
        mode=ScrapingMode.SEARCH,
        search_query="fastapi tutorial",
        search_sort="relevance",
        max_results=5,
    )
    results["search"] = await test_mode("Search Reddit ('fastapi tutorial')", config, max_items=5)

    # Test 3: User Profile
    config = ScraperInput(
        mode=ScrapingMode.USER_PROFILE,
        usernames=["spez"],
        user_content_type="overview",
        max_results=5,
    )
    results["user_profile"] = await test_mode("User Profile (u/spez)", config, max_items=5)

    # Test 4: Post Comments -- use a URL from the subreddit test (guaranteed fresh)
    # First grab a real post URL from r/AskReddit (high traffic, always has comments)
    print("\n  (Fetching a live post URL for comment test...)")
    live_url = None
    async with httpx.AsyncClient() as client:
        rate_limiter = RateLimiter(interval=7.0)
        fetch_config = ScraperInput(
            mode=ScrapingMode.SUBREDDIT_POSTS,
            subreddits=["AskReddit"],
            sort="hot",
            max_results=1,
        )
        scraper = RedditScraper(client, rate_limiter, fetch_config)
        async for item in scraper.scrape():
            live_url = item.get("url", "")
            print(f"  Using: {live_url}")
            break

    if live_url:
        config = ScraperInput(
            mode=ScrapingMode.POST_COMMENTS,
            post_urls=[live_url],
            max_comments_per_post=5,
            max_results=10,
        )
        results["post_comments"] = await test_mode("Post Comments", config, max_items=10)
    else:
        print("  SKIP: Could not fetch a live post URL for comment test")
        results["post_comments"] = False

    # Summary
    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"RESULTS ({elapsed:.1f}s)")
    print(f"{'='*60}")
    all_passed = True
    for mode, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {mode}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        print(f"\nAll tests passed.")
    else:
        print(f"\nSome tests FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
