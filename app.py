"""
Data Detective: Project 1 web app (Flask).

Run locally:   python app.py            -> http://127.0.0.1:8000
Production:    gunicorn app:app

The server keeps NO user data on disk. Each request carries the file (or asks for the
bundled real dataset), the result is computed in memory, and a small in-memory cache
(keyed by a hash of the file) avoids repeating work for a few minutes.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import secrets
import threading
import time
from collections import OrderedDict, defaultdict, deque
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

import analysis as an
import comments as cm
import report as rpt
import sentiment as sn
import youtube as yt

# ----------------------------------------------------------------- configuration
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "10"))
MAX_ROWS = int(os.environ.get("MAX_ROWS", "300000"))
SCALING_MAX_ROWS = int(os.environ.get("SCALING_MAX_ROWS", "1000000"))
BUNDLED_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "social_media_sentiment_raw.csv")
BUNDLED_LABEL = "Bundled dataset: social_media_sentiment_raw.csv (mrudukp/social-media-sentiment-analysis)"
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "90"))
HEAVY_LIMIT_PER_MIN = int(os.environ.get("HEAVY_LIMIT_PER_MIN", "12"))
CACHE_SIZE = 4
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "900"))

# YouTube website mode
YT_DEFAULT_VIDEOS = int(os.environ.get("YT_DEFAULT_VIDEOS", "200"))
YT_MAX_VIDEOS = int(os.environ.get("YT_MAX_VIDEOS", "300"))
YT_DAILY_QUOTA = int(os.environ.get("YT_DAILY_QUOTA", "9000"))        # stay under Google's free 10,000 units
FETCH_LIMIT_PER_MIN = int(os.environ.get("FETCH_LIMIT_PER_MIN", "4"))
FETCH_LIMIT_PER_HOUR = int(os.environ.get("FETCH_LIMIT_PER_HOUR", "20"))
ANALYSIS_TTL_SECONDS = int(os.environ.get("ANALYSIS_TTL_SECONDS", str(6 * 3600)))   # shared links expire
MAX_ANALYSES = int(os.environ.get("MAX_ANALYSES", "40"))
FETCH_CACHE_TTL_SECONDS = int(os.environ.get("FETCH_CACHE_TTL_SECONDS", "3600"))
ANALYSIS_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16}$")
SECTIONS = ("overview", "cleaned", "explore", "sentiment", "meaning", "scaling", "models", "report")
SITE_NAME = "Data Detective"

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.config["JSON_SORT_KEYS"] = False
if os.environ.get("TRUST_PROXY") == "1":          # set on Render / Hugging Face so rate limits see the real IP
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
log = logging.getLogger("data-detective")

# ----------------------------------------------------------------- small helpers
_lock = threading.Lock()
_cache: "OrderedDict[str, dict]" = OrderedDict()
_bundled_bytes: bytes | None = None
_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def _client_ip() -> str:
    return request.remote_addr or "unknown"


def rate_limit(kind: str, limit: int, window: int = 60) -> None:
    now = time.time()
    key = (_client_ip(), kind)
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise an.UserError("Too many requests. Please wait a minute and try again." if window <= 60 else
                               "You have used your fetches for this hour. Please try again later, or open one of your earlier results.")
        q.append(now)
        if len(_hits) > 5000:                      # keep memory bounded
            for k in list(_hits)[:1000]:
                _hits.pop(k, None)


def bundled_bytes() -> bytes:
    """The real dataset shipped with the app (read once, then kept in memory)."""
    global _bundled_bytes
    with _lock:
        if _bundled_bytes is None:
            try:
                with open(BUNDLED_CSV, "rb") as f:
                    _bundled_bytes = f.read()
            except OSError:
                raise an.UserError("The bundled dataset file is missing on this server. Upload a CSV instead.")
        return _bundled_bytes


def read_source() -> tuple[bytes, str]:
    """Returns (csv bytes, human label)."""
    source = request.form.get("source", "bundled")
    if source == "bundled":
        return bundled_bytes(), BUNDLED_LABEL
    if source == "upload":
        f = request.files.get("file")
        if f is None or not f.filename:
            raise an.UserError("Choose a CSV file to upload first.")
        data = f.read()
        name = os.path.basename(f.filename)[:80]
        return data, f"Your file: {name}"
    raise an.UserError("Unknown data source.")


def _purge_expired(now: float) -> None:
    """Called with _lock held. Uploaded data never stays in memory longer than CACHE_TTL_SECONDS."""
    for k in [k for k, v in _cache.items() if now - v["t"] > CACHE_TTL_SECONDS]:
        _cache.pop(k, None)


def get_dataset(data: bytes) -> dict:
    key = hashlib.sha256(data).hexdigest()
    with _lock:
        _purge_expired(time.time())
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    raw = an.read_csv_bytes(data, max_rows=MAX_ROWS)
    prof = an.profile(raw)
    clean_df, report = an.clean(raw)
    roles = an.column_roles(clean_df)
    entry = {"raw": raw, "profile": prof, "clean": clean_df, "report": report, "roles": roles,
             "focus_options": an.focus_options(clean_df, roles["groups"]), "t": time.time()}
    with _lock:
        _cache[key] = entry
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return entry


def default_focus(options: dict) -> dict | None:
    """Instagram is the lecture's brand channel; use it when the data has it."""
    for col, values in options.items():
        for v in values:
            if col.lower() == "platform" and v["value"].lower() == "instagram":
                return {"col": col, "val": v["value"]}
    return None


