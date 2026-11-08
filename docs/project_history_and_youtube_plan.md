# Data Detective: what we did, and the plan to move from CSV to YouTube

Status: **planning only. Nothing in the delivered project has been changed for this plan.**

---

## Part 1. What we did so far

### 1.1 Understanding the assignment
- Read 10 lecture steps (5 screenshots + 5 PDFs): *"Start with a business question, not a Big Data tool."*
- Scenario: a Pakistani clothing brand on Instagram, about 2,000 records, CSV + Colab + Pandas.
- Required flow: question, load/inspect, clean, EDA, **Finding / Evidence / Action / Limitation**, scaling experiment, classification/clustering/regression preview, 10-mark rubric.

### 1.2 Lecture project (delivered)
| File | Purpose |
|---|---|
| `project1_notebook.ipynb` | 25 code cells, runs on the real CSV with 0 failures |
| `scaling_experiment.py` | Repeats rows to see how Pandas behaves as data grows |
| `student_handout.md` | Student-facing instructions |
| `instructor_script.md` | Instructor-only answer key (kept private) |
| `data_dictionary.md` | Instructor copy, verified against the CSV |
| `project1_session_summary.md` | Earlier session summary |

### 1.3 Real-data validation
- Real CSV: 2,260 rows x 13 columns, which becomes **2,200 after cleaning** (60 duplicates removed; 44 were exact, 16 differed only in case or spacing).
- 595 Instagram rows. 8 impossible negative likes were turned into missing, not zero.
- Provenance findings: only **150 distinct post texts and 16 hashtags**, so the data looks generated. It has no license and is not verified as Pakistani brand data.

### 1.4 Deployable web app (delivered as `project1_app.zip`)
- **Backend:** Flask + pandas + scikit-learn (`app.py`, `analysis.py`).
- **Front end:** vanilla JS, 8 tabs, dependency-free SVG charts, light/dark theme, strict CSP, no `innerHTML`.
- **Safety:** upload limit 10 MB, row limit 300k, rate limits, in-memory cache (15 min, max 4 entries).
- **Data rules enforced from the lecture:**
  - never assume columns
  - clean a copy, not the original
  - missing is not zero
  - show group sizes and flag groups with too few posts
  - no weekday claims unless the data supports them
  - repeated rows are a scaling experiment, not evidence
  - leakage guard in models (engagement columns excluded from features)
- **Deployment files:** `requirements.txt`, `Dockerfile` (Hugging Face Spaces), `render.yaml` (Render), GitHub Actions CI, README.
- **Verified here:** 58 pytest tests pass; 69 of 69 Chromium checks pass.
- **Not verified here:** Docker build, gunicorn, Render, Hugging Face, Colab, Python versions other than 3.13.

### 1.5 Known caveats
- The bundled CSV has **no license**. Keep the repo private or ask the author for permission.
- The data looks generated, so findings are about this file only.
- The notebook uses raw follower counts, while the app log-scales skewed features, so their model numbers differ.

---

## Part 2. New goal

> The user types a **YouTube channel or a brand name**. The site fetches the data itself and runs the whole project: inspect, clean, explore, interpret, scale, models, report. **No CSV needed.**

### 2.1 What is and is not possible
| Wanted | Verdict | Notes |
|---|---|---|
| Channel input, such as a handle, URL, or channel ID | **Yes, and cheap** | Uses the official YouTube Data API v3 |
| Brand-name input | **Yes, with noise** | Search returns reviews, fan edits, and unrelated videos, so the user must confirm the channel or videos |
| "Other ads on YouTube" | **No** | There is no public API for ads. Scraping Google's Ads Transparency Center would break its terms. We call the results "videos about the brand," not ads. |
| Instagram from a brand name | **No** | Needs scraping, which violates Meta's terms |

### 2.2 API cost (free quota is about 10,000 units a day)
| Call | Cost | Use |
|---|---|---|
| `search.list` | **100 units** | Brand name to candidate channels or videos |
| `channels.list` | 1 | Channel stats (subscribers, video count) and the "uploads" playlist ID |
| `playlistItems.list` | 1 per 50 videos | List all of a channel's uploads |
| `videos.list` | 1 per 50 videos | Views, likes, comments, duration, publish date |

- **Channel-first design is much cheaper.** One search (100 units) to find the channel, then about 10 units for 200 videos.
- That is roughly **90+ analyses a day** for free, so we cache results.

---

## Part 3. How the project maps onto YouTube data

