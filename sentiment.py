"""Stage B: score comment sentiment (English + Roman Urdu) and summarise it.

Two scorers, chosen by the SENTIMENT_BACKEND environment variable:
  lexicon (default) - a transparent word list with negation, "but" and emoji rules. Small, fast, runs anywhere
                      (Render free tier included). Every score can be traced to the words that caused it.
  model             - a multilingual transformer (needs requirements-model.txt, ~1 GB RAM: Hugging Face Spaces).
                      If it cannot load, the site falls back to the lexicon and says so in the result.

Neither scorer is "the truth". tests/eval_sentiment.py measures whichever one is active against comments
a human labelled, so the accuracy that is reported is a measured number, not a claim.
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter

import numpy as np
import pandas as pd

import comments as cm

LABELS = ("positive", "neutral", "negative")
THRESHOLD = 0.2          # |score| below this is "neutral"
MIN_BUCKET = 10          # fewer comments than this in a time bucket / group is flagged as thin
MIN_TOPIC = 20
MODEL_MAX = int(os.environ.get("SENTIMENT_MODEL_MAX", "1500"))   # keeps a CPU request under the worker timeout
ACCURACY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sentiment_accuracy.json")
MODEL_NAME = os.environ.get("SENTIMENT_MODEL", "cardiffnlp/twitter-xlm-roberta-base-sentiment")

# ------------------------------------------------------------------ lexicon (weights: 1 = mild, 2 = strong)
POS = {
    # English
    "good": 1, "great": 2, "love": 2, "loved": 2, "loving": 2, "like": 0.5, "liked": 1, "nice": 1, "beautiful": 2,
    "amazing": 2, "awesome": 2, "excellent": 2, "perfect": 2, "best": 2, "gorgeous": 2, "stunning": 2, "lovely": 2,
    "wonderful": 2, "fantastic": 2, "pretty": 1, "elegant": 2, "classy": 2, "stylish": 1.5, "recommend": 1.5,
    "recommended": 1.5, "worth": 1, "happy": 1.5, "satisfied": 1.5, "fast": 0.5, "thanks": 1, "thank": 1,
    "flawless": 2, "superb": 2, "fabulous": 2, "comfortable": 1.5, "affordable": 1.5, "cute": 1, "obsessed": 1.5,
    # Roman Urdu
    "acha": 1, "achi": 1, "achay": 1, "acchi": 1, "accha": 1, "umda": 2, "zabardast": 2, "shandaar": 2, "lajawab": 2,
    "kamaal": 2, "mast": 1, "behtreen": 2, "behtareen": 2, "pasand": 1.5, "khoobsurat": 2, "khubsurat": 2,
    "khoobsoorat": 2, "sundar": 1.5, "shukriya": 1, "meherbani": 1, "sasta": 1.5, "sasti": 1.5, "bemisaal": 2,
    "mashallah": 1.5, "masha": 0.5, "pyari": 1.5, "pyara": 1.5, "kmaal": 2, "zbrdst": 2, "jabardast": 2,
    "dilkash": 1.5, "perfect_": 0,
}
NEG = {
    # English
    "bad": 1.5, "worst": 2, "terrible": 2, "awful": 2, "poor": 1.5, "hate": 2, "hated": 2, "disappointed": 2,
    "disappointing": 2, "waste": 2, "cheap": 0.5, "overpriced": 2, "expensive": 1.5, "fake": 2, "scam": 2,
    "rude": 2, "late": 1, "delayed": 1.5, "damaged": 2, "faded": 1.5, "torn": 1.5, "ugly": 2, "boring": 1.5,
    "useless": 2, "horrible": 2, "pathetic": 2, "regret": 2, "refund": 1, "complaint": 1.5, "worse": 2,
    "unprofessional": 2, "misleading": 2, "fraud": 2, "shame": 1.5, "disgusting": 2, "loose": 0.5,
    # Roman Urdu
    "bura": 1.5, "buri": 1.5, "bekar": 2, "kharab": 2, "ghatiya": 2, "mehngi": 1.5, "mehnga": 1.5, "mahngi": 1.5,
    "mahnga": 1.5, "jhoot": 1.5, "dhoka": 2, "fraud_": 0, "afsos": 1.5, "bakwas": 2, "faltu": 2, "ganda": 2,
    "gandi": 2, "pareshan": 1.5, "shikayat": 1.5, "dhokebaz": 2, "lutera": 2, "nakli": 2, "bewakoof": 1.5,
}
NEGATORS_FWD = {"not", "no", "never", "dont", "don't", "didnt", "didn't", "isnt", "isn't", "wasnt", "wasn't",
                "cant", "can't", "cannot", "wont", "won't", "hardly", "without", "mat", "nahi_"}   # flips next words
NEGATORS_UR = {"nahi", "nahin", "nhi", "nai", "na"}                    # Roman Urdu: "acha nahi hai" flips the word BEFORE
CONTRAST = {"but", "however", "lekin", "magar", "par", "though", "although"}
BOOST = {"very": 1.4, "really": 1.3, "so": 1.2, "too": 1.2, "extremely": 1.6, "bohat": 1.4, "bohot": 1.4, "bahut": 1.4,
         "boht": 1.4, "bht": 1.4, "bhot": 1.4, "buhat": 1.4, "bilkul": 1.3, "super": 1.4}
EMOJI_POS = set("❤💕😍🥰😘😊🤩👍👏🔥✨💯💖😻🙌🥳💗😁☺🤗")
EMOJI_NEG = set("😡👎😞😤🤮😠😢💔🙄😭😒🤬😖😩☹")
_TOK = re.compile(r"[a-z']+|[" + "".join(sorted(EMOJI_POS | EMOJI_NEG)) + "]")


def lexicon_score(text: str) -> float:
    """Score in [-1, 1]. Positive words add, negative words subtract; see the rules in the module notes."""
    toks = _TOK.findall((text or "").lower())
    vals: list[float] = []
    for i, w in enumerate(toks):
        v = POS.get(w, 0) - NEG.get(w, 0)
        if w in EMOJI_POS:
            v = 1.5
        elif w in EMOJI_NEG:
            v = -1.5
        if v and i and toks[i - 1] in BOOST:
            v *= BOOST[toks[i - 1]]
        vals.append(v)
    for i, w in enumerate(toks):                       # negation
        if w in NEGATORS_FWD:
            for j in range(i + 1, min(i + 4, len(toks))):
                if vals[j]:
                    vals[j] = -0.8 * vals[j]
                    break
        elif w in NEGATORS_UR:
            for j in range(i - 1, max(i - 4, -1), -1):  # look back, "acha nahi hai", "kapra acha nahi"
                if vals[j]:
                    vals[j] = -0.8 * vals[j]
                    break
    cut = next((i for i, w in enumerate(toks) if w in CONTRAST), None)
    if cut is not None:                                # "expensive but beautiful": the clause after "but" carries the verdict
        vals = [x * (0.5 if i < cut else 1.5) for i, x in enumerate(vals)]
    total = float(sum(vals))
    return total / math.sqrt(total * total + 4.0)


def to_label(score: float) -> str:
    return "positive" if score >= THRESHOLD else ("negative" if score <= -THRESHOLD else "neutral")


# ------------------------------------------------------------------ optional model backend
_model = {"pipe": None, "failed": None}


def _load_model():
    if _model["pipe"] is None and _model["failed"] is None:
        try:
            from transformers import pipeline          # noqa: PLC0415  (optional dependency)
            _model["pipe"] = pipeline("text-classification", model=MODEL_NAME, top_k=None, truncation=True, max_length=128)
        except Exception as exc:                       # noqa: BLE001  missing package, no network, out of memory...
            _model["failed"] = f"{type(exc).__name__}: {exc}"[:200]
    return _model["pipe"]


def _model_scores(pipe, texts: list[str]) -> list[float]:
    """Signed score = P(positive) - P(negative), so models and lexicon share one scale."""
    out = []
    for res in pipe(texts, batch_size=32):
        p = {r["label"].lower(): r["score"] for r in res}
        pos = p.get("positive", p.get("label_2", 0.0))
        neg = p.get("negative", p.get("label_0", 0.0))
        out.append(float(pos - neg))
    return out


def score_frame(df: pd.DataFrame, backend: str | None = None, pipe=None) -> tuple[pd.DataFrame, dict]:
    """Adds `score` and `sentiment` columns. Returns (frame, info) where info says what was really used."""
    want = (backend or os.environ.get("SENTIMENT_BACKEND", "lexicon")).lower()
    d = df.copy()
    info = {"backend": "lexicon", "note": "Word-list scorer for English and Roman Urdu: transparent but crude "
                                          "(it misses sarcasm and spellings it has not seen)."}
    if want == "model":
        pipe = pipe or _load_model()
        if pipe is None:
            info["note"] = ("The multilingual model could not be loaded on this server, so the word-list scorer was used "
                            "instead. " + (_model["failed"] or ""))[:300]
        else:
            if len(d) > MODEL_MAX:
                d = d.sample(MODEL_MAX, random_state=0).sort_index()
                info["sampled_to"] = MODEL_MAX
            d["score"] = _model_scores(pipe, d["text"].tolist())
            info = {**info, "backend": "model", "note": f"Multilingual model ({MODEL_NAME}). It was not trained on Roman Urdu "
                    "specifically, so check the accuracy figure before trusting it there."}
    if "score" not in d:
        d["score"] = d["text"].map(lexicon_score)
    d["sentiment"] = d["score"].map(to_label)
    measured = load_measured(info["backend"])
    if measured:
        info["measured"] = measured
    return d.reset_index(drop=True), info


# ------------------------------------------------------------------ measuring accuracy against human labels
def evaluate(labelled: pd.DataFrame, backend: str | None = None, pipe=None) -> dict:
    """`labelled` has columns text and label (positive / neutral / negative, written by a person)."""
    from sklearn.metrics import confusion_matrix, f1_score        # noqa: PLC0415
    d = labelled.copy()
    d["label"] = d["label"].astype(str).str.strip().str.lower()
    d = d[d["label"].isin(LABELS) & d["text"].astype(str).str.strip().ne("")].reset_index(drop=True)
    if d.empty:
        raise ValueError("No rows with a label of positive, neutral or negative.")
    d["text"] = d["text"].astype(str).map(cm.clean_text)
    d["language"] = d["text"].map(cm.detect_language)
    scored, info = score_frame(d, backend, pipe)
    y, yhat = scored["label"], scored["sentiment"]
    counts = y.value_counts()
    out = {"backend": info["backend"], "n": int(len(scored)), "accuracy": float((y == yhat).mean()),
           "baseline": float(counts.max() / len(scored)), "macro_f1": float(f1_score(y, yhat, labels=list(LABELS), average="macro", zero_division=0)),
           "labels": {k: int(counts.get(k, 0)) for k in LABELS},
           "confusion": {"rows_are_human": list(LABELS), "columns_are_scorer": list(LABELS),
                         "matrix": confusion_matrix(y, yhat, labels=list(LABELS)).tolist()},
           "by_language": {lg: {"n": int(len(g)), "accuracy": float((g["label"] == g["sentiment"]).mean())}
                           for lg, g in scored.groupby("language")}}
    out["caution"] = [m for m in (
        f"Only {out['n']} labelled comments: the accuracy figure is rough." if out["n"] < 100 else None,
        "Some labels have fewer than 15 examples, so their errors are not reliable." if min(out["labels"].values()) < 15 else None) if m]
    return out


def load_measured(backend: str) -> dict | None:
    """The last saved evaluation, but only if it was made for the scorer that is being used now."""
    try:
        with open(ACCURACY_FILE, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict) or m.get("backend") != backend:
        return None
    return {k: m.get(k) for k in ("n", "accuracy", "baseline", "macro_f1", "caution")}


# ------------------------------------------------------------------ topics (what are people talking about?)
# Neutral nouns only. Words like "expensive" or "faded" are left out on purpose: they are also sentiment words, and a topic
# found by them would look negative only because the scorer reads them as negative.
TOPICS = {
    "Price": r"\b(?:price|prices|pricing|cost|rate|rates|qeemat|keemat|discount|sale|offer)\b",
    "Quality & fabric": r"\b(?:quality|fabric|fabrics|cloth|kapra|kapray|kapre|stitching|material|texture|lawn|cotton|colou?r fade)\b",
    "Delivery & service": r"\b(?:delivery|order|ordered|courier|parcel|refund|return|exchange|customer service|support|response)\b",
    "Design & collection": r"\b(?:design|designs|collection|print|prints|pattern|style|colou?rs?|new arrivals?)\b",
    "Size & fit": r"\b(?:size|sizes|sizing|fit|fitting)\b",
    "Stores": r"\b(?:store|stores|outlet|branch|mall|shop|dukan|dukaan|showroom)\b",
}
_TOPIC_RE = {k: re.compile(v, re.I) for k, v in TOPICS.items()}


# ------------------------------------------------------------------ summary
def _shares(sub: pd.DataFrame) -> dict:
    n = int(len(sub))
    c = sub["sentiment"].value_counts()
    pos, neu, neg = (int(c.get(k, 0)) for k in LABELS)
    return {"n": n, "positive": pos / n if n else None, "neutral": neu / n if n else None,
            "negative": neg / n if n else None, "net": (pos - neg) / n if n else None}


def _rows(df: pd.DataFrame, col: str) -> list[dict]:
    out = []
    for key, sub in df.groupby(col, sort=True):
        out.append({"group": str(key), **_shares(sub), "few": bool(len(sub) < MIN_BUCKET)})
    return sorted(out, key=lambda r: -r["n"])


def filter_frame(df: pd.DataFrame, source: str | None = None, language: str | None = None,
                 date_from: str | None = None, date_to: str | None = None) -> pd.DataFrame:
    d = df
    if source in ("own", "public"):
        d = d[d["source"] == source]
    if language in ("english", "roman_urdu"):
        d = d[d["language"] == language]
    if date_from:
        d = d[d["published_at"] >= pd.Timestamp(date_from)]
    if date_to:
        d = d[d["published_at"] < pd.Timestamp(date_to) + pd.Timedelta(days=1)]
    return d


def summarize(df: pd.DataFrame) -> dict:
    """Everything the Sentiment page draws, from a scored frame. Only counts, shares and a few short quotes."""
    if df.empty:
        return {"n": 0}
    d = df
    out = {"n": int(len(d)), "overall": _shares(d), "by_source": _rows(d, "source"), "by_language": _rows(d, "language")}
    span = (d["published_at"].max() - d["published_at"].min()).days
    freq = "M" if span > 120 else "W"
    per = d["published_at"].dt.to_period(freq)
    trend = []
    for p, sub in d.groupby(per, sort=True):
        s = _shares(sub)
        trend.append({"period": str(p.start_time.date()), "unit": "month" if freq == "M" else "week", **s,
                      "few": bool(s["n"] < MIN_BUCKET)})
    out["trend"] = trend
    vids = []
    for (vid, title), sub in d.groupby(["video_id", "video_title"], sort=False):
        vids.append({"video_id": vid, "title": title, "source": str(sub["source"].iloc[0]), **_shares(sub)})
    out["by_video"] = sorted(vids, key=lambda r: -r["n"])[:10]
    topics = []
    for name, rx in _TOPIC_RE.items():
        sub = d[d["text"].str.contains(rx)]
        if len(sub):
            topics.append({"topic": name, **_shares(sub), "few": bool(len(sub) < MIN_TOPIC)})
    out["topics"] = sorted(topics, key=lambda r: -r["n"])

    def quotes(label):
        s = d[d["sentiment"] == label].assign(_a=lambda x: x["score"].abs())
        s = s.sort_values(["like_count", "_a"], ascending=False, na_position="last").head(5)
        return [{"text": t[:240], "likes": None if pd.isna(lk) else int(lk), "source": src, "language": lg,
                 "date": ts.strftime("%Y-%m-%d"), "video_id": v}
                for t, lk, src, lg, ts, v in zip(s["text"], s["like_count"], s["source"], s["language"],
                                                  s["published_at"], s["video_id"])]
    out["examples"] = {"positive": quotes("positive"), "negative": quotes("negative")}
    out["first_comment"], out["last_comment"] = (d["published_at"].min().strftime("%Y-%m-%d"),
                                                 d["published_at"].max().strftime("%Y-%m-%d"))
    w = []
    if len(d) < 100:
        w.append(f"Only {len(d)} comments match these filters: treat the percentages as a rough impression, not a measurement.")
    if len(out["by_source"]) > 1:
        w.append("Comments on the brand's own videos and comments on other people's videos come from different crowds; "
                 "compare them, do not add them up as one opinion.")
    if (d["source"] == "public").any():
        w.append("Public-video comments are about a video that mentions the brand, which may not be about the brand itself.")
    w.append("Only top-level comments are used, newest first up to the per-video limit. Comments are a small, self-selected "
             "part of the audience, and not everyone who likes or dislikes a brand comments.")
    out["warnings"] = w
    return out