def focused(entry: dict):
    if request.form.get("apply_focus", "1") == "1":
        return an.apply_focus(entry["clean"], request.form.get("focus_col") or None, request.form.get("focus_val") or None)
    return entry["clean"]


# ----------------------------------------------------------------- YouTube helpers
_analyses: "OrderedDict[str, dict]" = OrderedDict()
_fetch_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_quota = {"day": "", "used": 0}


def make_client() -> yt.YouTubeClient:
    """One client per request. Tests replace this to inject a fake HTTP layer."""
    return yt.YouTubeClient()


def reserve_quota(units: int) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _lock:
        if _quota["day"] != today:
            _quota["day"], _quota["used"] = today, 0
        if _quota["used"] + units > YT_DAILY_QUOTA:
            raise yt.QuotaExceeded("The site's daily YouTube limit has been reached. Please come back tomorrow, "
                                   "or open a result you already have.")
        _quota["used"] += units


def settle_quota(estimated: int, actual: int) -> None:
    with _lock:
        _quota["used"] = max(0, _quota["used"] + (actual - estimated))


def _purge_analyses(now: float) -> None:
    for k in [k for k, v in _analyses.items() if now - v["t"] > ANALYSIS_TTL_SECONDS]:
        _analyses.pop(k, None)
    for k in [k for k, v in _fetch_cache.items() if now - v["t"] > FETCH_CACHE_TTL_SECONDS]:
        _fetch_cache.pop(k, None)


def get_analysis(aid: str) -> dict:
    if not ANALYSIS_ID_RE.match(aid or ""):
        raise an.UserError("That result link is not valid.")
    with _lock:
        _purge_analyses(time.time())
        e = _analyses.get(aid)
        if e is not None:
            _analyses.move_to_end(aid)
    if e is None:
        raise Gone("This result has expired or never existed. Results are kept for a few hours. Run the analysis again.")
    return e


class Gone(an.UserError):
    pass


def json_body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def estimate_units(kind: str, n: int) -> int:
    pages = math.ceil(n / 50)
    return 1 + 2 * pages + (1 if kind == "video" else 0)


def new_analysis(result: dict) -> str:
    raw = result["df"]
    clean_df, report = an.clean_youtube(raw)
    entry = {"raw": raw, "clean": clean_df, "report": report, "roles": an.youtube_roles(clean_df),
             "channel": result["channel"], "snapshot": result["snapshot"], "t": time.time(),
             "scaling": None, "models": None, "comments": None}
    aid = secrets.token_urlsafe(12)
    with _lock:
        _purge_analyses(time.time())
        _analyses[aid] = entry
        while len(_analyses) > MAX_ANALYSES:
            _analyses.popitem(last=False)
    return aid


