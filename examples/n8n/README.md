# n8n example: Reddit pain point finder

A scheduled n8n workflow that searches Reddit for complaint language, tags which phrase matched, and appends the results to a Google Sheet.

It searches the *language people use when they are frustrated* rather than product names, which surfaces buying-intent posts before anyone has named a specific tool.

## Import

`reddit-pain-point-finder.json` contains no credentials. Import it, then attach your own.

## Setup

1. **Install the Apify community node.** No Apify node ships with n8n.

   ```
   Settings > Community nodes > Install > @apify/n8n-nodes-apify
   ```

2. **Apify credential.** On the `Search Reddit for Pain Points` node, add your Apify API token. A free token is enough; free accounts are capped at 25 results per run.

3. **Google Sheets credential.** On the `Log Pain Points to Sheet` node, connect your Google account and paste your spreadsheet ID in place of `PASTE_YOUR_SPREADSHEET_ID_HERE`. Set **Mapping Column Mode** to `Map Automatically`.

4. **Prepare the sheet.** Name the tab `Reddit Pain Points` and put these twelve headers in row 1, in any order:

   ```
   date, id, title, url, subreddit, author, score, comments, upvoteRatio, matchedPhrase, body, created
   ```

   Auto-mapping matches on header name, so a missing header silently drops that column.

5. **Edit your phrases.** Open the Apify node and change `searchQueriesList` in the Input JSON field.

## Two settings that decide whether this works

**Quote your phrases.** Reddit matches loose words by default. `looking for an alternative to` unquoted returns posts containing some of those common words, which is close to random. Quoted, it matches the phrase.

**Use `searchSort: "top"` with `timeFilter`.** The default `relevance` sort favours highly upvoted posts, which are often years old. `timeFilter` only takes effect when the sort is `top`.

## Choosing phrases

Phrase choice decides your audience, not just your precision:

| Phrase | What it finds |
|---|---|
| `"looking for an alternative to"` | People leaving a product they pay for |
| `"anyone know a better way to"` | People doing an unpaid chore, mostly hobbies |

Phrases that presuppose an existing paid product find buyers. Generic frustration phrases find engagement. Both match perfectly; only one is useful for lead generation.

## Notes

- The Sheets step uses **Append Row**, so a scheduled re-run appends a post again if it is still in the results. To upsert instead, switch to **Append or Update Row** and set Column to Match On to `id`.
- `maxResults` is a budget for the whole run, consumed one query at a time. With six phrases and `maxResults: 25`, the first phrase can use the entire budget.
- The Code node reads the phrase list back off the Apify node, so the list lives in one place. Renaming the Apify node breaks that lookup.

Built on [labrat011/reddit-scraper](https://apify.com/labrat011/reddit-scraper).
