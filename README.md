# Reddit Scraper

Scrape Reddit posts, comments, search results, and user profiles at scale. Works with n8n, Make, and Zapier. No API keys, no login, no OAuth. Batch search across multiple queries in one run. MCP-ready for AI agent pipelines. 97.7% success rate.

## What does it do?

Reddit Scraper pulls structured data from `old.reddit.com` - no OAuth, no Reddit API credentials. You get clean, consistent JSON output ready for analysis, NLP pipelines, or downstream AI tools.

**v1.3.0:** Input schema rewritten for clarity, including for AI agents calling this actor over MCP. Documents that search phrases must be quoted for exact matching, that `maxResults` is a run-wide budget shared across queries, and that `timeFilter` only applies when the sort is `top`. `searchQueriesList` now renders as a string list rather than a raw JSON field. No change to scraping behaviour.

**v1.2.0:** Reddit shut down its public `.json` API (returns 403 since May 2026). This actor now parses Reddit's server-rendered HTML instead, so it keeps working where `.json`-based scrapers broke. Output stays the same. Also added a fail-fast health check and faster request pacing.

**v1.1.0:** Added batch search (`searchQueriesList`) - run multiple queries in a single job with automatic deduplication by post ID.

## 👥 Who Uses This

### 🏢 Brand and Market Researchers

You need to know what real people say about your product, competitors, or industry - not curated press releases, but unfiltered community discussion. Reddit is where honest opinions live. This actor lets you monitor multiple brand terms or competitor names in one run, deduplicated and ready for sentiment analysis.

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

You need topic-specific text at scale - Reddit comments and posts for training classifiers, fine-tuning embeddings, building sentiment models, or labeling datasets. The structured output (author, score, depth, timestamp) gives you signal for quality filtering without post-processing.

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

You want to understand what problems your target market is describing in their own words - not survey responses, but organic complaints, feature requests, and workaround threads. Reddit search across the right subreddits is a fast way to do Jobs-to-Be-Done research before writing a single line of code.

**Discovery research across communities:**

```json
{
    "mode": "search",
    "searchQueriesList": ["\"wish there was a tool for\"", "\"looking for software that\"", "\"does anyone know how to automate\""],
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

Use `user_profile` mode to audit a specific account's post and comment history across subreddits - useful for investigating astroturfing, coordinated behavior, or tracking how a public figure's community engagement evolves.

---

### 🤖 AI/LLM Engineers and Agent Builders

You're building AI pipelines that need real-time access to community knowledge. RAG systems grounded in current Reddit discussions, agents that can search subreddits on demand, or workflows that pull fresh posts into an LLM context window.

**MCP tool config for Claude Desktop / Cursor / VS Code / Windsurf / Gemini CLI:**

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

This actor works as a hosted MCP tool via Apify's MCP server. No custom server, no infrastructure. Once configured, your AI agent can call `reddit-scraper` as a tool to search any subreddit, pull comment threads, or monitor user activity. Combine with other actors for multi-source research pipelines.

**Quick setup (Claude Code):**
```
claude mcp add reddit-scraper \
  -e APIFY_TOKEN=<YOUR_APIFY_TOKEN> \
  -- npx -y @apify/actors-mcp-server@latest --actors labrat011/reddit-scraper
