"""Stage A: collect public YouTube comments about a brand, clean them, tag their language.

Sources (the visitor chooses):
  own     - comments on the brand's own channel videos
  public  - comments on OTHER people's public videos that mention the brand
  both    - both, kept apart in the `source` column so they can be compared

Privacy: only comment text, date, like count and video info are kept. No author names, channel links or IDs.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone

import pandas as pd

import youtube as yt

SOURCES = ("own", "public", "both")
LANGS_DEFAULT = ("english", "roman_urdu")
MAX_TEXT = 1000

# ------------------------------------------------------------------ language tagging
# Short, common Roman-Urdu words. Words that are also common English words (to, me, main, so...) are left out.
ROMAN_URDU = set("""
hai hain tha thi thay hoga hogi hota hoti ho hun hu nahi nahin nhi nai na kya kyun kyu kaise kese kaisa kesa
kahan kab kon koi kuch sab sabhi bohat bohot bahut boht bhot buhat bht acha acha achi acchi achay achi bura
buri bekar kharab zabardast shandaar lajawab kamaal mast behtreen behtareen umda pasand ka ki ke ko se mein
mai mujhe mjhe mera meri mere hamara hamari hum hume tum tumhara aap aapka aapki apna apni ye yeh wo woh isko
usko iska uska yahan wahan abhi phir lekin magar ya aur bhi hi tak sath saath liye kar karo karna karen kia
kiya kiye karta karti krna kr dena dein dia diya lena lein liya milta milti mila mili aya aaya ayi aayi gaya
gayi gye gaye jaye jana jaa raha rahi rahe rha rhi rhe chahiye chahyie chaiye mehngi mehnga mahngi mahnga
sasta sasti qeemat keemat kapra kapray kapre kaptay jora joda dukan dukaan delivery wali wala walay waly
bilkul sach jhoot shukriya meherbani zaroor insha allah inshallah mashallah masha bhai behen baji yaar dost
logon
""".split())
ENGLISH = set("""
the is are was were be been being am and of it this that these those for with very good great bad best worst
quality price cloth cloths clothes fabric fabrics dress dresses collection design designs love loved like
liked nice beautiful amazing awesome terrible awful poor excellent service delivery customer order ordered
not no yes you your yours my our their they them we he she his her its in on at by from have has had do does did
will would can could should just really too so much many more most less than then when what which who why how
bought buy buying wear wearing worth expensive cheap shop store brand
""".split())
ENGLISH -= {"so", "me", "to", "do", "no", "am"}   # ambiguous in mixed text; stay out of the vote
_WORD = re.compile(r"[a-z']+")
_ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
_LATIN = re.compile(r"[A-Za-z]")
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_TAGS = re.compile(r"<[^>]+>")

SPAM_PHRASES = ("subscribe to my", "sub4sub", "check my channel", "giveaway winner", "click the link", "whatsapp +",
                "dm me", "free robux", "telegram", "earn money", "visit my profile")


def detect_language(text: str) -> str:
    """'english' | 'roman_urdu' | 'urdu_script' | 'other'. A transparent rule, not a model: see README."""
    t = (text or "").strip()
    if not t:
        return "other"
    arabic, latin = len(_ARABIC.findall(t)), len(_LATIN.findall(t))
    if arabic > latin and arabic >= 3:
        return "urdu_script"
    if latin < 3:
        return "other"                       # emoji-only, numbers, single letters
    toks = _WORD.findall(t.lower())
    ur = sum(w in ROMAN_URDU for w in toks)
    en = sum(w in ENGLISH for w in toks)
    if ur >= 1 and ur >= en:
        return "roman_urdu"                  # mixed English + Roman Urdu counts as Roman Urdu
    return "english"


# ------------------------------------------------------------------ cleaning
def clean_text(raw: str) -> str:
    t = html.unescape(raw or "")
    t = _TAGS.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:MAX_TEXT]


def is_spam(text: str) -> bool:
    low = text.lower()
    if _URL.search(low):
        return True
    if any(p in low for p in SPAM_PHRASES):
        return True
    return bool(re.search(r"(.)\1{9,}", low))        # aaaaaaaaaa


def clean_comments(df: pd.DataFrame, languages=LANGS_DEFAULT) -> tuple[pd.DataFrame, dict]:
    """Returns (clean frame, report of how many rows each rule removed). Never edits the input."""
    rep = {"fetched": int(len(df))}
    d = df.copy()
    d["text"] = d["text"].map(clean_text)
    d["published_at"] = pd.to_datetime(d["published_at"], utc=True, errors="coerce").dt.tz_localize(None)
    n = len(d); d = d[d["published_at"].notna() & (d["text"].str.len() >= 3)]
    rep["dropped_empty_or_undated"] = n - len(d)
    n = len(d); d = d.drop_duplicates("comment_id")
    rep["dropped_duplicate_id"] = n - len(d)
    key = d["text"].str.lower().str.replace(r"[^\w\s]", "", regex=True).str.strip()
    n = len(d); d = d[~key.duplicated()]
    rep["dropped_repeated_text"] = n - len(d)
    n = len(d); d = d[~d["text"].map(is_spam)]
    rep["dropped_spam_or_links"] = n - len(d)
    d["language"] = d["text"].map(detect_language)
    rep["language_counts"] = d["language"].value_counts().to_dict()
    n = len(d); d = d[d["language"].isin(languages)]
    rep["dropped_other_language"] = n - len(d)
    rep["kept"] = int(len(d))
    return d.reset_index(drop=True), rep


# ------------------------------------------------------------------ collecting
def _rfc3339(dt: datetime | None) -> str | None:
    return None if dt is None else dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def estimate_units(source: str, max_videos: int, max_comments_per_video: int) -> int:
    """Worst-case quota cost, used to refuse a run BEFORE it spends the shared daily quota."""
    per_video = -(-max_comments_per_video // 100)
    units = 0
    if source in ("own", "both"):
        units += 2 + 2 * (-(-max_videos // 50)) + max_videos * per_video   # channel + playlist + videos + comments
    if source in ("public", "both"):
        units += 100 * (-(-max_videos // 50)) + max_videos * per_video
    return units


def gather_comments(client: yt.YouTubeClient, brand: str, source: str = "both", *, channel: dict | None = None,
                    aliases: tuple[str, ...] = (), date_from: datetime | None = None, date_to: datetime | None = None,
                    max_videos: int = 20, max_comments_per_video: int = 200,
                    languages=LANGS_DEFAULT) -> dict:
    """Collect and clean comments. `channel` is a client.channel_info() result for the brand's own channel
    (required for source own/both). Dates apply to the COMMENT's own date. Returns {'df','report','snapshot'}."""
    if source not in SOURCES:
        raise yt.YouTubeError("Choose where comments come from: own channel, public videos, or both.")
    if source in ("own", "both") and not channel:
        raise yt.YouTubeError("The brand's own channel is needed for this source.")
    max_videos = int(max(1, min(max_videos, 50)))
    max_comments_per_video = int(max(20, min(max_comments_per_video, 1000)))
    if date_from and date_to and date_from > date_to:
        raise yt.YouTubeError("The start date is after the end date.")
    since = _rfc3339(date_from)
    vids: list[dict] = []
    own_channel_id = (channel or {}).get("channel_id", "")

    if source in ("own", "both"):
        ids = client.upload_ids(channel["uploads_playlist"], max_videos)
        for it in client.video_details(ids):
            sn = it.get("snippet") or {}
            vids.append({"video_id": it["id"], "video_title": sn.get("title", ""), "channel_title": channel["title"],
                         "source": "own"})
    if source in ("public", "both"):
        names = [brand, *aliases]
        found = client.search_videos(brand, published_after=since, published_before=_rfc3339(date_to),
                                     max_results=max_videos * 2)
        keep = []
        for v in found:
            if v["channel_id"] == own_channel_id and own_channel_id:
                continue                                               # public = OTHER people's videos
            hay = (v["video_title"] + " " + v["channel_title"]).lower()
            if any(a.lower() in hay for a in names):                   # drop unrelated search noise
                keep.append({**v, "source": "public"})
        vids.extend(keep[:max_videos])

    rows, skipped_disabled = [], 0
    meta = {v["video_id"]: v for v in vids}
    for vid in meta:
        try:
            rows.extend(client.comment_threads(vid, max_comments_per_video, since=since))
        except yt.CommentsDisabled:
            skipped_disabled += 1
    cols = ["comment_id", "video_id", "published_at", "text", "like_count", "reply_count"]
    raw = pd.DataFrame(rows, columns=cols)
    if raw.empty:
        clean, rep = raw.assign(language=[]), {"fetched": 0, "kept": 0}
    else:
        raw["video_title"] = raw["video_id"].map(lambda v: meta[v]["video_title"])
        raw["channel_title"] = raw["video_id"].map(lambda v: meta[v]["channel_title"])
        raw["source"] = raw["video_id"].map(lambda v: meta[v]["source"])
        clean, rep = clean_comments(raw, languages)
        if date_to is not None:
            end = pd.Timestamp(date_to.astimezone(timezone.utc).replace(tzinfo=None)) + timedelta(days=1)
            clean = clean[clean["published_at"] < end].reset_index(drop=True)
            rep["kept"] = int(len(clean))
    rep["videos_used"] = len(meta)
    rep["videos_comments_disabled"] = skipped_disabled
    snap = {"fetched_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "brand": brand,
            "source": source, "date_from": since, "date_to": _rfc3339(date_to),
            "api_units_used": client.units_used, "origin": "YouTube Data API v3 (public comments)"}
    return {"df": clean, "report": rep, "snapshot": snap}
