"""
Data Detective: YouTube fetcher (official YouTube Data API v3 only).

Quota costs (free quota is about 10,000 units a day):
    search.list        100 units   brand name -> candidate channels
    channels.list        1 unit    channel stats + uploads playlist id
    playlistItems.list   1 unit    per 50 videos
    videos.list          1 unit    per 50 videos

Rules carried over from the lecture:
  * Hidden or disabled counts are MISSING, never zero.
  * Views are not reach. Nothing here is called "reach".
  * The API key stays on the server. It is never logged and never returned.
  * Only public data is fetched. No comment text, no personal data.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd

API_BASE = "https://www.googleapis.com/youtube/v3"
HANDLE_RE = re.compile(r"^@[A-Za-z0-9._-]{3,60}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
DURATION_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")

QUOTA_COSTS = {"search": 100, "channels": 1, "playlistItems": 1, "videos": 1, "commentThreads": 1}
CATEGORY_NAMES = {
    "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music", "15": "Pets & Animals", "17": "Sports",
    "19": "Travel & Events", "20": "Gaming", "22": "People & Blogs", "23": "Comedy", "24": "Entertainment",
    "25": "News & Politics", "26": "Howto & Style", "27": "Education", "28": "Science & Technology",
    "29": "Nonprofits & Activism",
}
MAX_QUERY_LEN = 120
MAX_VIDEOS_HARD = 500
MIN_VIDEOS_FOR_ANALYSIS = 10
MIN_VIDEOS_FOR_MODELS = 40


class YouTubeError(ValueError):
    """A problem the visitor can understand (not found, quota used up, bad input). Safe to show."""


class QuotaExceeded(YouTubeError):
    pass


class CommentsDisabled(YouTubeError):
    """The video's owner turned comments off. Skipped quietly, not an error for the whole run."""