```

---

## Features

- **4 scraping modes:** subreddit posts, Reddit search, user profiles, post comments
- **Batch search:** run multiple search queries in a single job - results merged and deduplicated by post ID
- **Multi-target:** subreddits, usernames, and post URLs all accept lists - scrape many at once
- **Sort and filter:** hot, new, top (with configurable time range), rising, controversial
- **Full comment trees:** recursive extraction with depth tracking
- **Search scope:** across all of Reddit or restricted to a single subreddit
- **User profiles:** posts only, comments only, or both
- **NSFW filter:** optionally include or exclude adult content
- **Pagination:** automatic page-following up to Reddit's ~1,000-item limit
- **Browser-grade requests:** Playwright with Chrome TLS impersonation + rotating residential IPs to avoid blocks
- **28 output fields per post** - including upvote ratio, author flair, content type hints, edit timestamps, and crosspost detection
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

Sort options: `hot`, `new`, `top`, `rising`. `timeFilter` applies only when the sort is `top`: `hour`, `day`, `week`, `month`, `year`, `all`.

The same rule holds in Search mode, where the sort field is `searchSort`. `timeFilter` is accepted with any sort value but only takes effect when that value is `top`. The default `relevance` sort favours highly upvoted posts, which are often years old, so pair `top` with `timeFilter` when you need recent results.

---

### Mode 2: Search Reddit

Search across all of Reddit or within a specific subreddit. Use `searchQueriesList` to run multiple queries in one job.

**Quote your phrases.** Reddit matches loose words by default, so an unquoted multi-word query returns mostly unrelated posts. Wrap a phrase in double quotes to match it exactly:

```json
{ "searchQuery": "\"looking for an alternative to\"" }
```

Unquoted, `looking for an alternative to` matches any post containing some of those common words. Quoted, it matches the phrase.

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

`maxResults` is a budget for the whole run, not per query, and it is consumed one query at a time. With six queries and `maxResults: 25`, the first query can use the entire budget and the rest return nothing. Allow at least 25 per query you expect results from.

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
| `subreddits` | string[] | - | Subreddit names (without r/ prefix). Mode: subreddit_posts |
| `sort` | string | `hot` | Sort order: `hot`, `new`, `top`, `rising` |
| `timeFilter` | string | `week` | Time range. Applies **only** when the sort is `top` (`sort` in subreddit mode, `searchSort` in search mode): `hour`, `day`, `week`, `month`, `year`, `all` |
| `searchQuery` | string | - | Single search term. Wrap in double quotes for exact-phrase matching. Mode: search |
| `searchQueriesList` | string[] | `[]` | Multiple search queries, merged and deduplicated. Quote each phrase for exact matching. Overrides `searchQuery`. Mode: search |
| `searchSubreddit` | string | - | Restrict search to one subreddit. Leave empty for all of Reddit |
| `searchSort` | string | `relevance` | Search sort: `relevance`, `hot`, `top`, `new`, `comments` |
| `usernames` | string[] | - | Reddit usernames (without u/ prefix). Mode: user_profile |
| `userContentType` | string | `overview` | `overview` (posts+comments), `submitted`, `comments` |
| `postUrls` | string[] | - | Full Reddit post URLs. Mode: post_comments |
| `maxCommentsPerPost` | integer | `100` | Max comments per post. `0` = no limit |
| `maxResults` | integer | `100` | Max results for the whole run (1–10,000), shared across all queries and consumed in order. Free tier: 25 per run |
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
| `upvoteRatio` | number | Upvote ratio (0–1), community consensus signal |
| `edited` | timestamp/false | Unix timestamp of last edit, or `false` if never edited |
| `postHint` | string | Post type hint: `link`, `self`, `image`, `video`, `rich:video` |
| `isOriginalContent` | boolean | Original content (OC) flag |
| `authorFlair` | string | Author's subreddit flair text |
| `crosspostParent` | string | Parent post ID if crosspost (`t3_xxx`) |
| `mediaOnly` | boolean | Media-only post with no text body |
| `isGallery` | boolean | Reddit gallery post |

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
| `edited` | timestamp/false | Unix timestamp of last edit, or `false` if never edited |

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
    "isPromoted": false,
    "upvoteRatio": 0.89,
    "postHint": "self",
    "isOriginalContent": true,
    "authorFlair": "Expert",
    "mediaOnly": false,
    "isGallery": false
}
```

---

## Cost

This actor uses **pay-per-event (PPE) pricing** - you pay only for results you get.