def explore_defaults(roles: dict) -> dict:
    pick = lambda options, prefs: next((p for p in prefs if p in options), options[0] if options else None)  # noqa: E731
    return {"group_col": pick(roles["groups"], ["format", "category", "publish_weekday"]),
            "metric": pick(roles["metrics"], ["view_count", "like_count"]),
            "x": pick(roles["metrics"], ["duration_seconds"]), "y": pick(roles["metrics"], ["view_count"])}


def run_explore_for(entry: dict, args) -> dict:
    roles, df = entry["roles"], entry["clean"]
    d = explore_defaults(roles)
    if not roles["groups"] or not roles["metrics"]:
        raise an.UserError("This channel's data has no category column to compare groups by.")
    try:
        min_n = int(args.get("min_videos", yt.MIN_VIDEOS_FOR_ANALYSIS))
    except ValueError:
        raise an.UserError("Minimum videos must be a whole number.")
    out = an.explore(df, list(df.columns), args.get("group_col") or d["group_col"], args.get("metric") or d["metric"],
                     min_n, args.get("x") or d["x"], args.get("y") or d["y"],
                     roles["dates"][0] if roles["dates"] else None, youtube=True)
    out["options"] = {"groups": roles["groups"], "metrics": roles["metrics"]}
    out["selected"] = {"group_col": args.get("group_col") or d["group_col"], "metric": args.get("metric") or d["metric"],
                       "x": args.get("x") or d["x"], "y": args.get("y") or d["y"]}
    return out


def run_scaling_for(entry: dict, factors: list[int]) -> dict:
    df = entry["clean"]
    group = "format" if "format" in entry["roles"]["groups"] else entry["roles"]["groups"][0]
    metrics = [m for m in ("view_count", "like_count") if m in df.columns]
    out = an.run_scaling(df, group, metrics, factors, SCALING_MAX_ROWS)
    out["channel_note"] = ("One channel is only a few hundred rows, so this is a Pandas experiment on repeated copies, "
                           "not evidence about the channel.")
    entry["scaling"] = out
    return out


# ----------------------------------------------------------------- pages
def page(template: str, **ctx):
    resp = Response(render_template(template, site=SITE_NAME, **ctx))
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/")
def index():
    return page("landing.html", title=f"{SITE_NAME}: analyse any YouTube channel in minutes",
                desc="Type a YouTube channel or brand name. Data Detective fetches the public data, cleans it, "
                     "explores it and tells you what it does and does not show.", active="home")


@app.get("/about")
def about():
    return page("about.html", title=f"About {SITE_NAME}", desc="What Data Detective is, who it is for, and its limits.", active="about")


@app.get("/how-it-works")
def how_it_works():
    return page("how.html", title=f"How {SITE_NAME} works",
                desc="The steps from a channel name to a report: fetch, inspect, clean, explore, interpret, scale, model.", active="how")


@app.get("/privacy")
def privacy():
    return page("privacy.html", title=f"Data and privacy: {SITE_NAME}",
                desc="Only public YouTube data is used. Results are kept in memory for a few hours, then deleted.", active="privacy")


@app.get("/workbench")
def workbench():
    resp = send_from_directory(app.static_folder, "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/analysis/<aid>")
@app.get("/analysis/<aid>/<section>")
def analysis_page(aid, section="overview"):
    if not ANALYSIS_ID_RE.match(aid) or section not in SECTIONS:
        return page("404.html", title="Page not found", desc="", active=""), 404
    resp = page("results.html", title=f"Your analysis: {SITE_NAME}", desc="A shareable analysis of public YouTube data.", active="",
                aid=aid, section=section, sections=SECTIONS)
    resp.headers["X-Robots-Tag"] = "noindex"
    return resp


@app.get("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /analysis/\nDisallow: /api/\n", mimetype="text/plain")


@app.get("/healthz")
def healthz():
    return jsonify(ok=True)


