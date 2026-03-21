# Reddit Scraper

Scrape Reddit posts, comments, search results, and user profiles at scale. No API keys, no login, no browser required. Batch search across multiple queries in one run. MCP-ready for AI agent pipelines.

## What does it do?

Reddit Scraper pulls structured data from Reddit using `old.reddit.com` JSON endpoints — no OAuth, no Reddit API credentials, no headless browser. You get clean, consistent JSON output ready for analysis, NLP pipelines, or downstream AI tools.

**v1.1.0:** Added batch search (`searchQueriesList`) — run multiple queries in a single job with automatic deduplication by post ID.

## Who uses this

- **Brand and market researchers** — monitor what people say about your product, competitors, or industry across thousands of threads without manual browsing
- **NLP and sentiment analysis engineers** — collect topic-specific posts and comments at scale for training classifiers, fine-tuning embeddings, or labeling datasets
- **AI/LLM training data teams** — harvest diverse, high-quality human-written text from specific communities and topics
- **Social media analysts and journalists** — track narratives, investigate communities, map opinion shifts over time
- **Developers and AI agents** — call via Apify API or expose as an MCP tool so agents can query Reddit in real time

## Features

- **4 scraping modes:** subreddit posts, Reddit search, user profiles, post comments
- **Batch search:** run multiple search queries in a single job — results merged and deduplicated by post ID
- **Multi-target:** subreddits, usernames, and post URLs all accept lists — scrape many at once
- **Sort and filter:** hot, new, top (with configurable time range), rising
- **Full comment trees:** recursive extraction with depth tracking
- **Search scope:** across all of Reddit or restricted to a single subreddit
- **User profiles:** posts only, comments only, or both
- **Pagination:** automatic via Reddit's `after` cursor
- **Rate limiting:** 7s between requests to stay under Reddit's unauthenticated limits
- **Retry logic:** exponential backoff on 429, proxy rotation on 403
- **State persistence:** survives Apify actor migrations mid-run

---

## Scraping modes

### Mode 1: Subreddit Posts

Scrape posts from one or more subreddits.

```json
{
    "mode": "subreddit_posts",
    "subreddits": ["python", "machinelearning", "webdev"],
    "sort": "top",
    "timeFilter": "month",
    "maxResults": 200
}
```

Sort options: `hot`, `new`, `top`, `rising`. `timeFilter` applies only when `sort` is `top`: `hour`, `day`, `week`, `month`, `year`, `all`.

---

### Mode 2: Search Reddit

Search across all of Reddit or within a specific subreddit. Use `searchQueriesList` to run multiple queries in one job.

**Single query:**

```json
{
    "mode": "search",
    "searchQuery": "best python web framework 2025",
    "searchSort": "relevance",
    "maxResults": 100
}
```

**Batch search (v1.1.0):**

```json
{
    "mode": "search",
    "searchQueriesList": ["ChatGPT vs Claude", "best LLM 2025", "AI coding assistant"],
    "searchSort": "top",
    "timeFilter": "year",
    "maxResults": 300
}
```

Results across all queries are merged and deduplicated by post ID. `searchQueriesList` overrides `searchQuery` when provided.

**Restricted to a subreddit:**

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

---

### Mode 3: User Profile

Scrape posts and/or comments from Reddit user profiles.

```json
{
    "mode": "user_profile",
    "usernames": ["user1", "user2"],
    "userContentType": "overview",
    "maxResults": 200
}
```

Content type options: `overview` (posts + comments), `submitted` (posts only), `comments` (comments only).

---

### Mode 4: Post Comments

Extract the full comment tree from specific Reddit posts.

```json
{
    "mode": "post_comments",
    "postUrls": [
        "https://www.reddit.com/r/Python/comments/1r19hu1/after_25_years_using_orms_i_switched_to_raw/",
        "https://www.reddit.com/r/machinelearning/comments/abc123/some_post/"
    ],
    "maxCommentsPerPost": 500
}
```

---

## Input parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mode` | string | `subreddit_posts` | Scraping mode: `subreddit_posts`, `search`, `user_profile`, `post_comments` |
| `subreddits` | string[] | — | Subreddit names (without r/ prefix). Mode: subreddit_posts |
| `sort` | string | `hot` | Sort order: `hot`, `new`, `top`, `rising` |
| `timeFilter` | string | `week` | Time range for Top sort: `hour`, `day`, `week`, `month`, `year`, `all` |
| `searchQuery` | string | — | Single search term. Mode: search |
| `searchQueriesList` | string[] | `[]` | Multiple search queries — merged and deduplicated. Overrides `searchQuery`. Mode: search |
| `searchSubreddit` | string | — | Restrict search to one subreddit. Leave empty for all of Reddit |
| `searchSort` | string | `relevance` | Search sort: `relevance`, `hot`, `top`, `new`, `comments` |
| `usernames` | string[] | — | Reddit usernames (without u/ prefix). Mode: user_profile |
| `userContentType` | string | `overview` | `overview` (posts+comments), `submitted`, `comments` |
| `postUrls` | string[] | — | Full Reddit post URLs. Mode: post_comments |
| `maxCommentsPerPost` | integer | `100` | Max comments per post. `0` = no limit |
| `maxResults` | integer | `100` | Max total results (1–10,000). Free tier: 25 per run |
| `includeComments` | boolean | `false` | Also fetch comments for each post in subreddit/search mode. Slower, higher proxy cost |
| `proxyConfiguration` | object | Residential | Proxy settings. Residential proxies required |

---

## Output

Results are saved to the default dataset. Download as JSON, CSV, Excel, or XML from the Output tab.

