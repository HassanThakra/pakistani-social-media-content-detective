"""Stage B tests: sentiment scoring, summary maths, filters, the API and the optional model backend.
Invented comments, no network, no key. The sentences below test that RULES work (negation, "but", emoji). They are
NOT an accuracy measurement: accuracy comes from tests/eval_sentiment.py on comments a person labelled."""
import os
import sys
import urllib.parse

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as appmod  # noqa: E402
import report as rpt  # noqa: E402
import sentiment as sn  # noqa: E402
import yt_fixtures as fx  # noqa: E402
import youtube as yt  # noqa: E402


# ----------------------------------------------------------------- scorer rules
@pytest.mark.parametrize("text,label", [
    ("Bohat acha collection hai, love it", "positive"),
    ("The quality is very bad and too expensive", "negative"),
    ("Mehngi hai lekin kapra achi quality ka hai", "positive"),     # "but" clause carries the verdict
    ("kapra bilkul bekar hai", "negative"),
    ("acha nahi hai", "negative"),                                   # Roman Urdu negation comes AFTER the word
    ("not good at all", "negative"),
    ("not bad", "positive"),
    ("Which lawn is this?", "neutral"),
    ("price kya hai", "neutral"),
    ("😍😍 so pretty", "positive"),
    ("Worst service ever, fraud!!", "negative"),
])
def test_lexicon_rules(text, label):
    assert sn.to_label(sn.lexicon_score(text)) == label


def test_score_is_bounded_and_symmetric():
    big = " ".join(["love amazing perfect"] * 30)
    assert 0.9 < sn.lexicon_score(big) <= 1.0
    assert sn.lexicon_score("love it") == pytest.approx(-sn.lexicon_score("hate it"), abs=0.25)
    assert sn.lexicon_score("") == 0 and sn.lexicon_score(None) == 0


# ----------------------------------------------------------------- summary
def scored_frame():
    rows = []
    def add(i, text, day, source="own", lang="english", likes=0, vid="v1"):
        rows.append({"comment_id": f"c{i}", "video_id": vid, "video_title": f"Video {vid}", "published_at": pd.Timestamp(day),
                     "text": text, "like_count": likes, "reply_count": 0, "source": source, "language": lang,
                     "channel_title": "X"})
    n = 0
    for _ in range(12):
        n += 1; add(n, f"love this design {n}", "2026-03-05", likes=n)
    for _ in range(6):
        n += 1; add(n, f"worst quality, very bad {n}", "2026-03-06", likes=100 + n, vid="v2")
    for _ in range(4):
        n += 1; add(n, f"kya price hai {n}", "2026-04-02", source="public", lang="roman_urdu", vid="v2")
    df = pd.DataFrame(rows)
    return sn.score_frame(df)[0]


def test_summary_counts_and_shares_add_up():
    df = scored_frame()
    s = sn.summarize(df)
    o = s["overall"]
    assert s["n"] == 22 and o["n"] == 22
    assert o["positive"] + o["neutral"] + o["negative"] == pytest.approx(1)
    assert (o["positive"], o["negative"], o["neutral"]) == pytest.approx((12 / 22, 6 / 22, 4 / 22))
    assert o["net"] == pytest.approx((12 - 6) / 22)
    assert {r["group"] for r in s["by_source"]} == {"own", "public"} and sum(r["n"] for r in s["by_source"]) == 22


def test_thin_groups_and_small_n_are_flagged():
    s = sn.summarize(scored_frame())
    assert all(r["few"] for r in s["by_source"] if r["n"] < sn.MIN_BUCKET)
    assert any(t["few"] for t in s["trend"])                       # April has 4 comments
    assert any("Only 22 comments" in w for w in s["warnings"])
    assert any("different crowds" in w for w in s["warnings"])