### 3.1 Column mapping
| Original (Instagram CSV) | YouTube equivalent |
|---|---|
| post_id | video_id |
| timestamp | published_at |
| platform | (constant: YouTube) |
| likes | like_count (can be hidden by the creator, so treat it as missing, not 0) |
| comments | comment_count (can be disabled, so missing) |
| retweets_shares | **no equivalent**; drop |
| followers_count | channel subscriber_count (can be hidden) |
| text / hashtags | title, description, tags |
| sentiment | **not provided**; we would not invent it |
| country | channel country (often blank) |
| new | view_count, duration_seconds, definition, category_id |

### 3.2 The lecture rules still apply
- **Views are not reach.** Show "views," never "reach" or "engagement rate on reach."
- **Engagement per views or per subscribers is not engagement rate.** Label it exactly.
- **Hidden counts are missing, not zero.**
- **Show group sizes.** A channel with 15 videos gets a "too few videos" warning, and models are disabled below a minimum.
- **Models:** leakage guard stays (likes, comments, and views must not be used to predict themselves). Sensible targets are:
  - classification: high vs low engagement per view
  - regression: log views from duration, title length, publish hour, and subscribers
  - clustering: video profiles
- **Scaling experiment:** still valid, but a channel is small (hundreds of videos), so repeated rows are labelled as a Pandas experiment, not evidence.
- **Reproducibility:** live data changes daily, so each analysis stores a **snapshot** (fetch time, query, channel ID) and the report prints it.

---

## Part 4. Build plan (phases)

| # | Phase | What changes | Done when |
|---|---|---|---|
| 0 | **Decisions** | Answer the open questions in Part 6 | Scope agreed |
| 1 | **YouTube fetcher** (`youtube.py`) | Resolve channel (handle, URL, ID, name), page through uploads, batch `videos.list`, normalise to a DataFrame, handle quota and error responses | Works on 3 real channels |
| 2 | **Brand-name flow** | `search.list` returns candidate channels; user picks one (or ticks relevant videos) | User can go name to channel to data |
| 3 | **Backend wiring** | New `source: youtube` (alongside bundled and upload); API key from env var `YOUTUBE_API_KEY`; cache fetched snapshots; per-IP quota guard; clear errors when quota is exhausted | Same `/api/*` routes work with YouTube data |
| 4 | **Analysis adaptation** | Column roles for YouTube fields; engagement-per-view metrics; drop sentiment/country assumptions; adapt model targets; minimum-size gates | Explore and models run without errors |
| 5 | **UI** | Replace the "Load" tab with a search box (channel or brand), candidate picker, fetch progress, and a snapshot banner. Keep upload as fallback. | Full flow works in the browser |
| 6 | **Tests** | Mock the HTTP layer with **recorded real responses** (not invented data) for unit tests; one live smoke test run manually; update the E2E | CI green without a key |
| 7 | **Deploy** | Add `YOUTUBE_API_KEY` as a secret on Render / HF; update README; privacy note | Live URL works |

### 4.1 Security and privacy
- The API key stays **server-side only**. It is never sent to the browser or logged.
- Validate the user's input: accept only handles, URLs, IDs, or plain text. Never pass it to a shell or into a URL unescaped.
- Rate-limit fetches harder than analysis calls, because each costs quota.
- Only public data is used. Do not store comment text or personal data.
- Respect YouTube API Services Terms (do not keep API data for more than the allowed period; link back to videos).

### 4.2 Risks
- **Quota exhaustion** with many users. Mitigations: caching, per-user limits, a friendly "come back tomorrow" message.
- **Noisy brand search.** Mitigation: user confirmation step.
- **Brand channels with few videos or hidden counts.** Mitigation: warnings and gates.
- **Free-tier hosting sleep and memory limits.** The existing row and memory guards stay.
- **I can't test live API calls until you create a key.** I'd build against recorded responses first.

---

## Part 4b. It must be a website, not an app

What we have built is already served as web pages, but it was set up like a tool. The goal is a **public website** that anyone can open from a link in a normal browser, with nothing to install and no files to run.

### Website requirements
- **Public URL** that works on phone and desktop, with no sign-up.
- **Landing page first.** One sentence on what it does, then a big box: *"Enter a YouTube channel or brand name"* and a button. The analysis opens from that box.
- **Guided result pages** instead of the current tool-like tabs: Overview, Cleaned data, Explore, What it means (Finding / Evidence / Action / Limitation), Scaling, Models, Report.
- **Shareable results link** (for example `/analysis/<id>`) so a user can send someone their result. Results expire after a set time because they come from cached snapshots.
- **About / How it works / Data & privacy pages**, including a note that only public YouTube data is used.
- **Clear loading and error states:** "Fetching 200 videos...", "Daily limit reached, try tomorrow", "No channel found."
- **Basic web-site hygiene:** page titles, meta descriptions, a share image, a favicon, accessible contrast, and a keyboard-friendly layout.
- **Report download** (Markdown or PDF) stays.