### Post fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `"post"` |
| `id` | string | Reddit post ID |
| `subreddit` | string | Subreddit name |
| `title` | string | Post title |
| `author` | string | Author username |
| `selftext` | string | Post body text (empty for link posts) |
| `url` | string | Reddit permalink |
| `externalUrl` | string | Linked URL (for link posts) |
| `score` | integer | Net upvotes |
| `upvoteRatio` | float | Upvote percentage (0.0–1.0) |
| `numComments` | integer | Total comment count |
| `created` | string | ISO 8601 UTC timestamp |
| `isNSFW` | boolean | NSFW flag |
| `isSpoiler` | boolean | Spoiler flag |
| `isPinned` | boolean | Stickied/pinned flag |
| `flair` | string | Post flair text |
| `awards` | integer | Total awards received |
| `domain` | string | Link domain |
| `isVideo` | boolean | Video post flag |
| `thumbnail` | string | Thumbnail URL |

### Comment fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `"comment"` |
| `id` | string | Comment ID |
| `postId` | string | Parent post ID |
| `subreddit` | string | Subreddit name |
| `author` | string | Author username |
| `body` | string | Comment text |
| `score` | integer | Net upvotes |
| `created` | string | ISO 8601 UTC timestamp |
| `parentId` | string | Parent comment or post ID |
| `depth` | integer | Nesting depth (0 = top-level) |
| `isSubmitter` | boolean | Whether author is the post's OP |
| `awards` | integer | Total awards received |
| `url` | string | Reddit permalink |

### Example output

```json
{
    "type": "post",
    "id": "1r19hu1",
    "subreddit": "Python",
    "title": "After 25 years using ORMs, I switched to raw SQL",
    "author": "example_user",
    "selftext": "Here's what I learned after making the switch...",
    "url": "https://www.reddit.com/r/Python/comments/1r19hu1/...",
    "externalUrl": "",
    "score": 1842,
    "upvoteRatio": 0.97,
    "numComments": 312,
    "created": "2025-03-01T09:14:22+00:00",
    "isNSFW": false,
    "isSpoiler": false,
    "isPinned": false,
    "flair": "Discussion",
    "awards": 5,
    "domain": "self.Python",
    "isVideo": false,
    "thumbnail": "self"
}
```

---

## Cost

This actor uses **pay-per-event (PPE) pricing** — you pay only for results you get.

- **Proxy traffic** is billed separately (residential proxies run ~$12.50/GB on Apify)
- Typical cost: **$0.50–$1.00 per 1,000 results** depending on proxy usage and whether comments are included
- **Free tier: 25 results per run** — no subscription required
- **Paid tier: up to 10,000 results per run**

Reddit's rate limits mean roughly 8–10 requests per minute. A 100-post subreddit run takes 1–2 minutes. Enabling `includeComments` multiplies run time by the average number of comments per post.

---

## MCP Integration

This actor works as an MCP tool via Apify's hosted MCP server. No custom server needed — AI agents can call it directly.

- **Endpoint:** `https://mcp.apify.com?tools=labrat011/reddit-scraper`
- **Auth:** `Authorization: Bearer <APIFY_TOKEN>`
- **Transport:** Streamable HTTP
- **Works with:** Claude Desktop, Cursor, VS Code, Windsurf, Warp, Gemini CLI

**Claude Desktop / Cursor config:**

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

AI agents can search Reddit for discussions, scrape subreddit posts, pull comment threads, and monitor user activity — all as a callable tool without managing any infrastructure.

---

## Technical details

- Uses `old.reddit.com` JSON endpoints — no API credentials, no OAuth, no browser rendering
- Rate limited to ~10 requests/minute (7-second interval between requests)
- Exponential backoff on 429 rate limit responses (30s base, doubles per retry)
- Proxy rotation on 403 IP blocks
- Pagination via Reddit's `after` cursor (up to ~1,000 items per listing)
- Results pushed in batches of 25 for memory efficiency
- Actor state persisted across Apify platform migrations

---

## Limitations

- Reddit caps unauthenticated listing pagination at roughly 1,000 items per subreddit/user endpoint
- `"Load more comments"` nodes in deep comment trees are not expanded — only the initially loaded tree is extracted
- Datacenter proxies will not work — Reddit has blocked nearly all datacenter IP ranges since mid-2025. Residential proxies are required.
- High-volume runs (1,000+ results) take time due to Reddit's rate limits

---

## FAQ

### Is it legal to scrape Reddit?

Web scraping of publicly available data is generally legal, as established by the *hiQ Labs v. LinkedIn* ruling. This actor only accesses public Reddit content visible to any anonymous browser visitor. It does not bypass login walls, CAPTCHAs, or access private content.

### Why are residential proxies required?

Reddit blocks nearly all datacenter IP ranges. Residential proxies route requests through real ISP connections that Reddit does not filter. Without them, most requests will return 403s.

### How does batch search work?

Set `searchQueriesList` to an array of query strings. The actor runs each query sequentially and merges results into a single dataset, removing duplicate posts (matched by Reddit post ID). This is useful for brand monitoring (track multiple product names in one run), competitive research, or collecting data across related topics.

### Can I use this with the Apify API?

Yes. Call the actor via the Apify REST API and poll for results, or use the Apify Python or JavaScript client libraries. Results are available in JSON, CSV, Excel, and XML formats.

### What happens if a subreddit, user, or post URL doesn't exist?

The scraper logs a warning and skips the invalid target. All remaining valid targets in the same run continue as normal.

---

## Feedback

Found a bug or have a feature request? Open an issue on the Issues tab in Apify Console.
