# Reddit Scraper

Scrape Reddit posts, comments, search results, and user profiles at scale. No API keys, no browser, no login required. MCP-ready for AI agent integration.

## What does it do?

Reddit Scraper extracts structured data from Reddit using lightweight HTTP requests against `old.reddit.com` JSON endpoints. No Reddit API credentials, no browser rendering, no cookies. Returns clean JSON with consistent fields -- ready for analysis, NLP pipelines, or consumption by AI agents via MCP.

**Use cases:**

- **Market research** -- track what people are saying about your product, competitors, or industry
- **Sentiment analysis** -- collect posts and comments for NLP pipelines
- **Lead generation** -- find users discussing problems your product solves
- **Content monitoring** -- watch subreddits for trending topics or keywords
- **Academic research** -- gather Reddit data for studies and analysis
- **AI agent tooling** -- expose as an MCP tool so AI agents can search Reddit, pull posts, and analyze discussions in real time

## Features

- **4 scraping modes:** subreddit posts, Reddit search, user profiles, and post comments
- **Sort and filter:** hot, new, top (with time ranges), rising
- **Comment trees:** full recursive comment extraction with depth tracking
- **Search across Reddit** or within a specific subreddit
- **User profiles:** scrape posts, comments, or both from any public user
- **Automatic pagination** via Reddit's `after` cursor system
- **Rate limiting** built in (7s between requests to stay under Reddit's limits)
- **Retry logic** with exponential backoff on 429s and proxy rotation on 403s
- **State persistence** -- survives Apify actor migrations mid-run

## What data does it extract?

**Posts:**

| Field | Description |
|-------|-------------|
| `type` | Always `"post"` |
| `id` | Reddit post ID |
| `subreddit` | Subreddit name |
| `title` | Post title |
| `author` | Author username |
| `selftext` | Post body text |
| `url` | Reddit permalink |
| `externalUrl` | Link URL (for link posts) |
| `score` | Net upvotes |
| `upvoteRatio` | Upvote percentage (0.0-1.0) |
| `numComments` | Comment count |
| `created` | ISO 8601 UTC timestamp |
| `isNSFW` | NSFW flag |
| `isSpoiler` | Spoiler flag |
| `isPinned` | Pinned/stickied flag |
| `flair` | Post flair text |
| `awards` | Total awards received |
| `domain` | Link domain |
| `isVideo` | Video post flag |
| `thumbnail` | Thumbnail URL |

**Comments:**

| Field | Description |
|-------|-------------|
| `type` | Always `"comment"` |
| `id` | Comment ID |
| `postId` | Parent post ID |
| `subreddit` | Subreddit name |
| `author` | Author username |
| `body` | Comment text |
| `score` | Net upvotes |
| `created` | ISO 8601 UTC timestamp |
| `parentId` | Parent comment/post ID |
| `depth` | Nesting depth (0 = top-level) |
| `isSubmitter` | Whether author is the post's OP |
| `awards` | Total awards received |
| `url` | Reddit permalink |

---

## Input

Choose a scraping mode and provide the relevant parameters.

### Mode 1: Subreddit Posts

Scrape posts from one or more subreddits.

```json
{
    "mode": "subreddit_posts",
    "subreddits": ["python", "machinelearning", "webdev"],
    "sort": "hot",
    "maxResults": 100
}
```

Sort options: `hot`, `new`, `top`, `rising`. When using `top`, you can set `timeFilter` to `hour`, `day`, `week`, `month`, `year`, or `all`.

### Mode 2: Search Reddit

Search across all of Reddit or within a specific subreddit.

```json
{
    "mode": "search",
    "searchQuery": "best python web framework 2025",
    "searchSort": "relevance",
    "maxResults": 50
}
```

To restrict search to a subreddit:

```json
{
    "mode": "search",
    "searchQuery": "fastapi vs django",
    "searchSubreddit": "python",
    "searchSort": "top",
    "maxResults": 50
}
```

Search sort options: `relevance`, `hot`, `top`, `new`, `comments`.

### Mode 3: User Profile

Scrape posts and/or comments from Reddit user profiles.

```json
{
    "mode": "user_profile",
    "usernames": ["spez", "GovSchwarzenegger"],
    "userContentType": "overview",
    "maxResults": 100
}
```

Content type options: `overview` (posts + comments), `submitted` (posts only), `comments` (comments only).

### Mode 4: Post Comments

Extract the full comment tree from specific Reddit posts.

```json
{
    "mode": "post_comments",
    "postUrls": [
        "https://www.reddit.com/r/Python/comments/1i1x5si/what_are_some_mass_produced_products_that_use/"
    ],
    "maxCommentsPerPost": 100
}
```

### Additional Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `includeComments` | `false` | When scraping posts (subreddit or search mode), also fetch comments for each post. Slower and uses more proxy traffic. |
| `maxResults` | `100` | Maximum total results to return (max 10,000). Free users are limited to 25 per run. |
| `proxyConfiguration` | Residential | Proxy settings. **Residential proxies are required** -- Reddit blocks datacenter IPs. |

---

## Output

Results are saved to the default dataset. You can download them in JSON, CSV, Excel, or XML format from the Output tab.

### Example: Post output

```json
{
    "type": "post",
    "id": "1i1x5si",
    "subreddit": "Python",
    "title": "What are some mass-produced products that use Python?",
    "author": "example_user",
    "selftext": "I'm curious about real-world products...",
    "url": "https://www.reddit.com/r/Python/comments/1i1x5si/what_are_some_mass_produced_products_that_use/",
    "externalUrl": "",
    "score": 342,
    "upvoteRatio": 0.95,
    "numComments": 127,
    "created": "2025-01-15T14:23:01+00:00",
    "isNSFW": false,
    "isSpoiler": false,
    "isPinned": false,
    "flair": "Discussion",
    "awards": 2,
    "domain": "self.Python",
    "isVideo": false,
    "thumbnail": "self"
}
```

### Example: Comment output

```json
{
    "type": "comment",
    "id": "m7k2p1a",
    "postId": "1i1x5si",
    "subreddit": "Python",
    "author": "commenter123",
    "body": "Dropbox was famously written in Python...",
    "score": 89,
    "created": "2025-01-15T15:01:44+00:00",
    "parentId": "t3_1i1x5si",
    "depth": 0,
    "isSubmitter": false,
    "awards": 0,
    "url": "https://www.reddit.com/r/Python/comments/1i1x5si/what_are_some_mass_produced_products_that_use/m7k2p1a/"
}
```

---

## Cost

This actor uses **pay-per-event (PPE) pricing**. You pay only for the results you get.

- **Proxy traffic** is paid by the user (residential proxies required, approximately $12.50/GB on Apify)
- Typical cost: roughly **$0.50-$1.00 per 1,000 results** depending on proxy usage
- Free tier: **25 results per run** (no subscription required)

Reddit's rate limits mean each request takes ~7 seconds. A run scraping 100 posts from a single subreddit takes about 1-2 minutes.

---

## Technical details

- Uses `old.reddit.com` JSON endpoints (no API keys, no OAuth, no browser)
- Rate limited to ~10 requests/minute (built-in 7-second interval)
- Automatic retry with exponential backoff on rate limits (429)
- Proxy rotation on IP blocks (403)
- Pagination via Reddit's `after` cursor (up to ~1,000 items per listing)
- Results pushed in batches of 25 for efficiency
- Actor state persisted across migrations

---

## Limitations

- Reddit caps unauthenticated listing pagination at roughly 1,000 items
- "Load more comments" nodes in deep comment trees are not expanded (only initially loaded comments are extracted)
- Datacenter proxies will not work -- Reddit blocks them. Use residential proxies.
- Rate limit of ~10 requests/minute means large scrapes take time

---

## FAQ

### Is it legal to scrape Reddit?

Web scraping of publicly available data is generally legal, as established by the *hiQ Labs v. LinkedIn* ruling. This actor only accesses public Reddit data that anyone can view in a browser. It does not bypass any login walls, CAPTCHAs, or access private content.

### Why do I need residential proxies?

Since June 2025, Reddit blocks nearly all datacenter IP ranges. Residential proxies route requests through real ISP connections, which Reddit does not block.

### How fast is it?

Due to Reddit's rate limits, the scraper makes about 8-10 requests per minute. Scraping 100 posts from a subreddit takes 1-2 minutes. Adding comments to each post increases run time significantly.

### Can I use this with the Apify API?

Yes. Call the actor via the Apify API and retrieve results programmatically in JSON, CSV, or other formats. Works with the Apify Python and JavaScript clients.

### What if a subreddit or user doesn't exist?

The scraper logs a warning and skips invalid subreddits, users, or post URLs. Remaining valid targets are still scraped.

---

## MCP Integration

This actor works as an MCP tool through Apify's hosted MCP server. No custom server needed.

- **Endpoint:** `https://mcp.apify.com?tools=labrat011/reddit-scraper`
- **Auth:** `Authorization: Bearer <APIFY_TOKEN>`
- **Transport:** Streamable HTTP
- **Works with:** Claude Desktop, Cursor, VS Code, Windsurf, Warp, Gemini CLI

**Example MCP config (Claude Desktop / Cursor):**

```json
{
    "mcpServers": {
        "reddit-scraper": {
            "url": "https://mcp.apify.com?tools=labrat011/reddit-scraper",
            "headers": {
                "Authorization": "Bearer <APIFY_TOKEN>"
            }
        }
    }
}
```

AI agents can use this actor to search Reddit for discussions, scrape subreddit posts, extract comment threads, and monitor user activity -- all as a callable MCP tool.

---

## Feedback

Found a bug or have a feature request? Open an issue on the actor's Issues tab in Apify Console.