# ----------------------------------------------------------------- input handling
def parse_query(text: str) -> dict:
    """Decide what the visitor typed. Returns {'kind': 'id'|'handle'|'video'|'name', 'value': ...}.

    Nothing here is passed to a shell. Values later go through urllib.parse.urlencode,
    so they cannot change the URL structure.
    """
    q = (text or "").strip()
    if not q:
        raise YouTubeError("Type a YouTube channel (link, @handle or ID) or a brand name.")
    if len(q) > MAX_QUERY_LEN:
        raise YouTubeError(f"That is too long. Keep it under {MAX_QUERY_LEN} characters.")
    if any(ord(ch) < 32 for ch in q):
        raise YouTubeError("That contains characters that are not allowed.")
    if CHANNEL_ID_RE.match(q):
        return {"kind": "id", "value": q}
    if HANDLE_RE.match(q):
        return {"kind": "handle", "value": q}
    if "://" in q or re.match(r"^[\w.-]+\.[A-Za-z]{2,}(/|$)", q):          # looks like a link or a domain
        url = q if re.match(r"^https?://", q, re.I) else "https://" + q
        p = urllib.parse.urlparse(url)
        host = (p.hostname or "").lower()
        if not (host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")):
            raise YouTubeError("Only youtube.com links are accepted. To search by brand, type just the name.")
        parts = [x for x in p.path.split("/") if x]
        if host == "youtu.be" and parts and VIDEO_ID_RE.match(parts[0]):
            return {"kind": "video", "value": parts[0]}
        if parts and parts[0].startswith("@") and HANDLE_RE.match(parts[0]):
            return {"kind": "handle", "value": parts[0]}
        if len(parts) >= 2 and parts[0] == "channel" and CHANNEL_ID_RE.match(parts[1]):
            return {"kind": "id", "value": parts[1]}
        if parts and parts[0] == "watch":
            v = urllib.parse.parse_qs(p.query).get("v", [""])[0]
            if VIDEO_ID_RE.match(v):
                return {"kind": "video", "value": v}
        raise YouTubeError("I could not find a channel in that link. Use a channel link (youtube.com/@name), "
                           "a @handle, or just type the brand name.")
    return {"kind": "name", "value": q}


def parse_duration(iso: str | None) -> float | None:
    """ISO-8601 duration such as PT1H2M10S -> seconds. Live/unknown -> None (missing, not zero)."""
    if not iso:
        return None
    m = DURATION_RE.match(iso)
    if not m:
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return float(d * 86400 + h * 3600 + mi * 60 + s)


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------- HTTP layer
def _default_http(url: str, timeout: float = 15.0) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "data-detective/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https host)
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            body = {}
        return e.code, body
    except (urllib.error.URLError, TimeoutError, OSError):
        raise YouTubeError("Could not reach YouTube just now. Please try again in a minute.")


class YouTubeClient:
    """Thin wrapper. `http` is injectable so tests never touch the network."""

    def __init__(self, api_key: str | None = None, http: Callable[[str], tuple[int, dict]] | None = None):
        self._key = api_key if api_key is not None else os.environ.get("YOUTUBE_API_KEY", "")
        self._http = http or _default_http
        self.units_used = 0

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def _get(self, endpoint: str, **params: Any) -> dict:
        if not self._key:
            raise YouTubeError("This site has no YouTube API key configured yet.")
        qs = urllib.parse.urlencode({**params, "key": self._key})
        status, body = self._http(f"{API_BASE}/{endpoint}?{qs}")
        self.units_used += QUOTA_COSTS.get(endpoint, 1)
        if status == 200:
            return body
        reason = ""
        try:
            reason = body["error"]["errors"][0]["reason"]
        except (KeyError, IndexError, TypeError):
            pass
        if reason == "commentsDisabled":
            raise CommentsDisabled("Comments are turned off for this video.")
        if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
            raise QuotaExceeded("The site's daily YouTube limit has been reached. Please come back tomorrow.")
        if reason in ("keyInvalid", "keyExpired") or status in (400, 403) and "key" in reason.lower():
            raise YouTubeError("The site's YouTube API key is not working. The owner needs to check it.")
        if status == 404 or reason in ("playlistNotFound", "channelNotFound", "videoNotFound"):
            raise YouTubeError("YouTube could not find that.")
        raise YouTubeError("YouTube returned an error. Please try again later.")

    # ---- calls
    def search_channels(self, name: str, max_results: int = 6) -> list[dict]:
        body = self._get("search", part="snippet", type="channel", q=name, maxResults=max_results)
        out = []
        for it in body.get("items", []):
            cid = (it.get("id") or {}).get("channelId")
            sn = it.get("snippet") or {}
            if cid:
                out.append({"channel_id": cid, "title": sn.get("channelTitle") or sn.get("title", ""),
                            "description": (sn.get("description") or "")[:160]})
        return out

    def channel_info(self, query: dict) -> dict:
        key = {"id": "id", "handle": "forHandle"}[query["kind"]]
        body = self._get("channels", part="snippet,statistics,contentDetails", **{key: query["value"]})
        items = body.get("items") or []
        if not items:
            raise YouTubeError("No channel found for that. Check the spelling, or type the brand name instead.")
        it = items[0]
        st, sn = it.get("statistics") or {}, it.get("snippet") or {}
        hidden = bool(st.get("hiddenSubscriberCount"))
        return {
            "channel_id": it["id"],
            "title": sn.get("title", ""),
            "country": sn.get("country"),
            "created": sn.get("publishedAt"),
            "subscribers": None if hidden else _int_or_none(st.get("subscriberCount")),
            "subscribers_hidden": hidden,
            "video_count": _int_or_none(st.get("videoCount")),
            "total_views": _int_or_none(st.get("viewCount")),
            "uploads_playlist": ((it.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads"),
        }

    def video_channel(self, video_id: str) -> str:
        body = self._get("videos", part="snippet", id=video_id)
        items = body.get("items") or []
        if not items:
            raise YouTubeError("No video found for that link.")
        return items[0]["snippet"]["channelId"]

    def upload_ids(self, playlist_id: str, limit: int) -> list[str]:
        ids: list[str] = []
        token = None
        while len(ids) < limit:
            params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50}
            if token:
                params["pageToken"] = token
            body = self._get("playlistItems", **params)
            for it in body.get("items", []):
                vid = (it.get("contentDetails") or {}).get("videoId")
                if vid:
                    ids.append(vid)
            token = body.get("nextPageToken")
            if not token:
                break
        return ids[:limit]

    def video_details(self, ids: list[str]) -> list[dict]:
        rows: list[dict] = []
        for i in range(0, len(ids), 50):
            body = self._get("videos", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]))
            rows.extend(body.get("items", []))
        return rows

    # ---- comments and public search (stage A)
    def search_videos(self, query: str, published_after: str | None = None, published_before: str | None = None,
                      max_results: int = 50) -> list[dict]:
        """Public videos matching `query`. 100 quota units per page of up to 50 results."""
        out: list[dict] = []
        token = None
        max_results = int(max(1, min(max_results, 150)))
        while len(out) < max_results:
            params: dict[str, Any] = {"part": "snippet", "type": "video", "q": query, "order": "relevance",
                                      "maxResults": min(50, max_results - len(out))}
            if published_after:
                params["publishedAfter"] = published_after
            if published_before:
                params["publishedBefore"] = published_before
            if token:
                params["pageToken"] = token
            body = self._get("search", **params)
            for it in body.get("items", []):
                vid = (it.get("id") or {}).get("videoId")
                sn = it.get("snippet") or {}
                if vid:
                    out.append({"video_id": vid, "video_title": sn.get("title", ""),
                                "channel_id": sn.get("channelId", ""), "channel_title": sn.get("channelTitle", ""),
                                "video_published_at": sn.get("publishedAt")})
            token = body.get("nextPageToken")
            if not token:
                break
        return out[:max_results]

    def comment_threads(self, video_id: str, max_comments: int = 200, since: str | None = None) -> list[dict]:
        """Top-level comments, newest first (1 quota unit per 100). Stops early once comments are older than
        `since` (an ISO timestamp). No author names or channel links are kept."""
        rows: list[dict] = []
        token = None
        while len(rows) < max_comments:
            params: dict[str, Any] = {"part": "snippet", "videoId": video_id, "order": "time",
                                      "textFormat": "plainText", "maxResults": 100}
            if token:
                params["pageToken"] = token
            body = self._get("commentThreads", **params)
            stop = False
            for it in body.get("items", []):
                top = ((it.get("snippet") or {}).get("topLevelComment") or {})
                sn = top.get("snippet") or {}
                published = sn.get("publishedAt")
                if since and published and published < since:
                    stop = True
                    continue
                rows.append({"comment_id": top.get("id", ""), "video_id": video_id, "published_at": published,
                             "text": sn.get("textDisplay") or sn.get("textOriginal") or "",
                             "like_count": _int_or_none(sn.get("likeCount")),
                             "reply_count": _int_or_none((it.get("snippet") or {}).get("totalReplyCount"))})
            token = body.get("nextPageToken")
            if stop or not token:
                break
        return rows[:max_comments]