- Charged per dataset item pushed (default Apify PPE event)
- **Proxy traffic** is billed separately (residential proxies run ~$12.50/GB on Apify)
- Typical cost: **$1.50 per 1,000 results** depending on proxy usage and whether comments are included
- **Free tier: 25 results per run** - no subscription required
- **Paid tier: up to 10,000 results per run**

**Worked pricing example:**
Searching 3 subreddits for "python framework", sorting by top of the month, returning 100 results:
- ~4-8 requests × 25 items each
- ~$0.15–0.20 in event charges (100 items × $1.50/1k + $0.02 run start)
- ~$0.01–0.03 in residential proxy traffic
- **Total: ~$0.17–0.20 per run**

Each listing page returns ~25 posts, and requests are paced at roughly 1 per second over rotating residential IPs. A 100-post subreddit run takes well under a minute. Enabling `includeComments` adds one request per post.

---

## MCP Integration

This actor works as an MCP tool via Apify's hosted MCP server. No custom server needed - AI agents can call it directly.

- **Endpoint:** `https://mcp.apify.com?tools=labrat011/reddit-scraper`
- **Auth:** `Authorization: Bearer <APIFY_TOKEN>`
- **Transport:** Streamable HTTP
- **Works with:** n8n, Make, Zapier, Claude Desktop, Cursor, VS Code, Windsurf, Warp, Gemini CLI

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

AI agents can search Reddit for discussions, scrape subreddit posts, pull comment threads, and monitor user activity - all as a callable tool without managing any infrastructure.

**If you are calling this from an agent, two settings matter most:**

- **Quote your phrases.** Reddit matches loose words unless a phrase is quoted, so `"looking for an alternative to"` and `looking for an alternative to` return very different results. The unquoted form succeeds and returns mostly unrelated posts, with no error to signal it.
- **Pair `searchSort: "top"` with `timeFilter`.** The default `relevance` sort favours highly upvoted posts, which are often years old. `timeFilter` has no effect on any other sort value.

---

## Technical details

