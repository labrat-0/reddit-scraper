# Reddit Scraper

Scrape Reddit posts, comments, search results, and user profiles at scale. No API keys, no login, no OAuth. Batch search across multiple queries in one run. MCP-ready for AI agent pipelines.

## What does it do?

Reddit Scraper pulls structured data from `old.reddit.com` — no OAuth, no Reddit API credentials. You get clean, consistent JSON output ready for analysis, NLP pipelines, or downstream AI tools.

**v1.2.0:** Reddit shut down its public `.json` API (returns 403 since May 2026). This actor now parses Reddit's server-rendered HTML instead, so it keeps working where `.json`-based scrapers broke. Output stays the same. Also added a fail-fast health check and faster request pacing.

**v1.1.0:** Added batch search (`searchQueriesList`) — run multiple queries in a single job with automatic deduplication by post ID.

## 👥 Who Uses This

### 🏢 Brand and Market Researchers

You need to know what real people say about your product, competitors, or industry — not curated press releases, but unfiltered community discussion. Reddit is where honest opinions live. This actor lets you monitor multiple brand terms or competitor names in one run, deduplicated and ready for sentiment analysis.

**Typical input:**

```json
{
    "mode": "search",
    "searchQueriesList": ["YourBrand review", "CompetitorA vs CompetitorB", "best CRM 2025"],
    "searchSort": "top",
    "timeFilter": "year",
    "maxResults": 500,
    "includeComments": true
}
```

Run this on a schedule (daily or weekly via Apify schedules) to track brand sentiment shifts over time without touching the Reddit website.

---

### 💻 NLP and ML Engineers

You need topic-specific text at scale — Reddit comments and posts for training classifiers, fine-tuning embeddings, building sentiment models, or labeling datasets. The structured output (author, score, depth, timestamp) gives you signal for quality filtering without post-processing.

**Collect training data from multiple subreddits:**

```json
{
    "mode": "subreddit_posts",
    "subreddits": ["MachineLearning", "LocalLLaMA", "datascience", "learnmachinelearning"],
    "sort": "top",
    "timeFilter": "year",
    "maxResults": 2000,
    "includeComments": true
}
```

Filter by `score` (high-upvote posts = community-validated content) and `depth` (top-level comments = more coherent standalone text). The `userContentType` field on user profile mode lets you pull comment-only output for dialogue dataset construction.

---

### 🛠️ Product Teams and Startups

You want to understand what problems your target market is describing in their own words — not survey responses, but organic complaints, feature requests, and workaround threads. Reddit search across the right subreddits is a fast way to do Jobs-to-Be-Done research before writing a single line of code.

**Discovery research across communities:**

```json
{
    "mode": "search",
    "searchQueriesList": ["wish there was a tool for", "looking for software that", "does anyone know how to automate"],
    "searchSubreddit": "entrepreneur",
    "searchSort": "relevance",
    "maxResults": 200
}
```

Use batch search to sweep multiple pain-point queries across a single subreddit or across all of Reddit. Export to CSV for tagging and clustering in a spreadsheet.

---

### 📰 Social Media Analysts and Journalists

You're tracking narratives, investigating communities, or mapping how opinions shift around a topic over time. Reddit's threaded comment structure and upvote system give you signal on consensus and dissent that flat social feeds don't provide.

**Pull full comment trees from key posts:**

```json
{
    "mode": "post_comments",
    "postUrls": [
        "https://www.reddit.com/r/politics/comments/abc123/some_breaking_story/",
        "https://www.reddit.com/r/technology/comments/def456/another_post/"
    ],
    "maxCommentsPerPost": 1000
}
```

Use `user_profile` mode to audit a specific account's post and comment history across subreddits — useful for investigating astroturfing, coordinated behavior, or tracking how a public figure's community engagement evolves.

---

### 🤖 AI/LLM Engineers and Agent Builders

You're building AI pipelines that need real-time access to community knowledge — RAG systems grounded in current Reddit discussions, agents that can search subreddits on demand, or workflows that pull fresh posts into an LLM context window.

**MCP tool config for Claude Desktop / Cursor:**

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

Once configured, your AI agent can call `reddit-scraper` as a tool to search any subreddit, pull comment threads, or monitor user activity — no infrastructure to manage. Combine with other actors in the healthcare or finance cluster for multi-source research pipelines.

---

## Features