# ----------------------------------------------------------------- normalise
def videos_to_frame(items: list[dict], channel: dict, as_of: datetime | None = None) -> pd.DataFrame:
    """One row per video. Hidden counts become missing (NaN), never 0."""
    recs = []
    for it in items:
        sn, st, cd = it.get("snippet") or {}, it.get("statistics") or {}, it.get("contentDetails") or {}
        title = sn.get("title") or ""
        recs.append({
            "video_id": it.get("id"),
            "published_at": sn.get("publishedAt"),
            "title": title,
            "title_length": len(title),
            "view_count": _int_or_none(st.get("viewCount")),
            "like_count": _int_or_none(st.get("likeCount")),          # absent when the creator hides likes
            "comment_count": _int_or_none(st.get("commentCount")),    # absent when comments are disabled
            "duration_seconds": parse_duration(cd.get("duration")),
            "definition": (cd.get("definition") or "").upper() or None,
            "category": CATEGORY_NAMES.get(str(sn.get("categoryId")), f"Category {sn.get('categoryId')}" if sn.get("categoryId") else None),
            "tag_count": len(sn.get("tags") or []),
            "is_live": (sn.get("liveBroadcastContent") or "none") != "none",
        })
    df = pd.DataFrame.from_records(recs)
    if df.empty:
        raise YouTubeError("That channel has no public videos to analyse.")
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce", utc=True).dt.tz_localize(None)
    for c in ("view_count", "like_count", "comment_count"):
        df[c] = df[c].astype("float64")          # float so missing can be NaN
    df["channel_subscribers"] = float(channel["subscribers"]) if channel.get("subscribers") is not None else float("nan")
    df["channel_title"] = channel.get("title", "")
    df["publish_hour"] = df["published_at"].dt.hour.astype("float64")
    ref = pd.Timestamp((as_of or datetime.now(timezone.utc)).replace(tzinfo=None))
    df["age_days"] = ((ref - df["published_at"]).dt.total_seconds() / 86400).round(1)
    df["publish_weekday"] = df["published_at"].dt.day_name()
    df["is_short"] = df["duration_seconds"].le(60).where(df["duration_seconds"].notna())
    df["format"] = df["is_short"].map({True: "Short (60 s or less)", False: "Standard video"})
    df = df.drop(columns=["is_short"]).sort_values("published_at", ascending=False).reset_index(drop=True)
    return df


def fetch_channel_snapshot(client: YouTubeClient, query: dict, max_videos: int = 200) -> dict:
    """Resolve a channel (id / handle / video link) and fetch its latest uploads.

    Returns {'df', 'channel', 'snapshot'}. `snapshot` is printed in the report because live data
    changes daily: fetch time, what was asked, channel id, quota units spent.
    """
    max_videos = int(max(MIN_VIDEOS_FOR_ANALYSIS, min(max_videos, MAX_VIDEOS_HARD)))
    if query["kind"] == "video":
        query = {"kind": "id", "value": client.video_channel(query["value"])}
    if query["kind"] not in ("id", "handle"):
        raise YouTubeError("Pick a channel first.")
    ch = client.channel_info(query)
    if not ch.get("uploads_playlist"):
        raise YouTubeError("This channel has no public uploads list.")
    ids = client.upload_ids(ch["uploads_playlist"], max_videos)
    if not ids:
        raise YouTubeError("That channel has no public videos to analyse.")
    items = client.video_details(ids)
    now = datetime.now(timezone.utc)
    df = videos_to_frame(items, ch, as_of=now)
    snap = {
        "fetched_at_utc": now.strftime("%Y-%m-%d %H:%M UTC"),
        "query": query["value"],
        "channel_id": ch["channel_id"],
        "channel_title": ch["title"],
        "videos_requested": max_videos,
        "videos_fetched": int(len(df)),
        "channel_video_count": ch.get("video_count"),
        "subscribers": ch.get("subscribers"),
        "subscribers_hidden": ch["subscribers_hidden"],
        "api_units_used": client.units_used,
        "source": "YouTube Data API v3 (public data)",
    }
    return {"df": df, "channel": ch, "snapshot": snap}
