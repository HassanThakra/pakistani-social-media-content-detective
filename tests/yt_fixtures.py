"""
Test double for the YouTube Data API v3. NO network.

IMPORTANT: these numbers are INVENTED and exist only so the plumbing can be tested in CI
without an API key. They have the same JSON *shape* as the real API, nothing more.
Nothing here is ever shown to a visitor.

To use REAL recorded responses instead, run (once, with your key):
    YOUTUBE_API_KEY=... python tests/record_fixtures.py @SomeChannel
That writes tests/fixtures/recorded/*.json, and fake_http() prefers those files when present.
"""
from __future__ import annotations

import json
import os
import urllib.parse
from datetime import datetime, timedelta, timezone

import numpy as np

RECORDED = os.path.join(os.path.dirname(__file__), "fixtures", "recorded")
CHANNEL_ID = "UC" + "a" * 22
UPLOADS = "UU" + "a" * 22


def _iso_dur(sec: int) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return "PT" + (f"{h}H" if h else "") + (f"{m}M" if m else "") + f"{s}S"


def make_videos(n: int = 120, seed: int = 7, hide_likes_every: int = 9, comments_off_every: int = 13) -> list[dict]:
    rng = np.random.default_rng(seed)
    base = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    items = []
    for i in range(n):
        short = i % 4 == 0
        dur = int(rng.integers(15, 60)) if short else int(rng.integers(180, 1500))
        views = int(rng.lognormal(8.5 if not short else 8.9, 1.1))
        st = {"viewCount": str(views)}
        if i % hide_likes_every != 0:
            st["likeCount"] = str(int(views * rng.uniform(0.01, 0.06)))
        if i % comments_off_every != 0:
            st["commentCount"] = str(int(views * rng.uniform(0.0005, 0.004)))
        pub = base - timedelta(days=int(i * 3 + rng.integers(0, 3)), hours=int(rng.integers(0, 24)))
        items.append({
            "id": f"v{i:010d}"[-11:].replace("0", "A") if False else ("vid" + f"{i:08d}"),
            "snippet": {"publishedAt": pub.strftime("%Y-%m-%dT%H:%M:%SZ"), "title": f"Video number {i} {'short' if short else 'long'}",
                        "categoryId": "22" if i % 3 else "24", "tags": ["a"] * int(rng.integers(0, 8)),
                        "liveBroadcastContent": "none"},
            "statistics": st,
            "contentDetails": {"duration": _iso_dur(dur), "definition": "hd"},
        })
    return items


# ---- invented comments, only for the fake server and browser checks (never shown to a real visitor)
_PHRASES = [
    ("Bohat acha collection hai, love it", 3), ("Zabardast design, mashallah", 3), ("Beautiful colours and great quality", 3),
    ("Love the new prints, so pretty", 3), ("Kapra bilkul bekar hai, bohat mehngi", 2), ("The quality is very bad and too expensive", 2),
    ("Worst delivery ever, still no refund", 2), ("Size chart is wrong, very disappointed", 1), ("Price kya hai?", 2),
    ("Which lawn is this", 2), ("New arrivals kab aayengi", 1), ("Mehngi hai lekin kapra achi quality ka hai", 2),
    ("Not good at all, stitching is poor", 1), ("Outlet in Lahore ka address?", 1), ("Amazing collection, thank you", 2),
]


def make_comments(video_id: str, n: int = 120, seed: int = 11) -> list[dict]:
    rng = np.random.default_rng(abs(hash(video_id)) % (2**32) + seed)
    weights = np.array([w for _, w in _PHRASES], dtype=float)
    weights /= weights.sum()
    base = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        text = _PHRASES[int(rng.choice(len(_PHRASES), p=weights))][0] + f" #{video_id[-4:]}-{i}"      # unique, so repeats are not dropped
        when = base - timedelta(days=int(rng.integers(0, 240)), hours=int(rng.integers(0, 24)))
        out.append({"snippet": {"totalReplyCount": int(rng.integers(0, 3)), "topLevelComment": {"id": f"{video_id}-c{i}", "snippet": {
            "textDisplay": text, "publishedAt": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "likeCount": int(rng.integers(0, 40))}}}})
    out.sort(key=lambda it: it["snippet"]["topLevelComment"]["snippet"]["publishedAt"], reverse=True)
    return out


def fake_http(n_videos: int = 120, subscribers: str | None = "12345", quota_after: int | None = None,
              missing_channel: bool = False):
    """Returns an http(url) -> (status, json) callable that mimics the four endpoints we use."""
    videos = make_videos(n_videos)
    calls = {"n": 0, "urls": []}

    def http(url: str):
        calls["n"] += 1
        calls["urls"].append(url)
        if quota_after is not None and calls["n"] > quota_after:
            return 403, {"error": {"errors": [{"reason": "quotaExceeded"}]}}
        u = urllib.parse.urlparse(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        ep = u.path.rsplit("/", 1)[-1]
        if ep == "channels":
            if missing_channel:
                return 200, {"items": []}
            stats = {"videoCount": str(n_videos), "viewCount": "999999"}
            if subscribers is None:
                stats["hiddenSubscriberCount"] = True
            else:
                stats["subscriberCount"] = subscribers
            return 200, {"items": [{"id": CHANNEL_ID, "snippet": {"title": "Test Channel", "country": "PK",
                                                                "publishedAt": "2020-01-01T00:00:00Z"},
                                    "statistics": stats,
                                    "contentDetails": {"relatedPlaylists": {"uploads": UPLOADS}}}]}
        if ep == "commentThreads":
            return 200, {"items": make_comments(q["videoId"])}
        if ep == "search" and q.get("type") == "video":
            return 200, {"items": [{"id": {"videoId": f"pub{j:08d}"}, "snippet": {"title": f"Test Channel haul review {j}", "channelId": "UC" + "z" * 22,
                                                                                 "channelTitle": "A Reviewer"}} for j in range(8)]}
        if ep == "search":
            return 200, {"items": [{"id": {"channelId": CHANNEL_ID},
                                    "snippet": {"channelTitle": "Test Channel", "description": "x" * 300}}]}
        if ep == "playlistItems":
            start = int(q.get("pageToken", "0") or 0)
            page = videos[start:start + 50]
            body = {"items": [{"contentDetails": {"videoId": v["id"]}} for v in page]}
            if start + 50 < len(videos):
                body["nextPageToken"] = str(start + 50)
            return 200, body
        if ep == "videos":
            ids = q["id"].split(",")
            by = {v["id"]: v for v in videos}
            if q.get("part") == "snippet" and len(ids) == 1:
                return 200, {"items": [{"id": ids[0], "snippet": {"channelId": CHANNEL_ID}}]}
            return 200, {"items": [by[i] for i in ids if i in by]}
        return 404, {}

    http.calls = calls
    return http
