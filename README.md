# Data Detective

**A website that turns public YouTube data into an honest analysis.** Type a YouTube channel or a brand name and it fetches the public data through the official YouTube Data API, cleans it, explores it, and writes up each finding with its evidence and its limits. A second page collects public **comments about a brand** and scores their sentiment in **English and Roman Urdu**.

> **Live demo:** _add your Render link here after deploying_

## What it does

| Page | What you get |
|---|---|
| `/` | One search box: a channel link, `@handle`, channel ID, video link, or a brand name |
| `/analysis/<id>/...` | Guided results: overview, cleaned data, explore, what it means (Finding / Evidence / Action / Limitation), scaling experiment, model previews, downloadable report |
| `/sentiment` | **Brand sentiment**: comments from the brand's own channel, from other people's videos about it, or both. Filter by source, date and language. Trend over time, topics (price, quality, delivery, service, design, fit), top comments, CSV download |
| `/workbench` | A CSV tool: upload your own file and run the same inspect / clean / explore steps |
| `/how-it-works`, `/about`, `/privacy` | Plain-language pages |

A channel link or `@handle` costs about 10 YouTube quota units. A brand-name search costs 100, then asks you to pick the brand's own channel. The site never claims to find ads: YouTube has no public ads API.

## How the evidence is handled

- **Views are not reach.** Nothing is called reach or "engagement rate on reach".
- **Hidden is not zero.** Hidden likes and disabled comments are treated as missing.
- **Small groups are flagged.** Every comparison shows group sizes, and models switch off below 40 videos.
- **No leakage.** Views, likes and comments are never used to predict themselves.
- **Every report prints its snapshot:** fetch time, what was typed, and the channel ID.

## Brand sentiment: what to know

- Comments are collected with the official API. Only text, date, likes and video title are kept. **No author names or IDs are stored.** Results live in memory and expire after a few hours.
- Two scorers, chosen with `SENTIMENT_BACKEND`:
  - `lexicon` (default): rule-based word lists for English and Roman Urdu, with negation handling. Fast, transparent, no extra install.
  - `model`: a multilingual transformer (needs `requirements-model.txt` and about 1 GB of RAM; suited to Hugging Face Spaces, not Render's free tier).
- **Neither scorer has been proven accurate on Roman Urdu.** Check it on comments you label by hand before quoting any numbers. Comments on a brand's own channel also tend to lean positive, so compare them with public videos.

## Run it locally

```bash
pip install -r requirements.txt
export YOUTUBE_API_KEY=your_key_here      # Windows PowerShell: $env:YOUTUBE_API_KEY="your_key_here"
python app.py                             # open http://127.0.0.1:8000
```

You need a free key: Google Cloud console, enable **YouTube Data API v3**, then create an API key. Without a key the site still starts, and live fetching is switched off.

## Tests

```bash
pip install pytest
python -m pytest -q       # no API key needed: the YouTube layer is replaced by a test double
```

The test data is invented. It has the same shape as real API responses, and exists only so the code can be tested without a key. Tests that need the unlicensed sample CSV are skipped automatically.

## Deploy (GitHub to Render)

1. Push this repo to GitHub.
2. On Render choose **New, Blueprint** and pick this repo. `render.yaml` sets up everything and redeploys on every push.
3. In the Render dashboard add the secret **`YOUTUBE_API_KEY`**. It is never sent to the browser and never logged.
4. Free Render services sleep when idle, so the first visit can take 30 to 60 seconds. All visitors share one daily YouTube quota.

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `YOUTUBE_API_KEY` | none | **Secret.** Your YouTube Data API key |
| `YT_DAILY_QUOTA` | 9000 | Stops the site using more than this many of Google's 10,000 free daily units |
| `YT_DEFAULT_VIDEOS` / `YT_MAX_VIDEOS` | 200 / 300 | Videos fetched per channel analysis |
| `SENTIMENT_BACKEND` | `lexicon` | `lexicon` or `model` |
| `ANALYSIS_TTL_SECONDS` | 21600 | How long a result link works (6 hours) |
| `TRUST_PROXY` | 1 on Render | Lets rate limits see the real visitor IP |

## Project layout

`app.py` (Flask: pages and API) · `youtube.py` (API client) · `comments.py` (collect and clean comments) · `sentiment.py` (scoring and summaries) · `analysis.py` (pandas / scikit-learn) · `report.py` (Markdown report) · `templates/` and `static/` (site pages, CSS, JS, SVG charts) · `tests/` · `lecture/` · `docs/`

## Data, privacy and limits

- Only **public** YouTube data is used, through the official YouTube Data API v3. Not affiliated with or endorsed by YouTube or Google.
- The sample CSV from the original lecture is **not included**, because its source repository has no license. The workbench accepts your own CSV upload instead.
- Results describe one snapshot of public data. They cannot show causes, and they do not measure the quality of a brand.

## Author

Noor Ul Hassan · Big Data