def test_topics_and_examples_are_ranked_sensibly():
    s = sn.summarize(scored_frame())
    topics = {t["topic"]: t for t in s["topics"]}
    assert topics["Design & collection"]["n"] == 12 and topics["Design & collection"]["net"] == 1.0
    assert topics["Quality & fabric"]["negative"] == 1.0 and topics["Price"]["n"] == 4
    assert s["examples"]["negative"][0]["likes"] == max(e["likes"] for e in s["examples"]["negative"])
    assert all(len(e["text"]) <= 240 for k in s["examples"] for e in s["examples"][k])
    assert "author" not in str(s).lower()


def test_filters_and_empty_selection():
    df = scored_frame()
    assert len(sn.filter_frame(df, source="public")) == 4
    assert len(sn.filter_frame(df, language="roman_urdu")) == 4
    assert len(sn.filter_frame(df, date_from="2026-03-06", date_to="2026-03-06")) == 6        # to-date inclusive
    assert sn.summarize(sn.filter_frame(df, date_from="2027-01-01")) == {"n": 0}


# ----------------------------------------------------------------- model backend (fake pipeline: no download)
class FakePipe:
    def __call__(self, texts, batch_size=32):
        return [[{"label": "positive", "score": 0.8}, {"label": "neutral", "score": 0.1}, {"label": "negative", "score": 0.1}]
                if "good" in t else
                [{"label": "LABEL_0", "score": 0.7}, {"label": "LABEL_1", "score": 0.2}, {"label": "LABEL_2", "score": 0.1}]
                for t in texts]


def test_model_backend_uses_signed_probability_and_both_label_styles():
    df = pd.DataFrame({"text": ["so good", "so so"]})
    out, info = sn.score_frame(df, backend="model", pipe=FakePipe())
    assert info["backend"] == "model" and list(out["sentiment"]) == ["positive", "negative"]
    assert out["score"].iloc[0] == pytest.approx(0.7) and out["score"].iloc[1] == pytest.approx(-0.6)


def test_model_backend_samples_when_too_many(monkeypatch):
    monkeypatch.setattr(sn, "MODEL_MAX", 5)
    out, info = sn.score_frame(pd.DataFrame({"text": ["good"] * 12}), backend="model", pipe=FakePipe())
    assert len(out) == 5 and info["sampled_to"] == 5


def test_model_backend_falls_back_to_lexicon_and_says_so(monkeypatch):
    monkeypatch.setattr(sn, "_load_model", lambda: None)
    sn._model["failed"] = "ImportError: no transformers"
    out, info = sn.score_frame(pd.DataFrame({"text": ["love it", "worst ever"]}), backend="model")
    sn._model["failed"] = None
    assert info["backend"] == "lexicon" and "could not be loaded" in info["note"] and list(out["sentiment"]) == ["positive", "negative"]


# ----------------------------------------------------------------- API
def comment_item(cid, text, when):
    return {"snippet": {"totalReplyCount": 0, "topLevelComment": {"id": cid, "snippet": {
        "textDisplay": text, "publishedAt": when, "likeCount": 3, "authorDisplayName": "SHOULD NOT BE KEPT"}}}}