- Parses `old.reddit.com` server-rendered HTML - no API credentials, no OAuth. (Reddit's `.json` API now returns 403; this actor does not depend on it.)
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
- `"Load more comments"` nodes in deep comment trees are not expanded - only the initially loaded tree (up to 500 comments/post) is extracted


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



## Why This Scraper vs Alternatives

| Feature | Reddit Scraper (labrat011) | spry_wholemeal/reddit-scraper (FREE) | trudax/reddit-scraper | harshmaur/reddit-scraper-pro |
|---|---|---|---|---|
| **Price per 1k** | **$1.50** | Free (platform compute only) | ~$4 + $45/mo sub | $20/mo |
| **Rating** | 0.0 (0 reviews) | **5.0** (12 reviews) | 2.5 | 4.7 |
| **Total Users** | 214 | **1,100** | 14K | 2.8K |
| **MAU** | 62 | **221** | - | - |
| **Works after May '26 .json die-off** | ✅ Playwright warm-up | ? | ? | ❌ |
| **Need Reddit API key / OAuth** | **No** | No | No | No |
| **MCP Server (AI agent)** | ✅ Apify hosted MCP | ✅ Custom npx MCP | ❌ | ❌ |
| **NSFW filter** | ✅ | ❌ | ❌ | ❌ |
| **Controversial sort** | ✅ | ❌ | ❌ | ❌ |
| **Batch search (multi-query)** | ✅ | ❌ | ❌ | ❌ |
| **User profile scraping** | ✅ | ❌ | ❌ | ❌ |
| **Free tier** | ✅ 25 results/run | ✅ Free all results | ❌ | ✅ Limited |
| **Updated since May '26** | ✅ Yes (v1.2) | Possibly not | Unlikely | Unlikely |

**Key advantages:** After Reddit shut down its public `.json` API in May 2026, this actor was updated to use Playwright-based browser warm-up to solve Cloudflare challenges. Competitors that still depend on the old `.json` endpoints now return 403s. At $1.50/1k, you get affordable scalable results with MCP support, batch search, user profiles, controversial sorting, and an NSFW filter.

**About the free competitor:** spry_wholemeal/reddit-scraper is a solid free option for light use. Its paid counterpart (harshmaur/reddit-scraper-pro) costs $20/mo. Neither offers batch search, user profiles, controversial sort, or NSFW filtering. If you need any of those -- or need to know your scraper works after May 2026 -- this actor is the right choice.

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

## n8n example

A ready-to-import n8n workflow: scheduled Reddit search, phrase tagging, and
append to Google Sheets. It searches the language people use when they are
frustrated rather than product names, which surfaces buying-intent posts
before anyone has named a specific tool. The workflow below carries no
credentials.

**Setup**

1. Install the Apify community node. n8n does not ship one:
   `Settings > Community nodes > Install > @apify/n8n-nodes-apify`
2. On the `Search Reddit for Pain Points` node, add your Apify API token. A
   free token works; free accounts are capped at 25 results per run.
3. On the `Log Pain Points to Sheet` node, connect Google and paste your
   spreadsheet ID. Set **Mapping Column Mode** to `Map Automatically`.
4. Name the sheet tab `Reddit Pain Points` and put these twelve headers in
   row 1, in any order: `date, id, title, url, subreddit, author, score,
   comments, upvoteRatio, matchedPhrase, body, created`. Auto-mapping matches
   on header name, so a missing header silently drops that column.
5. Edit `searchQueriesList` in the Apify node to your own phrases.

Two settings decide whether this works. **Quote your phrases**: Reddit matches
loose words by default, so `looking for an alternative to` unquoted returns
posts sharing a few common words, which is close to random. Quoted, it matches
the phrase. And **use `searchSort: "top"` together with `timeFilter`**: the
default `relevance` sort favours highly upvoted posts that are often years
old, and `timeFilter` only takes effect when the sort is `top`.

<details>
<summary>reddit-pain-point-finder.json, click to expand</summary>

```json
{
  "name": "RatLabs - Reddit Pain Point Finder Template (labrat011/reddit-scraper)",
  "nodes": [
    {
      "id": "setup-note",
      "name": "Setup Instructions",
      "type": "n8n-nodes-base.stickyNote",
      "typeVersion": 1,
      "position": [
        -400,
        0
      ],
      "parameters": {
        "width": 440,
        "height": 620,
        "content": "## Who this is for\nFounders and growth teams who want to find buying-intent posts on Reddit BEFORE anyone names a specific product - the earliest, highest-value lead signal Reddit has.\n\n## Setup (4 steps)\n\n1. **Install the Apify node**: Settings > Community nodes > Install > `@apify/n8n-nodes-apify`. This template will not import without it.\n\n2. **Apify credential**: On 'Search Reddit for Pain Points', add your Apify API token (Credentials > Apify API key connection). Get a free token at apify.com - this actor is Pay Per Event, no subscription needed.\n\n3. **Google Sheets credential**: Connect your Google account on 'Log Pain Points to Sheet' and paste your Spreadsheet ID. Set Mapping Column Mode to `Map Automatically`. The tab must be named `Reddit Pain Points` and row 1 must contain these twelve headers, in any order:\ndate, id, title, url, subreddit, author, score, comments, upvoteRatio, matchedPhrase, body, created\n\n4. **Edit your search**: Open 'Search Reddit for Pain Points' and edit `searchQueriesList` in the Input JSON field with the complaint phrases for your niche. KEEP THE QUOTES around each phrase - they are what makes Reddit match the phrase instead of the loose words. The Code node reads this same list, so you only edit it here.\n\n---\nWhat this does differently: instead of searching for your product/keyword directly, it searches for the LANGUAGE people use when they're frustrated and looking for a solution - 'is there a tool that', 'so sick of', 'looking for an alternative to'. This surfaces buying-intent posts before anyone mentions a specific product.\n\n---\nTwo settings that decide whether this works at all:\n- Phrases MUST be quoted. Unquoted, Reddit matches the words separately and you get random posts.\n- searchSort is `relevance`, not `new`. Sorting by new samples whatever was posted in the last few minutes, and the matches drown.\n\n---\nNot a database. A live query, run when you need it. Every result comes straight off Reddit at run time, not a cached snapshot going stale in someone's warehouse.\n\nBuilt on labrat011/reddit-scraper - also callable directly by AI agents via Apify's MCP endpoint, no custom server needed: https://mcp.apify.com?tools=labrat011/reddit-scraper\n\nhttps://apify.com/labrat011/reddit-scraper\n\nNo Reddit API keys needed. ~$1.50/1,000 results, pay per run. searchQueriesList batches multiple phrases in one run. Free-tier Apify accounts are capped at 25 results/run - raise maxResults if you're on a paid plan.\n\nThe sheet step uses Append Row. A scheduled re-run appends a post again if it is still in the search results. To upsert instead, switch the operation to `Append or Update Row` and set Column to Match On = `id`."
      }
    },
    {
      "id": "schedule-trigger",
      "name": "Daily Schedule",
      "type": "n8n-nodes-base.scheduleTrigger",
      "typeVersion": 1.1,
      "position": [
        0,
        300
      ],
      "parameters": {
        "rule": {
          "interval": [
            {
              "field": "cronExpression",
              "expression": "0 9 * * *"
            }
          ]
        }
      }
    },
    {
      "id": "manual-trigger",
      "name": "Run Manually",
      "type": "n8n-nodes-base.manualTrigger",
      "typeVersion": 1,
      "position": [
        0,
        460
      ],
      "parameters": {}
    },
    {
      "id": "apify-reddit-pain",
      "name": "Search Reddit for Pain Points",
      "type": "@apify/n8n-nodes-apify.apify",
      "typeVersion": 1,
      "position": [
        280,
        380
      ],
      "parameters": {
        "authentication": "apifyApi",
        "resource": "Actors",
        "operation": "Run actor and get dataset",
        "actorSource": "store",
        "actorId": {
          "__rl": true,
          "mode": "id",
          "value": "labrat011~reddit-scraper"
        },
        "customBody": "{\n  \"mode\": \"search\",\n  \"searchQueriesList\": [\n    \"\\\"is there a tool that\\\"\",\n    \"\\\"looking for an alternative to\\\"\",\n    \"\\\"anyone know a better way to\\\"\",\n    \"\\\"anyone else hate\\\"\",\n    \"\\\"so sick of\\\"\",\n    \"\\\"is there a better way\\\"\"\n  ],\n  \"searchSubreddit\": \"\",\n  \"searchSort\": \"relevance\",\n  \"maxResults\": 25\n}",
        "memory": 1024,
        "build": "",
        "notes": "REQUIRED: add an Apify API credential. Phrases in searchQueriesList are wrapped in escaped quotes so Reddit does exact-phrase matching - without quotes Reddit treats them as loose words and returns unrelated posts. searchSort is 'relevance', not 'new': sorting by new samples Reddit's firehose and buries the matches. The Code node downstream reads this same list, so this is the only place you edit it. Set searchSubreddit to one subreddit (no r/ prefix) to scope the hunt, or leave empty to search all of Reddit. maxResults defaults to 25 to match the free-tier cap. Actor ID uses Apify's username~actor-name format, with a TILDE - a slash produces a 404."
      }
    },
    {
      "id": "tag-posts",
      "name": "Dedupe & Tag Matched Phrase",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [
        520,
        380
      ],
      "parameters": {
        "language": "javaScript",
        "code": "const posts = $input.all().map(item => item.json);\n\n// Single source of truth: read the phrase list back off the Apify node so\n// editing searchQueriesList in one place stays correct. Phrases are quoted\n// in the query so Reddit does exact-phrase matching; the quotes are stripped\n// here before the substring test.\nlet painPhrases = [];\ntry {\n  const raw = $('Search Reddit for Pain Points').params.customBody;\n  painPhrases = (JSON.parse(raw).searchQueriesList || [])\n    .map(phrase => phrase.replace(/\"/g, '').trim());\n} catch (e) {\n  painPhrases = [];\n}\n\n// Dedupe on Reddit's stable post id, then again on title to catch crossposts,\n// which are separate posts with separate ids but identical content.\nconst seenId = new Set();\nconst seenTitle = new Set();\nconst deduped = posts.filter(p => {\n  const id = p.id || p.url;\n  const title = (p.title || '').trim().toLowerCase();\n  if (!id || seenId.has(id)) return false;\n  if (title && seenTitle.has(title)) return false;\n  seenId.add(id);\n  if (title) seenTitle.add(title);\n  return true;\n});\n\nreturn deduped.map(p => {\n  const text = ((p.title || '') + ' ' + (p.selftext || '')).toLowerCase();\n  const matched = painPhrases.filter(phrase => text.includes(phrase.toLowerCase()));\n  return {\n    json: {\n      id: p.id || '',\n      title: p.title || 'Untitled',\n      url: p.url || '',\n      subreddit: p.subreddit || 'unknown',\n      author: p.author || 'unknown',\n      score: p.score || 0,\n      comments: p.numComments || 0,\n      upvoteRatio: p.upvoteRatio ?? '',\n      matchedPhrase: matched.length ? matched.join('; ') : 'search match (no exact phrase)',\n      body: (p.selftext || '').slice(0, 500),\n      created: p.created || ''\n    }\n  };\n});"
      }
    },
    {
      "id": "set-date",
      "name": "Add Log Date",
      "type": "n8n-nodes-base.set",
      "typeVersion": 3.4,
      "position": [
        760,
        380
      ],
      "parameters": {
        "assignments": {
          "assignments": [
            {
              "id": "date-field",
              "name": "date",
              "type": "string",
              "value": "={{ $now.toFormat('yyyy-MM-dd') }}"
            }
          ]
        },
        "includeOtherFields": true
      }
    },
    {
      "id": "log-to-sheet",
      "name": "Log Pain Points to Sheet",
      "type": "n8n-nodes-base.googleSheets",
      "typeVersion": 4.5,
      "position": [
        1000,
        380
      ],
      "parameters": {
        "resource": "sheet",
        "operation": "append",
        "documentId": {
          "__rl": true,
          "value": "PASTE_YOUR_SPREADSHEET_ID_HERE",
          "mode": "id"
        },
        "sheetName": {
          "__rl": true,
          "value": "Reddit Pain Points",
          "mode": "name"
        },
        "columns": {
          "mappingMode": "autoMapInputData"
        },
        "notes": "Append Row. The tab must be named 'Reddit Pain Points' and row 1 must be: date, id, title, url, subreddit, author, score, comments, upvoteRatio, matchedPhrase, body, created. Note: a scheduled re-run appends the same post again. To upsert instead, switch the operation to 'Append or Update Row' and set Column to Match On = id."
      }
    }
  ],
  "connections": {
    "Daily Schedule": {
      "main": [
        [
          {
            "node": "Search Reddit for Pain Points",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Run Manually": {
      "main": [
        [
          {
            "node": "Search Reddit for Pain Points",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Search Reddit for Pain Points": {
      "main": [
        [
          {
            "node": "Dedupe & Tag Matched Phrase",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Dedupe & Tag Matched Phrase": {
      "main": [
        [
          {
            "node": "Add Log Date",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Add Log Date": {
      "main": [
        [
          {
            "node": "Log Pain Points to Sheet",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  },
  "settings": {},
  "pinData": {}
}
```

</details>

## License

MIT.

## Feedback

Found a bug or have a feature request? Open an issue on the Issues tab in Apify Console.
