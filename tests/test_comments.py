"""Stage A tests: comment collection, cleaning and language tagging. Invented data, no network, no key."""
import os
import sys
import urllib.parse
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import comments as cm  # noqa: E402
import youtube as yt  # noqa: E402

OWN_CH = {"channel_id": "UC" + "a" * 22, "title": "Khaadi", "uploads_playlist": "UU" + "a" * 22}


def comment_item(cid, text, when):
    return {"snippet": {"totalReplyCount": 1, "topLevelComment": {"id": cid, "snippet": {
        "textDisplay": text, "publishedAt": when, "likeCount": 2, "authorDisplayName": "SHOULD NOT BE KEPT"}}}}


def fake_http(disabled=(), quota_after=None):
    calls = {"n": 0, "urls": []}
    own = ["own00000001", "own00000002"]
    pub = [("pub00000001", "Khaadi winter haul review", "UCother1" + "x" * 15),
           ("pub00000002", "Cooking pasta", "UCother2" + "x" * 15),            # unrelated search noise
           ("pub00000003", "Khadi vs Sapphire", "UC" + "a" * 22)]               # brand's own channel
    texts = {
        "own00000001": [("c1", "Bohat acha collection hai, love it", "2026-03-10T10:00:00Z"),
                        ("c2", "The quality is very bad and too expensive", "2026-02-01T10:00:00Z"),
                        ("c3", "Visit my profile for free robux", "2026-03-09T10:00:00Z"),
                        ("c4", "bohat acha collection hai love it!", "2026-03-08T10:00:00Z"),   # repeat of c1
                        ("c5", "یہ بہت اچھا ہے", "2026-03-07T10:00:00Z"),
                        ("c6", "2026-01-01 old", "2025-12-01T10:00:00Z")],
        "own00000002": [],
        "pub00000001": [("c7", "Mehngi hai lekin kapra achi quality ka hai", "2026-03-05T10:00:00Z")],
    }

    def http(url):
        calls["n"] += 1; calls["urls"].append(url)
        if quota_after is not None and calls["n"] > quota_after:
            return 403, {"error": {"errors": [{"reason": "quotaExceeded"}]}}
        u = urllib.parse.urlparse(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        ep = u.path.rsplit("/", 1)[-1]
        if ep == "playlistItems":
            return 200, {"items": [{"contentDetails": {"videoId": v}} for v in own]}
        if ep == "videos":
            return 200, {"items": [{"id": i, "snippet": {"title": f"Own video {i}"}} for i in q["id"].split(",")]}
        if ep == "search":
            return 200, {"items": [{"id": {"videoId": v}, "snippet": {"title": t, "channelId": c,
                                                                       "channelTitle": "Some Reviewer"}} for v, t, c in pub]}
        if ep == "commentThreads":
            vid = q["videoId"]
            if vid in disabled:
                return 403, {"error": {"errors": [{"reason": "commentsDisabled"}]}}
            return 200, {"items": [comment_item(*t) for t in texts.get(vid, [])]}
        return 404, {}
    http.calls = calls
    return http


def run(source="both", http=None, **kw):
    c = yt.YouTubeClient("k", http=http or fake_http())
    return cm.gather_comments(c, "Khaadi", source, channel=OWN_CH, aliases=("khadi",), **kw)


# ----------------------------------------------------------------- language tagging
@pytest.mark.parametrize("text,lang", [
    ("The quality is very good and I love it", "english"),
    ("Bohat acha collection hai", "roman_urdu"),
    ("Kapra mehngi hai but quality is good", "roman_urdu"),      # mixed counts as Roman Urdu
    ("یہ بہت اچھا ہے", "urdu_script"),
    ("🔥🔥🔥", "other"),
    ("", "other"),
    ("Nice", "english"),
])
def test_detect_language(text, lang):
    assert cm.detect_language(text) == lang


# ----------------------------------------------------------------- cleaning
def test_cleaning_rules_and_report():
    r = run("own")
    df, rep = r["df"], r["report"]
    assert set(df["comment_id"]) == {"c1", "c2", "c6"}
    assert rep["dropped_spam_or_links"] == 1 and rep["dropped_repeated_text"] == 1 and rep["dropped_other_language"] == 1
    assert rep["fetched"] == 6 and rep["kept"] == 3
    assert set(df["language"]) == {"english", "roman_urdu"}


def test_no_author_data_is_kept():
    df = run("own")["df"]
    assert not any("author" in c.lower() for c in df.columns)
    assert "SHOULD NOT BE KEPT" not in df.to_string()


# ----------------------------------------------------------------- sources
def test_own_vs_public_vs_both():
    own, pub, both = run("own")["df"], run("public")["df"], run("both")["df"]
    assert set(own["source"]) == {"own"} and set(pub["source"]) == {"public"}
    assert set(pub["comment_id"]) == {"c7"}                      # noise video and the brand's own channel excluded
    assert len(both) == len(own) + len(pub)


def test_date_filter_applies_to_comment_dates():
    r = run("own", date_from=datetime(2026, 3, 1, tzinfo=timezone.utc))
    assert set(r["df"]["comment_id"]) == {"c1"}                  # c2 (Feb) and c6 (2025) are older
    r = run("own", date_from=datetime(2026, 1, 1, tzinfo=timezone.utc), date_to=datetime(2026, 2, 1, tzinfo=timezone.utc))
    assert set(r["df"]["comment_id"]) == {"c2"}                  # to-date is inclusive for that whole day


def test_bad_dates_and_sources_are_refused():
    with pytest.raises(yt.YouTubeError):
        run("own", date_from=datetime(2026, 5, 1, tzinfo=timezone.utc), date_to=datetime(2026, 4, 1, tzinfo=timezone.utc))
    with pytest.raises(yt.YouTubeError):
        run("everything")
    with pytest.raises(yt.YouTubeError):
        cm.gather_comments(yt.YouTubeClient("k", http=fake_http()), "Khaadi", "own")      # no channel given


def test_comments_disabled_video_is_skipped_not_fatal():
    r = run("own", http=fake_http(disabled={"own00000002"}))
    assert r["report"]["videos_comments_disabled"] == 1 and len(r["df"]) == 3


def test_quota_exhaustion_surfaces_clearly():
    with pytest.raises(yt.QuotaExceeded):
        run("both", http=fake_http(quota_after=3))


def test_estimate_units_is_a_worst_case_upper_bound():
    http = fake_http()
    r = run("both", http=http, max_videos=20, max_comments_per_video=200)
    assert r["snapshot"]["api_units_used"] <= cm.estimate_units("both", 20, 200)
    assert cm.estimate_units("own", 20, 200) < cm.estimate_units("public", 20, 200)   # search costs 100 units a page