@app.get("/api/config")
def config():
    return jsonify(max_upload_mb=MAX_UPLOAD_MB, max_rows=MAX_ROWS, scaling_max_rows=SCALING_MAX_ROWS,
                   cache_minutes=CACHE_TTL_SECONDS // 60, youtube_enabled=make_client().configured,
                   default_videos=YT_DEFAULT_VIDEOS, max_videos=YT_MAX_VIDEOS,
                   result_hours=round(ANALYSIS_TTL_SECONDS / 3600, 1))


# ----------------------------------------------------------------- API
@app.post("/api/inspect")
def api_inspect():
    rate_limit("api", RATE_LIMIT_PER_MIN)
    data, label = read_source()
    entry = get_dataset(data)
    return jsonify(an.jsonable({"label": label, "profile": entry["profile"]}))


@app.post("/api/clean")
def api_clean():
    rate_limit("api", RATE_LIMIT_PER_MIN)
    data, label = read_source()
    entry = get_dataset(data)
    focus = default_focus(entry["focus_options"])
    sel_col, sel_val = request.form.get("focus_col") or None, request.form.get("focus_val") or None
    if sel_col is None and "focus_col" not in request.form and focus:
        sel_col, sel_val = focus["col"], focus["val"]
    sub = an.apply_focus(entry["clean"], sel_col, sel_val)
    c = entry["clean"]
    return jsonify(an.jsonable({
        "label": label, "report": entry["report"], "roles": entry["roles"],
        "focus_options": entry["focus_options"], "default_focus": focus,
        "focus": {"col": sel_col, "val": sel_val, "rows": int(len(sub)), "of": int(len(c))},
        "columns": list(c.columns), "engagement": an.engagement_columns(c),
    }))


@app.post("/api/explore")
def api_explore():
    rate_limit("api", RATE_LIMIT_PER_MIN)
    data, _ = read_source()
    entry = get_dataset(data)
    df = focused(entry)
    try:
        min_posts = int(request.form.get("min_posts", "30"))
    except ValueError:
        raise an.UserError("Minimum posts must be a whole number.")
    out = an.explore(df, list(entry["clean"].columns), request.form.get("group_col", ""), request.form.get("metric", ""),
                     min_posts, request.form.get("x"), request.form.get("y"), request.form.get("dt_col"))
    return jsonify(an.jsonable(out))


@app.post("/api/scaling")
def api_scaling():
    rate_limit("heavy", HEAVY_LIMIT_PER_MIN)
    data, _ = read_source()
    entry = get_dataset(data)
    try:
        factors = [int(x) for x in request.form.get("factors", "1,10,100").split(",") if x.strip()][:6]
    except ValueError:
        raise an.UserError("Factors must be whole numbers.")
    if not factors or any(f < 1 or f > 100000 for f in factors):
        raise an.UserError("Choose multipliers between 1 and 100000.")
    metrics = [m for m in request.form.get("metrics", "").split(",") if m][:4]
    out = an.run_scaling(entry["clean"], request.form.get("group_col", ""), metrics, factors, SCALING_MAX_ROWS)
    return jsonify(an.jsonable(out))


@app.post("/api/models")
def api_models():
    rate_limit("heavy", HEAVY_LIMIT_PER_MIN)
    data, _ = read_source()
    entry = get_dataset(data)
    return jsonify(an.jsonable(an.run_models(entry["clean"])))


# ----------------------------------------------------------------- YouTube API
@app.post("/api/youtube/resolve")
def yt_resolve():
    """What did the visitor type? A channel (go straight to analysis) or a brand name (pick a channel)."""
    rate_limit("api", RATE_LIMIT_PER_MIN)
    q = yt.parse_query(json_body().get("query", ""))
    client = make_client()
    if not client.configured:
        raise yt.YouTubeError("This site has no YouTube API key configured yet. You can still try the CSV workbench.")
    if q["kind"] != "name":
        return jsonify(mode="direct", query=q)
    rate_limit("fetch", FETCH_LIMIT_PER_MIN)
    reserve_quota(yt.QUOTA_COSTS["search"])
    try:
        cands = client.search_channels(q["value"])
    finally:
        settle_quota(yt.QUOTA_COSTS["search"], client.units_used)
    if not cands:
        raise yt.YouTubeError("No channels found for that name. Try a different spelling, or paste the channel link.")
    return jsonify(mode="pick", query=q, candidates=cands,
                   note="Search returns many channels that mention the name (reviews, fan pages). Pick the brand's own channel.")


