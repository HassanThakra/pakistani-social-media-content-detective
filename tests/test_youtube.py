"""Tests for the YouTube fetcher, the website routes and the YouTube analysis rules.
The HTTP layer is a test double (tests/yt_fixtures.py): no network and no API key needed."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analysis as an  # noqa: E402
import app as appmod  # noqa: E402
import yt_fixtures as fx  # noqa: E402
import youtube as yt  # noqa: E402


def client_for(http, key="test-key"):
    return yt.YouTubeClient(key, http=http)


@pytest.fixture()
def web():
    appmod.app.config.update(TESTING=True)
    appmod._hits.clear()
    appmod._analyses.clear()
    appmod._fetch_cache.clear()
    appmod._quota.update(day="", used=0)
    state = {"http": fx.fake_http(120), "key": "test-key"}
    appmod.make_client = lambda: yt.YouTubeClient(state["key"], http=state["http"])
    c = appmod.app.test_client()
    c.state = state
    return c


def analyse(web, **body):
    body = {"kind": "handle", "value": "@testchannel", "max_videos": 120, **body}
    return web.post("/api/youtube/analyze", json=body)


# ---------------------------------------------------------------- input parsing
@pytest.mark.parametrize("text,kind,value", [
    ("@MyBrand", "handle", "@MyBrand"),
    ("https://www.youtube.com/@MyBrand", "handle", "@MyBrand"),
    ("youtube.com/@MyBrand/videos", "handle", "@MyBrand"),
    ("UC" + "a" * 22, "id", "UC" + "a" * 22),
    ("https://www.youtube.com/channel/UC" + "a" * 22, "id", "UC" + "a" * 22),
    ("https://youtu.be/abcdefghijk", "video", "abcdefghijk"),
    ("https://www.youtube.com/watch?v=abcdefghijk&t=3", "video", "abcdefghijk"),
    ("Lawrencepur fabrics", "name", "Lawrencepur fabrics"),
])
def test_parse_query(text, kind, value):
    assert yt.parse_query(text) == {"kind": kind, "value": value}


@pytest.mark.parametrize("bad", ["", "   ", "x" * 200, "a\x00b", "https://evil.example/@MyBrand",
                                 "https://youtube.com.evil.example/@MyBrand", "https://www.youtube.com/feed/trending"])
def test_parse_query_rejects(bad):
    with pytest.raises(yt.YouTubeError):
        yt.parse_query(bad)


def test_query_is_urlencoded_not_concatenated():
    http = fx.fake_http(60)
    client_for(http).search_channels("a&key=EVIL&part=x#frag")
    url = http.calls["urls"][0]
    assert "q=a%26key%3DEVIL%26part%3Dx%23frag" in url and url.count("key=") == 1


def test_parse_duration():
    assert yt.parse_duration("PT1H2M10S") == 3730 and yt.parse_duration("PT45S") == 45
    assert yt.parse_duration("P1DT1H") == 90000 and yt.parse_duration(None) is None and yt.parse_duration("nonsense") is None


# ---------------------------------------------------------------- fetcher
def test_snapshot_columns_and_missing_not_zero():
    r = yt.fetch_channel_snapshot(client_for(fx.fake_http(120)), yt.parse_query("@testchannel"), 120)
    df, snap = r["df"], r["snapshot"]
    assert len(df) == 120 and snap["videos_fetched"] == 120 and snap["api_units_used"] == 7
    assert df["like_count"].isna().sum() == 14 and df["comment_count"].isna().sum() == 10      # hidden -> NaN
    assert (df["like_count"].dropna() >= 0).all() and not (df["like_count"] == 0).all()
    assert df["published_at"].is_monotonic_decreasing and "retweets_shares" not in df and "sentiment" not in df
    assert snap["channel_id"] == fx.CHANNEL_ID and "fetched_at_utc" in snap


def test_hidden_subscribers_are_missing():
    r = yt.fetch_channel_snapshot(client_for(fx.fake_http(60, subscribers=None)), yt.parse_query("@testchannel"), 60)
    assert r["snapshot"]["subscribers_hidden"] is True and r["snapshot"]["subscribers"] is None
    assert r["df"]["channel_subscribers"].isna().all()


def test_paging_and_batching():
    http = fx.fake_http(120)
    r = yt.fetch_channel_snapshot(client_for(http), yt.parse_query("@testchannel"), 120)
    eps = [u.split("?")[0].rsplit("/", 1)[-1] for u in http.calls["urls"]]
    assert eps.count("playlistItems") == 3 and eps.count("videos") == 3 and eps.count("search") == 0
    assert r["df"]["video_id"].is_unique


def test_error_mapping():
    with pytest.raises(yt.QuotaExceeded):
        yt.fetch_channel_snapshot(client_for(fx.fake_http(60, quota_after=1)), yt.parse_query("@testchannel"), 60)
    with pytest.raises(yt.YouTubeError, match="No channel found"):
        yt.fetch_channel_snapshot(client_for(fx.fake_http(60, missing_channel=True)), yt.parse_query("@testchannel"), 60)
    with pytest.raises(yt.YouTubeError, match="no YouTube API key"):
        yt.YouTubeClient("", http=fx.fake_http(60)).channel_info({"kind": "handle", "value": "@x"})
    with pytest.raises(yt.YouTubeError, match="Could not reach"):
        def boom(url):
            raise yt.YouTubeError("Could not reach YouTube just now. Please try again in a minute.")
        yt.fetch_channel_snapshot(client_for(boom), yt.parse_query("@testchannel"), 60)


def test_api_key_never_in_snapshot_or_results():
    r = yt.fetch_channel_snapshot(client_for(fx.fake_http(60), key="SECRET-KEY-123"), yt.parse_query("@testchannel"), 60)
    assert "SECRET-KEY-123" not in repr(r["snapshot"]) and "SECRET-KEY-123" not in repr(r["channel"])


# ---------------------------------------------------------------- analysis rules
def _clean(n=120):
    r = yt.fetch_channel_snapshot(client_for(fx.fake_http(n)), yt.parse_query("@testchannel"), n)
    return an.clean_youtube(r["df"])


def test_clean_keeps_missing_and_adds_per_view_measures():
    c, rep = _clean()
    assert c["like_count"].isna().sum() == 14 and rep["rows_after"] == 120
    ok = c.dropna(subset=["like_count", "comment_count"]).iloc[0]
    assert abs(ok["engagement_per_1k_views"] - (ok["like_count"] + ok["comment_count"]) / ok["view_count"] * 1000) < 1e-9
    hidden = c[c["like_count"].isna()]
    assert hidden["likes_per_1k_views"].isna().all() and hidden["engagement_per_1k_views"].isna().all()
    assert "reach" not in " ".join(s["title"] + s["detail"] for s in rep["steps"]).replace("not an engagement rate on reach", "")


def test_negative_counts_become_missing():
    r = yt.fetch_channel_snapshot(client_for(fx.fake_http(60)), yt.parse_query("@testchannel"), 60)
    df = r["df"]
    df.loc[3, "view_count"] = -5
    c, rep = an.clean_youtube(df)
    assert pd_isna(c.loc[3, "view_count"]) and rep["negatives_to_missing"] == {"view_count": 1}


def pd_isna(v):
    return v != v


def test_explore_youtube_warns_views_are_not_reach_and_small_weekdays():
    c, _ = _clean()
    out = an.explore(c, list(c.columns), "format", "view_count", 10, "duration_seconds", "view_count", "published_at", youtube=True)
    text = " ".join(out["warnings"]).lower()
    assert "views are not reach" in text and "fewer than 30 videos" in text and "newer videos" in text


def test_small_group_is_flagged():
    c, _ = _clean(60)
    out = an.explore(c, list(c.columns), "category", "view_count", 30, None, None, None, youtube=True)
    assert any(r["too_few"] for r in out["group"]["rows"]) and "fewer than 30 videos" in out["warnings"][0]


def test_insights_never_claim_best_day_without_enough_data():
    c, _ = _clean()
    cards = {x["title"]: x for x in an.insights_youtube(c)}
    assert cards["Best day to post"]["finding"] == "No best-day claim is made." and cards["Best day to post"]["strength"] == "weak"
    for x in cards.values():
        assert {"finding", "evidence", "action", "limitation"} <= set(x)
        assert "reach" not in x["finding"].lower().replace("not reach", "")


def test_insights_gate_on_tiny_channels():
    c, _ = _clean(10)
    c = c.head(6)
    cards = an.insights_youtube(c)
    assert len(cards) == 1 and "Too few" in cards[0]["title"]


def test_models_gate_and_leakage_guard():
    c, _ = _clean(120)
    m = an.run_models_youtube(c)
    assert m["available"] and not (set(m["features"]) & an.YT_LEAK)
    assert all(not f.startswith(("view_count", "like_count", "comment_count", "engagement", "likes_per")) for f in m["features"])
    assert "channel_subscribers" not in m["features"]
    assert m["regression"]["mae_baseline"] > 0 and 0 <= m["classification"]["baseline"] <= 1
    small = an.run_models_youtube(_clean(30)[0])
    assert small["available"] is False and "at least 40" in small["reason"]


# ---------------------------------------------------------------- website
def test_pages_render_with_seo_basics(web):
    for path, needle in [("/", "Type a YouTube channel"), ("/about", "About Data Detective"),
                         ("/how-it-works", "How it works"), ("/privacy", "Data and privacy")]:
        r = web.get(path)
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and needle in html and "<title>" in html and 'name="description"' in html
        assert 'property="og:image"' in html and "favicon.svg" in html and 'lang="en"' in html and "Skip to content" in html
    assert web.get("/nope").status_code == 404 and web.get("/analysis/short").status_code == 404
    assert "Disallow: /analysis/" in web.get("/robots.txt").get_data(as_text=True)


def test_workbench_still_serves_the_csv_tool(web):
    r = web.get("/workbench")
    assert r.status_code == 200 and b"Load &amp; inspect" in r.data


def test_csp_blocks_inline_script_on_every_page(web):
    for path in ("/", "/about", "/workbench"):
        csp = web.get(path).headers["Content-Security-Policy"]
        assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    html = web.get("/").get_data(as_text=True)
    assert "<script>" not in html and "onclick=" not in html


def test_config_reports_key_status_without_leaking_it(web):
    cfg = web.get("/api/config").get_json()
    assert cfg["youtube_enabled"] is True and "test-key" not in str(cfg)
    web.state["key"] = ""
    assert web.get("/api/config").get_json()["youtube_enabled"] is False
    assert web.post("/api/youtube/resolve", json={"query": "@x"}).status_code == 400


def test_resolve_direct_vs_brand_name_candidates(web):
    d = web.post("/api/youtube/resolve", json={"query": "https://www.youtube.com/@MyBrand"}).get_json()
    assert d["mode"] == "direct" and d["query"] == {"kind": "handle", "value": "@MyBrand"}
    n = web.post("/api/youtube/resolve", json={"query": "My Brand"}).get_json()
    assert n["mode"] == "pick" and n["candidates"][0]["channel_id"] == fx.CHANNEL_ID and len(n["candidates"][0]["description"]) <= 160
    assert web.post("/api/youtube/resolve", json={"query": ""}).status_code == 400


def test_full_flow_and_shareable_link(web):
    r = analyse(web)
    j = r.get_json()
    assert r.status_code == 200 and j["videos"] == 120 and j["url"] == f"/analysis/{j['id']}/overview"
    aid = j["id"]
    ov = web.get(f"/api/analysis/{aid}/overview").get_json()
    assert ov["overview"]["videos"] == 120 and ov["overview"]["likes_hidden"] == 14 and ov["snapshot"]["channel_id"] == fx.CHANNEL_ID
    assert ov["overview"]["top_videos"][0]["views"] >= ov["overview"]["top_videos"][-1]["views"]
    assert "test-key" not in web.get(f"/api/analysis/{aid}/overview").get_data(as_text=True)
    for sec in ("overview", "cleaned", "explore", "meaning", "scaling", "models", "report"):
        page = web.get(f"/analysis/{aid}/{sec}")
        assert page.status_code == 200 and page.headers["X-Robots-Tag"] == "noindex"
    assert web.get(f"/analysis/{aid}/bogus").status_code == 404
    assert web.get(f"/api/analysis/{aid}/cleaned").get_json()["report"]["rows_after"] == 120
    ex = web.get(f"/api/analysis/{aid}/explore?group_col=category&metric=like_count&min_videos=5").get_json()
    assert ex["group"]["group_col"] == "category" and ex["group"]["metric"] == "like_count" and ex["group"]["min_posts"] == 5
    assert web.get(f"/api/analysis/{aid}/explore?group_col=title&metric=view_count").status_code == 400
    assert web.get(f"/api/analysis/{aid}/meaning").get_json()["cards"]
    sc = web.get(f"/api/analysis/{aid}/scaling?factors=1,10").get_json()
    assert [x["status"] for x in sc["results"]] == ["ok", "ok"] and "not new real-world evidence" in sc["note"]
    assert web.get(f"/api/analysis/{aid}/scaling?factors=0").status_code == 400
    assert web.get(f"/api/analysis/{aid}/models").get_json()["available"] is True


def test_report_download(web):
    aid = analyse(web).get_json()["id"]
    r = web.get(f"/api/analysis/{aid}/report.md")
    text = r.get_data(as_text=True)
    assert r.status_code == 200 and r.mimetype == "text/markdown" and "attachment" in r.headers["Content-Disposition"]
    for part in ("## 1. Data snapshot", "Fetched:", fx.CHANNEL_ID, "## 4. What it means: Finding / Evidence / Action / Limitation",
                 "- **Finding:**", "- **Limitation:**", "## 5. Scaling experiment", "## 6. Models preview", "views are not reach"):
        assert part in text, part
    assert "test-key" not in text


def test_expired_and_invalid_links(web, monkeypatch=None):
    aid = analyse(web).get_json()["id"]
    appmod._analyses[aid]["t"] -= appmod.ANALYSIS_TTL_SECONDS + 5
    r = web.get(f"/api/analysis/{aid}/overview")
    assert r.status_code == 410 and "expired" in r.get_json()["error"]
    assert web.get("/api/analysis/AAAAAAAAAAAAAAAA/overview").status_code == 410
    assert web.get("/api/analysis/not-valid/overview").status_code == 400


def test_repeat_fetch_is_cached_and_costs_no_quota(web):
    analyse(web)
    used = appmod._quota["used"]
    calls = web.state["http"].calls["n"]
    a, b = analyse(web).get_json(), analyse(web).get_json()
    assert web.state["http"].calls["n"] == calls and appmod._quota["used"] == used and a["id"] != b["id"]


def test_daily_quota_guard_and_friendly_message(web):
    appmod.YT_DAILY_QUOTA, old = 5, appmod.YT_DAILY_QUOTA
    try:
        r = analyse(web)
        assert r.status_code == 429 and r.get_json()["quota"] is True and "tomorrow" in r.get_json()["error"]
    finally:
        appmod.YT_DAILY_QUOTA = old
    web.state["http"] = fx.fake_http(120, quota_after=0)
    r = analyse(web)
    assert r.status_code == 429 and "tomorrow" in r.get_json()["error"]


def test_fetch_rate_limit(web):
    codes = [analyse(web, value="@testchannel").status_code for _ in range(appmod.FETCH_LIMIT_PER_MIN + 2)]
    assert codes[: appmod.FETCH_LIMIT_PER_MIN] == [200] * appmod.FETCH_LIMIT_PER_MIN and codes[-1] == 400


def test_analyze_validates_input(web):
    for body in ({"kind": "name", "value": "Brand"}, {"kind": "handle", "value": ""}, {"kind": "handle", "value": "not a handle!"},
                 {"kind": "id", "value": "https://evil.example"}, {}):
        assert web.post("/api/youtube/analyze", json=body).status_code == 400, body
    assert web.post("/api/youtube/analyze", data="junk", content_type="text/plain").status_code == 400
    assert analyse(web, max_videos="abc").status_code == 400


def test_video_link_resolves_to_its_channel(web):
    r = web.post("/api/youtube/analyze", json={"kind": "video", "value": "abcdefghijk", "max_videos": 60})
    assert r.status_code == 200 and r.get_json()["channel"] == "Test Channel"


def test_analyses_are_bounded(web):
    appmod.MAX_ANALYSES, old = 3, appmod.MAX_ANALYSES
    try:
        appmod._hits.clear()
        for _ in range(5):
            appmod._hits.clear()
            analyse(web)
        assert len(appmod._analyses) == 3
    finally:
        appmod.MAX_ANALYSES = old
