---
title: Data Detective
emoji: 🔎
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Data Detective

A public website. A visitor types a **YouTube channel or a brand name**; the site fetches the channel's public
videos through the official YouTube Data API v3 and runs the whole lecture project on them: inspect, clean, explore,
interpret (Finding / Evidence / Action / Limitation), scaling experiment, classification / clustering / regression
preview, and a downloadable report. No CSV is needed. (The original CSV tool is still at `/workbench`.)

Built from `docs/project_history_and_youtube_plan.md` (phases 1-7, 5a and 5b).

## Pages
| URL | What |
|---|---|
| `/` | Landing page: one search box (channel link, `@handle`, channel ID, video link, or brand name) |
| `/analysis/<id>/overview` `cleaned` `explore` `sentiment` `meaning` `scaling` `models` `report` | Guided result pages. The link is shareable and expires (6 h by default) |
| `/how-it-works` `/about` `/privacy` | Plain-language pages |
| `/workbench` | The earlier CSV tool (bundled sample dataset or your own upload) |

A channel link or `@handle` costs about 10 YouTube quota units. A **brand name** costs 100 (search) and then shows
candidate channels so the visitor confirms which one is the brand. It never claims to find ads (YouTube has no public ads API).

## Sentiment page (stage B)
The **Sentiment** tab collects public comments (own videos, other people's videos that mention the brand, or both), cleans
and language-tags them (`comments.py`), scores them (`sentiment.py`) and shows shares, a trend, topics, examples, and
narrowing filters (language, source, dates) that cost no quota. Collecting costs shared quota (about 50 to 250 units;
`estimate_units` refuses a run that would break `YT_DAILY_QUOTA` before it starts).

Two scorers, chosen by `SENTIMENT_BACKEND`:
| Value | What | Where it fits |
|---|---|---|
| `lexicon` (default) | Word list for English and Roman Urdu with negation, "but" and emoji rules. Transparent, instant, no extra install. | Render free tier, local |
| `model` | Multilingual transformer (`SENTIMENT_MODEL`, default `cardiffnlp/twitter-xlm-roberta-base-sentiment`). Install `requirements-model.txt`. Roughly 1 GB RAM, so Hugging Face Spaces, not Render free. At most `SENTIMENT_MODEL_MAX` (1500) comments are scored per request, sampled if there are more. If it cannot load, the site falls back to the lexicon and says so on the page. | Hugging Face Spaces |

**Neither scorer is trusted until measured.** The model was not trained on Roman Urdu specifically, so do not assume it is
better there. Measure both on comments a person labelled:
```bash
YOUTUBE_API_KEY=... python tests/eval_sentiment.py sample @khaadi 150   # writes data/to_label.csv
# fill the `label` column (positive / neutral / negative), save as data/sentiment_labelled.csv
SENTIMENT_BACKEND=lexicon python tests/eval_sentiment.py score          # accuracy, baseline, confusion, per language
```
The result is saved to `data/sentiment_accuracy.json`; the page shows it only for the scorer it was measured on.
`data/to_label.csv` and `data/sentiment_labelled.csv` hold other people's public comments and are git-ignored.

**Hugging Face with the model:** in the `Dockerfile` change `ARG WITH_MODEL=0` to `1` and set the Space variable `SENTIMENT_BACKEND=model`.
Also set `WEB_WORKERS=1`: each worker loads its own copy of the model (about 1 GB). Collecting comments can take close to a minute, so the gunicorn timeout is 120 s.
(That Docker path has not been built or run here.)

## Run locally
```bash
pip install -r requirements.txt
export YOUTUBE_API_KEY=...        # Google Cloud console -> enable "YouTube Data API v3" -> create an API key
python app.py                     # http://127.0.0.1:8000
```
Without a key the site still starts; the landing page says live fetching is off and points to `/workbench`.

Try it **without a key** (fake YouTube API with invented numbers, for development only):
```bash
PORT=8766 python tests/serve_fake.py
```

## Tests
```bash
pip install pytest && python -m pytest -q                       # no key needed; the YouTube layer is a test double
python tests/serve_fake.py &  python tests/e2e_site.py  http://127.0.0.1:8766   # website, in Chromium (Playwright)
python tests/e2e_browser.py http://127.0.0.1:8766                               # the /workbench CSV tool
```
**Fixtures are invented, not recorded.** `tests/yt_fixtures.py` produces API-shaped JSON with made-up numbers, so CI
needs no key. To replace it with real recorded responses, run once with your key:
`YOUTUBE_API_KEY=... python tests/record_fixtures.py @SomeChannel` (saves scrubbed JSON to `tests/fixtures/recorded/`).
One manual live smoke test is still needed before launch (see "Before you go live").

## Deploy (Way 1: GitHub -> Render, visitors need no key)
1. Push this folder to a GitHub repo (GitHub Actions runs the tests).
2. Render: **New -> Blueprint**, pick the repo (`render.yaml` sets everything, with auto-deploy on every push).
3. In the Render dashboard set the secret **`YOUTUBE_API_KEY`**. It is never sent to the browser or logged.
4. Free services sleep when idle, so the first visit takes 30-60 s. All visitors share one daily YouTube quota
   (`YT_DAILY_QUOTA`, default 9000 of Google's 10,000 free units, about 90 analyses; repeats are cached for an hour).

Hugging Face Spaces (Docker) also works: add `YOUTUBE_API_KEY` under Space secrets; the front matter above sets the port.
GitHub Pages alone cannot host this (the key must stay secret and the analysis is Python).

## Environment variables
`YOUTUBE_API_KEY` (secret) · `YT_DAILY_QUOTA` (9000) · `YT_DEFAULT_VIDEOS` (200) · `YT_MAX_VIDEOS` (300) ·
`FETCH_LIMIT_PER_MIN` (4) · `FETCH_LIMIT_PER_HOUR` (20) · `ANALYSIS_TTL_SECONDS` (21600) · `MAX_ANALYSES` (40) ·
`FETCH_CACHE_TTL_SECONDS` (3600) · `SENTIMENT_BACKEND` (lexicon) · `SENTIMENT_MODEL` · `SENTIMENT_MODEL_MAX` (1500) · `TRUST_PROXY=1` (already in the deploy files) · `SCALING_MAX_ROWS` · `MAX_UPLOAD_MB` · `MAX_ROWS` · `PORT` · `HOST`.
Quota and rate limits are counted per process (Render runs one worker; the Hugging Face Dockerfile runs two, so its effective daily cap can be up to double).

## Data rules (from the lecture, enforced in code)
- Views are not reach. Nothing is called reach or "engagement rate on reach"; engagement is per 1,000 **views**.
- Hidden likes and disabled comments are **missing**, never zero. Averages use only videos that have a value.
- Every comparison shows group sizes; groups under 10 videos are flagged, weekday claims need ~30 per day, and the
  models switch off below 40 videos.
- Leakage guard: views, likes, comments and anything built from them are never model inputs; subscribers are constant for one channel, so unused.
- Scaling repeats rows as a Pandas experiment, not evidence. Every report prints the snapshot (fetch time, what was typed, channel ID, units used).
- Only public data. Comment text is fetched only when a visitor presses *Collect* on the Sentiment page; author names, links and IDs are never kept. Results and comments live in memory only and expire.

## Before you go live
- Create the API key and run one real fetch on 3 channels (the code has only been exercised against the test double).
- Run one real comment collection (Sentiment tab) and the labelled accuracy check above; the scorer rules were only tested on invented sentences.
- Check Google's YouTube API Services Terms and make sure the privacy page matches how you deploy.
- Confirm the build on your host (Docker, gunicorn and Render have not been run here).

## Data provenance of the bundled CSV (workbench only)
The CSV comes from the GitHub repo `mrudukp/social-media-sentiment-analysis`, which **has no license**: keep your repo
private or ask the author before publishing it. It looks generated (150 distinct texts, 16 hashtags) and is not verified as
Pakistani-brand data.

## Layout
`app.py` (Flask: pages + API) · `youtube.py` (API client, parsing, normalising) · `comments.py` (collect, clean, language-tag comments) · `sentiment.py` (scoring, summary, accuracy check) · `analysis.py` (pandas / scikit-learn) ·
`report.py` (Markdown report) · `templates/` (site pages) · `static/` (CSS, JS, SVG charts) · `tests/` · `lecture/` · `docs/`.