@app.post("/api/youtube/analyze")
def yt_analyze():
    rate_limit("fetch", FETCH_LIMIT_PER_MIN)
    rate_limit("fetch-hour", FETCH_LIMIT_PER_HOUR, window=3600)
    body = json_body()
    kind, value = body.get("kind"), str(body.get("value", ""))
    if kind not in ("id", "handle", "video") or not value:
        raise yt.YouTubeError("Pick a channel first.")
    # re-validate whatever the browser sent (a bare 11-character video ID comes from resolve())
    q = {"kind": "video", "value": value} if kind == "video" and yt.VIDEO_ID_RE.match(value) else yt.parse_query(value)
    if q["kind"] not in ("id", "handle", "video"):
        raise yt.YouTubeError("Pick a channel first.")
    try:
        n = int(body.get("max_videos", YT_DEFAULT_VIDEOS))
    except (TypeError, ValueError):
        raise yt.YouTubeError("The number of videos must be a whole number.")
    n = max(yt.MIN_VIDEOS_FOR_ANALYSIS, min(n, YT_MAX_VIDEOS))
    ck = (q["kind"], q["value"].lower() if q["kind"] == "handle" else q["value"], n)
    with _lock:
        _purge_analyses(time.time())
        hit = _fetch_cache.get(ck)
    if hit:
        result = hit["result"]
    else:
        client = make_client()
        if not client.configured:
            raise yt.YouTubeError("This site has no YouTube API key configured yet.")
        est = estimate_units(q["kind"], n)
        reserve_quota(est)
        try:
            result = yt.fetch_channel_snapshot(client, q, n)
        finally:
            settle_quota(est, client.units_used)
        with _lock:
            _fetch_cache[ck] = {"t": time.time(), "result": result}
            while len(_fetch_cache) > 8:
                _fetch_cache.popitem(last=False)
    aid = new_analysis(result)
    return jsonify(id=aid, url=f"/analysis/{aid}/overview", videos=int(len(result["df"])), channel=result["channel"]["title"])