### Where it can live (free)
The YouTube API key must stay secret, and the analysis uses Python (pandas, scikit-learn). Because of that, **a purely static host like GitHub Pages cannot run it alone.**

| Option | Works? | Notes |
|---|---|---|
| **Render** (website + backend together) | Yes | Recommended. Free tier sleeps when idle, and the first visit is slow. |
| **Hugging Face Spaces** (Docker) | Yes | Free, and sleeps less aggressively. |
| **GitHub Pages** front end + backend on Render | Yes | Two deployments, so more setup. Only worth it if you want a GitHub-hosted address. |
| **GitHub Pages only** | **No** | Would expose the API key or lose the Python analysis. |

Recommendation: keep one Flask service that serves the website and the API, and put it on Render, with a Hugging Face copy as a backup. You can add a custom domain later.

### "Deployable using GitHub": two real ways

**Way 1. GitHub repo, auto-deployed to Render (recommended).**
- You push the code to GitHub. Render watches the repo and redeploys on every push.
- GitHub Actions runs the tests first (already set up).
- The YouTube key is stored as a secret in Render, so visitors never see it and don't need their own key.
- Trade-off: the free tier sleeps, and the shared key's daily quota (about 90 analyses) is used up by all visitors together.

**Way 2. Fully static site on GitHub Pages, deployed by GitHub Actions.**
- The site runs entirely in the visitor's browser. No server at all, so it is free and never sleeps.
- Each visitor **pastes their own free YouTube API key**, stored only in their browser, so each person has their own quota.
- The analysis has to run in the browser. Two ways:
  - **Pyodide:** pandas and scikit-learn run in the browser. This reuses most of the Python code, but the first load downloads tens of MB and is slow on phones.
  - **Rewrite the analysis in JavaScript:** faster and lighter, but a large rewrite, and the models would need a JS library.
- Trade-off: visitors must get an API key, which many non-technical users won't do. That conflicts with "people just type a brand name."

| | Way 1: Render | Way 2: GitHub Pages |
|---|---|---|
| Visitor needs a key | No | **Yes** |
| Runs existing Python | Yes | Only through Pyodide, or after a rewrite |
| Cold-start delay | ~30-60 s | None |
| Shared quota limit | Yes | No (per visitor) |
| Setup effort | Low | High |

My suggestion: **Way 1** for the public site, since it is the only one where people truly just type a name. I could add Way 2 later as an "enter your own key" mode if the shared quota runs out.

### Phase added to the build plan
| # | Phase | Done when |
|---|---|---|
| 5a | **Website shell:** landing page, multi-page navigation, About / Privacy pages, responsive design, SEO basics | The site looks and works like a website on a phone |
| 5b | **Shareable results:** analysis ID, expiry, results page | A pasted link opens the same result for a limited time |

---

## Part 5. What stays and what goes
- **Stays:** cleaning rules, group-size flags, the Finding/Evidence/Action/Limitation notes, scaling experiment, report download, security headers, deployment files, CSV upload as a fallback.
- **Changes:** loading tab, column roles, model targets, tests.
- **Goes (or becomes optional):** the bundled CSV as the default source. It can stay as a "sample dataset" option.

---

## Part 6. Open questions for you
1. **YouTube only,** or keep CSV upload and the bundled dataset as fallback options?
2. **Input:** channel only, brand name only, or both? (I recommend both, with the channel path as the cheap route.)
3. Can you **create a free Google Cloud API key** (YouTube Data API v3)? I can't create one for you.
4. Should the user **confirm which results belong to the brand**, or should it be fully automatic?
5. Is this still graded against the **lecture rubric**, or is it becoming a standalone product? That decides how much of the lecture structure (4-part notes, scaling, models) we keep.
6. How many videos to fetch per run (for example, the latest 200)? More videos means more quota and slower analysis.
7. **Hosting way:** Way 1 (GitHub repo auto-deployed to Render; visitors need no key) or Way 2 (static GitHub Pages; visitors paste their own key)? I recommend Way 1.
8. **Website details:** do you want shareable result links, a custom domain later, and a name for the site? (The current name is "Data Detective".)

---

## Part 7. Suggested next step
Answer the questions in Part 6. Then I start with **Phase 1 (the fetcher)** using recorded responses, so you can see real YouTube columns flow through the existing analysis before the UI is rewritten.