- **4 scraping modes:** subreddit posts, Reddit search, user profiles, post comments
- **Batch search:** run multiple search queries in a single job — results merged and deduplicated by post ID
- **Multi-target:** subreddits, usernames, and post URLs all accept lists — scrape many at once
- **Sort and filter:** hot, new, top (with configurable time range), rising
- **Full comment trees:** recursive extraction with depth tracking
- **Search scope:** across all of Reddit or restricted to a single subreddit
- **User profiles:** posts only, comments only, or both
- **Pagination:** automatic page-following up to Reddit's ~1,000-item limit
- **Browser-grade requests:** Chrome TLS impersonation (`curl_cffi`) + rotating residential IPs to avoid blocks
- **Retry logic:** exponential backoff on 429, IP rotation on 403
- **Fail-fast health check:** a run that scrapes 0 results fails loudly instead of silently billing compute
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
| `numComments` | integer | Total comment count |
| `created` | string | ISO 8601 UTC timestamp |
| `isNSFW` | boolean | NSFW flag |
| `isSpoiler` | boolean | Spoiler flag |
| `isPinned` | boolean | Stickied/pinned flag |
| `flair` | string | Post flair text |
| `awards` | integer | Award (gilding) count |
| `domain` | string | Link domain (e.g. `self.python`) |
| `isVideo` | boolean | Video post flag |
| `thumbnail` | string | Thumbnail URL (empty for self/text posts) |
| `isPromoted` | boolean | Whether the post is a promoted ad |

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
| `depth` | integer | Nesting depth (0 = top-level) |
| `isSubmitter` | boolean | Whether author is the post's OP |
| `awards` | integer | Award (gilding) count |
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
    "numComments": 312,
    "created": "2025-03-01T09:14:22+00:00",
    "isNSFW": false,
    "isSpoiler": false,
    "isPinned": false,
    "flair": "Discussion",
    "awards": 5,
    "domain": "self.Python",
    "isVideo": false,
    "thumbnail": "",
    "isPromoted": false
}
```

---

## Cost

This actor uses **pay-per-event (PPE) pricing** — you pay only for results you get.

- Charged per dataset item pushed (default Apify PPE event)
- **Proxy traffic** is billed separately (residential proxies run ~$12.50/GB on Apify)
- Typical cost: **$0.50–$1.00 per 1,000 results** depending on proxy usage and whether comments are included
- **Free tier: 25 results per run** — no subscription required
- **Paid tier: up to 10,000 results per run**

**Worked pricing example:**
Searching 3 subreddits for "python framework", sorting by top of the month, returning 100 results:
- ~4-8 requests × 25 items each
- ~$0.15–0.20 in event charges (100 items × $1.50/1k + $0.01 run start)
- ~$0.01–0.03 in residential proxy traffic
- **Total: ~$0.16–0.23 per run**

Each listing page returns ~25 posts, and requests are paced at roughly 1 per second over rotating residential IPs. A 100-post subreddit run takes well under a minute. Enabling `includeComments` adds one request per post.

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

- Parses `old.reddit.com` server-rendered HTML — no API credentials, no OAuth. (Reddit's `.json` API now returns 403; this actor does not depend on it.)
- Requests use Chrome TLS impersonation via `curl_cffi` to pass Reddit's bot fingerprinting
- Paced at ~1 request/second with jitter over rotating residential IPs
- Exponential backoff on 429 (5s base, doubles per retry); IP rotation on 403
- Pagination by following the listing's next-page link (up to ~1,000 items per listing)
- Results pushed in batches of 25 for memory efficiency
- Fail-fast health check: a run that yields 0 results fails with a clear message
- Actor state persisted across Apify platform migrations

---

## Limitations

- Reddit caps listing pagination at roughly 1,000 items per subreddit/user endpoint
- `"Load more comments"` nodes in deep comment trees are not expanded — only the initially loaded tree (up to 500 comments/post) is extracted
- Datacenter proxies will not work — Reddit has blocked nearly all datacenter IP ranges. Residential proxies are required.
- `upvoteRatio` is not available from Reddit's HTML and is therefore not included in output

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

## 🔗 Related Actors

| Actor | What it does | Pairs well with Reddit Scraper when... |
|-------|-------------|----------------------------------------|
| [Academic Paper Scraper](https://apify.com/labrat011/academic-paper-scraper) | Google Scholar, Semantic Scholar, arXiv | You find a paper discussed on Reddit and want the full metadata and abstract |
| [PubMed Scraper](https://apify.com/labrat011/pubmed-scraper) | 35M+ biomedical abstracts from NCBI | r/science or health subreddit posts reference medical studies you want to retrieve |
| [Clinical Trials Scraper](https://apify.com/labrat011/clinical-trials-scraper) | ClinicalTrials.gov study data | Reddit health communities discuss ongoing trials you want to track |
| [LinkedIn Jobs Scraper](https://apify.com/labrat011/linkedin-jobs-scraper) | Job postings and company data | You monitor r/cscareerquestions or industry subreddits and want matching job listings |
| [NPI Provider Contact Finder](https://apify.com/labrat011/npi-provider-contact-finder) | Healthcare provider directory | Health subreddit discussions lead to provider lookup needs |

---

## Feedback

Found a bug or have a feature request? Open an issue on the Issues tab in Apify Console.