@app.get("/api/analysis/<aid>/overview")
def api_overview(aid):
    rate_limit("api", RATE_LIMIT_PER_MIN)
    e = get_analysis(aid)
    ch = e["channel"]
    return jsonify(an.jsonable({
        "channel": {k: ch.get(k) for k in ("channel_id", "title", "country", "created", "subscribers", "subscribers_hidden",
                                           "video_count", "total_views")},
        "snapshot": e["snapshot"], "overview": an.youtube_overview(e["clean"]),
        "expires_in_minutes": max(0, int((ANALYSIS_TTL_SECONDS - (time.time() - e["t"])) // 60))}))


@app.get("/api/analysis/<aid>/cleaned")
def api_cleaned(aid):
    rate_limit("api", RATE_LIMIT_PER_MIN)
    e = get_analysis(aid)
    prof = an.profile(e["raw"])
    c = e["clean"]
    head = c.head(8).copy()
    head["published_at"] = head["published_at"].astype("string")
    return jsonify(an.jsonable({
        "report": e["report"], "columns": prof["cols"], "issues": prof["issues"],
        "raw_rows": prof["rows"], "head": head.astype(object).where(head.notna(), None).to_dict("records")}))


@app.get("/api/analysis/<aid>/explore")
def api_explore_yt(aid):
    rate_limit("api", RATE_LIMIT_PER_MIN)
    return jsonify(an.jsonable(run_explore_for(get_analysis(aid), request.args)))


# ----------------------------------------------------------------- sentiment (stage B)
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_day(value, label: str) -> datetime | None:
    value = str(value or "").strip()
    if not value:
        return None
    if not _DAY_RE.match(value):
        raise an.UserError(f"{label} must be a date like 2026-03-31.")
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise an.UserError(f"{label} is not a real date.")


def _int_field(body: dict, key: str, default: int, label: str) -> int:
    try:
        return int(body.get(key, default))
    except (TypeError, ValueError):
        raise an.UserError(f"{label} must be a whole number.")


def _empty_comments_frame():
    import pandas as pd
    cols = ["comment_id", "video_id", "published_at", "text", "like_count", "reply_count", "video_title",
            "channel_title", "source", "language", "score", "sentiment"]
    return pd.DataFrame({c: pd.Series(dtype="datetime64[ns]" if c == "published_at" else "object") for c in cols})


def sentiment_view(e: dict, args) -> dict:
    """The collected comments, narrowed by the visitor's filters. Filtering costs no YouTube quota."""
    c = e["comments"]
    if c is None:
        return {"collected": False}
    df = c["df"]
    filt = {"source": args.get("source") or None, "language": args.get("language") or None,
            "date_from": args.get("date_from") or None, "date_to": args.get("date_to") or None}
    if filt["source"] not in (None, "own", "public") or filt["language"] not in (None, "english", "roman_urdu"):
        raise an.UserError("Unknown source or language filter.")
    for k in ("date_from", "date_to"):
        if filt[k] and not _DAY_RE.match(filt[k]):
            raise an.UserError("Dates must look like 2026-03-31.")
    sub = sn.filter_frame(df, **filt)
    available = {"sources": sorted(df["source"].unique().tolist()) if len(df) else [],
             "languages": sorted(df["language"].unique().tolist()) if len(df) else [],
             "first": df["published_at"].min().strftime("%Y-%m-%d") if len(df) else None,
             "last": df["published_at"].max().strftime("%Y-%m-%d") if len(df) else None}
    return {"collected": True, "params": c["params"], "collection": c["report"], "snapshot": c["snapshot"],
            "scoring": c["scoring"], "filters": filt, "available": available, "summary": sn.summarize(sub)}


@app.get("/api/analysis/<aid>/sentiment")
def api_sentiment(aid):
    rate_limit("api", RATE_LIMIT_PER_MIN)
    return jsonify(an.jsonable(sentiment_view(get_analysis(aid), request.args)))


@app.post("/api/analysis/<aid>/sentiment/collect")
def api_sentiment_collect(aid):
    """Fetch public comments (spends YouTube quota), score them, keep them in memory with this analysis."""
    rate_limit("fetch", FETCH_LIMIT_PER_MIN)
    rate_limit("fetch-hour", FETCH_LIMIT_PER_HOUR, window=3600)
    e = get_analysis(aid)
    body = json_body()
    source = body.get("source", "both")
    if source not in cm.SOURCES:
        raise an.UserError("Choose where comments come from: own channel, public videos, or both.")
    mv = max(1, min(_int_field(body, "max_videos", 20, "Videos"), 50))
    mc = max(20, min(_int_field(body, "max_comments", 200, "Comments per video"), 1000))
    d_from, d_to = parse_day(body.get("date_from"), "The start date"), parse_day(body.get("date_to"), "The end date")
    if d_from and d_to and d_from > d_to:
        raise an.UserError("The start date is after the end date.")
    aliases = tuple(a.strip()[:40] for a in str(body.get("aliases", "")).split(",") if a.strip())[:5]
    ch = e["channel"]
    ck = ("comments", ch.get("channel_id"), source, d_from and d_from.date().isoformat(), d_to and d_to.date().isoformat(),
          mv, mc, tuple(a.lower() for a in aliases))
    with _lock:
        _purge_analyses(time.time())
        hit = _fetch_cache.get(ck)
    if hit:
        result = hit["result"]
    else:
        client = make_client()
        if not client.configured:
            raise yt.YouTubeError("This site has no YouTube API key configured yet.")
        est = cm.estimate_units(source, mv, mc)
        reserve_quota(est)
        try:
            result = cm.gather_comments(client, ch["title"], source, channel=ch, aliases=aliases, date_from=d_from,
                                        date_to=d_to, max_videos=mv, max_comments_per_video=mc)
        finally:
            settle_quota(est, client.units_used)
        with _lock:
            _fetch_cache[ck] = {"t": time.time(), "result": result}
            while len(_fetch_cache) > 8:
                _fetch_cache.popitem(last=False)
    if len(result["df"]):
        scored, info = sn.score_frame(result["df"])
    else:
        scored, info = _empty_comments_frame(), {"backend": "lexicon", "note": ""}
    e["comments"] = {"df": scored, "report": result["report"], "snapshot": result["snapshot"], "scoring": info,
                     "params": {"source": source, "max_videos": mv, "max_comments": mc, "aliases": list(aliases),
                                "date_from": d_from and d_from.date().isoformat(), "date_to": d_to and d_to.date().isoformat()}}
    return jsonify(an.jsonable(sentiment_view(e, {})))


@app.get("/api/analysis/<aid>/meaning")
def api_meaning(aid):
    rate_limit("api", RATE_LIMIT_PER_MIN)
    e = get_analysis(aid)
    return jsonify(an.jsonable({"cards": an.insights_youtube(e["clean"]),
                                "videos": int(len(e["clean"])),
                                "always": ["Views are not reach, and nothing here is an engagement rate on reach.",
                                           "Hidden likes and disabled comments are missing, not zero.",
                                           "This is one snapshot of public data. It cannot show causes."]}))


@app.get("/api/analysis/<aid>/scaling")
def api_scaling_yt(aid):
    rate_limit("heavy", HEAVY_LIMIT_PER_MIN)
    e = get_analysis(aid)
    try:
        factors = [int(x) for x in request.args.get("factors", "1,10,100").split(",") if x.strip()][:6]
    except ValueError:
        raise an.UserError("Factors must be whole numbers.")
    if not factors or any(f < 1 or f > 100000 for f in factors):
        raise an.UserError("Choose multipliers between 1 and 100000.")
    return jsonify(an.jsonable(run_scaling_for(e, factors)))


@app.get("/api/analysis/<aid>/models")
def api_models_yt(aid):
    rate_limit("heavy", HEAVY_LIMIT_PER_MIN)
    e = get_analysis(aid)
    e["models"] = an.run_models_youtube(e["clean"])
    return jsonify(an.jsonable(e["models"]))


@app.get("/api/analysis/<aid>/report.md")
def api_report(aid):
    rate_limit("heavy", HEAVY_LIMIT_PER_MIN)
    e = get_analysis(aid)
    if e["scaling"] is None:
        run_scaling_for(e, [1, 10, 100])
    if e["models"] is None:
        e["models"] = an.run_models_youtube(e["clean"])
    ex = run_explore_for(e, {})
    text = rpt.build_report(e, e["scaling"], e["models"], an.jsonable(ex))
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", e["channel"].get("title", "channel"))[:40].strip("-") or "channel"
    resp = Response(text, mimetype="text/markdown; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="data-detective-{safe}.md"'
    return resp


# ----------------------------------------------------------------- errors and headers
@app.errorhandler(Gone)
def gone(e):
    return jsonify(error=str(e)), 410


@app.errorhandler(yt.QuotaExceeded)
def quota_error(e):
    return jsonify(error=str(e), quota=True), 429


@app.errorhandler(yt.YouTubeError)
def youtube_error(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(an.UserError)
def user_error(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(RequestEntityTooLarge)
def too_large(_e):
    return jsonify(error=f"That file is larger than the {MAX_UPLOAD_MB} MB limit on this server."), 413


@app.errorhandler(HTTPException)
def http_error(e):
    if request.path.startswith("/api/"):
        return jsonify(error=e.description or e.name), e.code
    if e.code == 404:
        return page("404.html", title="Page not found", desc="", active=""), 404
    return e


@app.errorhandler(Exception)
def server_error(e):
    log.exception("Unhandled error")
    return jsonify(error="Something went wrong on the server. Please try again, or reload the page."), 500


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")), debug=False)