def http_with_comments(n_videos=120, comments_off=()):
    base = fx.fake_http(n_videos)
    calls = {"comment_calls": 0}

    def http(url):
        u = urllib.parse.urlparse(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        ep = u.path.rsplit("/", 1)[-1]
        if ep == "commentThreads":
            calls["comment_calls"] += 1
            vid = q["videoId"]
            if vid in comments_off:
                return 403, {"error": {"errors": [{"reason": "commentsDisabled"}]}}
            k = vid                                    # unique text per video, or the repeat-text rule would drop rows
            return 200, {"items": [comment_item(f"{vid}-a", f"Bohat acha design hai, love it {k}", "2026-03-10T10:00:00Z"),
                                   comment_item(f"{vid}-b", f"The quality is very bad and too expensive {k}", "2026-02-10T10:00:00Z"),
                                   comment_item(f"{vid}-c", f"Which collection is this {k}?", "2026-03-12T10:00:00Z")]}
        if ep == "search" and q.get("type") == "video":
            return 200, {"items": [{"id": {"videoId": "pub00000001"}, "snippet": {"title": "Test Channel haul review", "channelId": "UCother" + "x" * 17,
                                                                                 "channelTitle": "Reviewer"}}]}
        return base(url)
    http.calls, http.base = calls, base
    return http


@pytest.fixture()
def web():
    appmod.app.config.update(TESTING=True)
    appmod._hits.clear(); appmod._analyses.clear(); appmod._fetch_cache.clear(); appmod._quota.update(day="", used=0)
    state = {"http": http_with_comments(), "key": "test-key"}
    appmod.make_client = lambda: yt.YouTubeClient(state["key"], http=state["http"])
    c = appmod.app.test_client()
    c.state = state
    aid = c.post("/api/youtube/analyze", json={"kind": "handle", "value": "@testchannel", "max_videos": 120}).get_json()["id"]
    c.aid = aid
    appmod._hits.clear()
    return c


def collect(web, **body):
    return web.post(f"/api/analysis/{web.aid}/sentiment/collect", json={"max_videos": 5, "max_comments": 100, **body})


def test_sentiment_page_is_served_and_listed(web):
    r = web.get(f"/analysis/{web.aid}/sentiment")
    assert r.status_code == 200 and b"Sentiment" in r.data and r.headers["X-Robots-Tag"] == "noindex"
    assert "sentiment" in appmod.SECTIONS


def test_not_collected_yet(web):
    assert web.get(f"/api/analysis/{web.aid}/sentiment").get_json() == {"collected": False}


def test_collect_own_scores_and_summarises(web):
    r = collect(web, source="own")
    j = r.get_json()
    assert r.status_code == 200 and j["collected"] is True and j["scoring"]["backend"] == "lexicon"
    s = j["summary"]
    assert s["n"] == 15 and s["overall"]["positive"] == pytest.approx(1 / 3) and s["overall"]["negative"] == pytest.approx(1 / 3)
    assert {x["group"] for x in s["by_language"]} == {"english", "roman_urdu"}
    assert j["collection"]["videos_used"] == 5 and j["params"]["source"] == "own"
    assert "SHOULD NOT BE KEPT" not in r.get_data(as_text=True) and "author" not in r.get_data(as_text=True).lower()


def test_collect_both_keeps_sources_apart(web):
    j = collect(web, source="both", aliases="test channel").get_json()
    assert {x["group"] for x in j["summary"]["by_source"]} == {"own", "public"}


def test_filters_narrow_without_spending_quota(web):
    collect(web, source="own")
    used, calls = appmod._quota["used"], web.state["http"].calls["comment_calls"]
    base = f"/api/analysis/{web.aid}/sentiment"
    assert web.get(base + "?language=english").get_json()["summary"]["n"] == 10
    assert web.get(base + "?date_from=2026-03-01").get_json()["summary"]["n"] == 10          # the February comments drop out
    assert web.get(base + "?date_from=2030-01-01").get_json()["summary"] == {"n": 0}
    assert web.get(base + "?language=klingon").status_code == 400
    assert web.get(base + "?date_from=yesterday").status_code == 400
    assert appmod._quota["used"] == used and web.state["http"].calls["comment_calls"] == calls


def test_collect_validates_input(web):
    assert collect(web, source="everything").status_code == 400
    assert collect(web, date_from="2026-05-01", date_to="2026-04-01").status_code == 400
    assert collect(web, date_from="31/03/2026").status_code == 400
    assert collect(web, max_videos="lots").status_code == 400
    appmod._hits.clear()                                   # validation errors count towards the per-minute limit
    assert web.post("/api/analysis/" + "A" * 16 + "/sentiment/collect", json={}).status_code == 410


def test_collect_limits_are_clamped_and_quota_is_reserved(web):
    j = collect(web, source="own", max_videos=9999, max_comments=999999).get_json()
    assert j["params"]["max_videos"] == 50 and j["params"]["max_comments"] == 1000
    assert appmod._quota["used"] > 0


def test_collect_is_refused_before_spending_when_quota_is_short(web, monkeypatch):
    monkeypatch.setattr(appmod, "YT_DAILY_QUOTA", appmod._quota["used"] + 5)
    r = collect(web, source="public", max_videos=50)
    assert r.status_code == 429 and web.state["http"].calls["comment_calls"] == 0


def test_repeat_collect_uses_the_cache_and_costs_nothing(web):
    collect(web, source="own"); first = web.state["http"].calls["comment_calls"]; used = appmod._quota["used"]
    collect(web, source="own")
    assert web.state["http"].calls["comment_calls"] == first and appmod._quota["used"] == used


def test_comments_off_everywhere_gives_a_clear_empty_result(web):
    web.state["http"] = http_with_comments(comments_off={f"vid{i:08d}" for i in range(120)})
    j = collect(web, source="own").get_json()
    assert j["collected"] is True and j["summary"] == {"n": 0} and j["collection"]["videos_comments_disabled"] == 5
    assert web.get(f"/api/analysis/{web.aid}/sentiment?language=english").get_json()["summary"] == {"n": 0}


def test_rate_limit_applies_to_collection(web):
    codes = [collect(web, source="own").status_code for _ in range(6)]
    assert 400 in codes


def test_report_includes_sentiment_only_when_collected(web):
    before = web.get(f"/api/analysis/{web.aid}/report.md").get_data(as_text=True)
    assert "## 7. Comment sentiment" not in before and "no author names" in before
    appmod._hits.clear()
    collect(web, source="own")
    after = web.get(f"/api/analysis/{web.aid}/report.md").get_data(as_text=True)
    assert "## 7. Comment sentiment" in after and "net sentiment" in after and "SHOULD NOT BE KEPT" not in after


# ----------------------------------------------------------------- measuring accuracy
def test_evaluate_reports_accuracy_baseline_and_confusion(tmp_path, monkeypatch):
    monkeypatch.setattr(sn, "ACCURACY_FILE", str(tmp_path / "acc.json"))
    lab = pd.DataFrame({"text": ["love it", "worst ever", "which lawn is this", "bohat acha", "acha nahi hai", "kya price hai", "nice but late"],
                        "label": ["positive", "negative", "neutral", "positive", "negative", "neutral", " POSITIVE"]})   # last: scorer says negative, the human said positive
    r = sn.evaluate(lab)
    assert r["n"] == 7 and r["accuracy"] == pytest.approx(6 / 7) and r["baseline"] == pytest.approx(3 / 7)  # 3 positive, 2 negative, 2 neutral
    assert r["confusion"]["matrix"][0] == [2, 0, 1] and r["confusion"]["matrix"][1] == [0, 2, 0] and sum(map(sum, r["confusion"]["matrix"])) == 7
    assert any("Only 7 labelled" in c for c in r["caution"]) and {"english", "roman_urdu"} <= set(r["by_language"])
    with pytest.raises(ValueError):
        sn.evaluate(pd.DataFrame({"text": ["x"], "label": ["maybe"]}))


def test_measured_accuracy_is_only_shown_for_the_scorer_that_was_measured(tmp_path, monkeypatch):
    import json
    f = tmp_path / "acc.json"
    f.write_text(json.dumps({"backend": "model", "n": 120, "accuracy": 0.7, "baseline": 0.5, "macro_f1": 0.6, "caution": []}))
    monkeypatch.setattr(sn, "ACCURACY_FILE", str(f))
    df = pd.DataFrame({"text": ["love it"]})
    assert "measured" not in sn.score_frame(df, backend="lexicon")[1]            # measured for a different scorer: not shown
    assert sn.score_frame(df, backend="model", pipe=FakePipe())[1]["measured"]["accuracy"] == 0.7
    f.write_text("not json")
    assert "measured" not in sn.score_frame(df, backend="lexicon")[1]
