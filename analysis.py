"""
Data Detective: the data logic behind Project 1.

Pure pandas / numpy / scikit-learn. No web code lives here, so every function
can be tested on its own. The same ideas as the Colab notebook:

    inspect -> clean a COPY -> explore -> scale -> analytics preview

Design rules (from the lecture):
  * Never assume a column exists. Detect what is there.
  * Missing is not zero. Impossible values become missing, not zero.
  * Always report group sizes next to medians and means.
  * Repeated rows are a scaling experiment, not new evidence.
  * No data leakage: the label is built from engagement metrics, so those
    metrics (and anything derived from them) are never used as features.
"""
from __future__ import annotations

import io
import math
import re
import time
import warnings
from typing import Any

import numpy as np
import pandas as pd

# ----------------------------------------------------------------- constants
ENGAGEMENT_NAMES = ("likes", "comments", "shares", "retweets_shares", "retweets", "saves", "reposts")
FOLLOWER_NAMES = ("followers_count", "followers")

COUNT_LIKE = re.compile(r"(like|comment|share|retweet|repost|save|view|impression|click|reach|follower|count)", re.I)
ID_LIKE = re.compile(r"(^id$|_id$|^id_|uuid)", re.I)
DATE_LIKE = re.compile(r"(time|date)", re.I)
TEXT_LIKE = re.compile(r"(^text$|caption|message|body|description|hashtag|title)", re.I)
REACH_LIKE = re.compile(r"(reach|impression)", re.I)

MAX_GROUPS_SHOWN = 20
MAX_GROUP_LEVELS = 60


class UserError(ValueError):
    """A problem the person can fix (bad file, missing column). Safe to show."""


# ----------------------------------------------------------------- helpers
def jsonable(o: Any) -> Any:
    """Make numpy / pandas values JSON-safe. NaN and NaT become None."""
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return f if math.isfinite(f) else None
    if o is None or o is pd.NA or o is pd.NaT:
        return None
    if isinstance(o, pd.Timestamp):
        return str(o)
    return o


def _is_texty(s: pd.Series) -> bool:
    """True for string/object columns (not numeric, bool, or datetime)."""
    return not (pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s)
                or pd.api.types.is_datetime64_any_dtype(s))


def _num_from_text(st: pd.Series) -> pd.Series:
    """Parse text like '1,125' or '668.0' to numbers. Unparseable values become NaN."""
    return pd.to_numeric(st.astype("string").str.replace(",", "", regex=False).str.strip(), errors="coerce")


def _parse_dates(st: pd.Series) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(st, errors="coerce")


def harmonise(series: pd.Series) -> pd.Series:
    """Trim spaces and unify capitalisation. Every spelling becomes the MOST COMMON one,
    so 'TWITTER' and 'twitter  ' both become 'Twitter'."""
    s = series.astype("string").str.strip()
    key = s.str.lower()
    canon = s.groupby(key).agg(lambda x: x.value_counts().index[0])
    return key.map(canon)


def stored_as(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "true/false"
    if pd.api.types.is_integer_dtype(s):
        return "integer"
    if pd.api.types.is_float_dtype(s):
        return "decimal"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date/time"
    return "text"


def guess_kind(name: str, s: pd.Series) -> str:
    """numerical / categorical / text / date/time / identifier / empty."""
    nonnull = s.dropna()
    if nonnull.empty:
        return "empty"
    if pd.api.types.is_bool_dtype(s):
        return "categorical"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date/time"
    if pd.api.types.is_numeric_dtype(s):
        return "identifier" if ID_LIKE.search(name) else "numerical"
    st = nonnull.astype("string")
    if DATE_LIKE.search(name) and _parse_dates(st).notna().mean() >= 0.9:
        return "date/time"
    if _num_from_text(st).notna().mean() >= 0.9:
        return "numerical"
    if ID_LIKE.search(name):
        return "identifier"
    if TEXT_LIKE.search(name):
        return "text"
    nun = st.nunique()
    if st.str.len().mean() > 40:
        return "text"
    if nun <= 50 or nun / len(st) < 0.05:
        return "categorical"
    if nun / len(st) > 0.9:
        return "identifier"
    return "text"


# ----------------------------------------------------------------- loading
def read_csv_bytes(data: bytes, max_rows: int = 300_000, max_cols: int = 100) -> pd.DataFrame:
    if not data or not data.strip():
        raise UserError("The file is empty.")
    # A real CSV is text. Binary files (images, Excel, zip...) contain NUL or many control bytes.
    sample = data[:8192]
    ctrl = sum(1 for b in sample if b < 32 and b not in (9, 10, 13))
    if b"\x00" in sample or ctrl / len(sample) > 0.01:
        raise UserError("This looks like a binary file, not a CSV. Export it as CSV (comma-separated text) and try again.")
    df = None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(data), nrows=max_rows + 1, encoding=enc, low_memory=False)
            break
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError:
            raise UserError("The file is empty.")
        except (pd.errors.ParserError, ValueError):
            raise UserError("This does not look like a comma-separated (CSV) file.")
    if df is None:
        raise UserError("Could not read the file's text encoding. Save it as UTF-8 CSV and try again.")
    if df.shape[1] < 2:
        raise UserError("Only one column was found. Is the file comma-separated?")
    if df.shape[1] > max_cols:
        raise UserError(f"The file has {df.shape[1]} columns; this tool handles up to {max_cols}.")
    if len(df) == 0:
        raise UserError("The file has column names but no data rows.")
    if len(df) > max_rows:
        raise UserError(f"The file has more than {max_rows:,} rows. This hosted tool handles up to {max_rows:,}. "
                        "That limit is itself a small lesson in why scalable tools exist.")
    df.columns = [str(c).strip() or f"column_{i}" for i, c in enumerate(df.columns)]
    return df


# ----------------------------------------------------------------- inspect
def profile(df: pd.DataFrame) -> dict:
    """What the raw file looks like. Nothing is changed."""
    cols = []
    for name in df.columns:
        s = df[name]
        nonnull = s.dropna()
        example = "" if nonnull.empty else str(nonnull.iloc[0])[:40]
        cols.append({
            "name": name,
            "stored_as": stored_as(s),
            "kind": guess_kind(name, s),
            "missing": int(s.isna().sum()),
            "missing_pct": round(100 * float(s.isna().mean()), 1),
            "distinct": int(s.nunique(dropna=True)),
            "example": example,
        })
    exact = int(df.duplicated().sum())
    return {
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "exact_duplicates": exact,
        "missing_cells": int(df.isna().sum().sum()),
        "cols": cols,
        "issues": detect_issues(df, cols, exact),
        "provenance": provenance_signals(df, cols),
        "head": jsonable(df.head(8).astype(object).where(df.head(8).notna(), None).to_dict("records")),
    }


def detect_issues(df: pd.DataFrame, cols: list[dict], exact: int) -> list[dict]:
    issues: list[dict] = []
    if exact:
        issues.append({"column": "(rows)", "text": f"{exact} rows are exact copies of another row."})
    for c in cols:
        name, s = c["name"], df[c["name"]]
        if c["kind"] == "numerical" and c["stored_as"] == "text":
            commas = int(s.astype("string").str.contains(",", regex=False).sum())
            extra = f"; {commas} values contain a thousands comma" if commas else ""
            issues.append({"column": name, "text": f"Numbers are stored as text{extra}."})
        if c["kind"] == "categorical" and _is_texty(s):
            st = s.astype("string")
            raw_n, tidy_n = st.nunique(), st.str.strip().str.lower().nunique()
            if tidy_n < raw_n:
                issues.append({"column": name,
                               "text": f"{raw_n} different spellings for {tidy_n} real values "
                                       "(capitalisation or extra spaces)."})
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s) and COUNT_LIKE.search(name):
            neg = int((s < 0).sum())
            if neg:
                issues.append({"column": name, "text": f"{neg} negative values, which are impossible for a count."})
        if c["kind"] == "date/time" and _is_texty(s):
            nonnull = s.dropna().astype("string")
            failed = int(_parse_dates(nonnull).isna().sum())
            if failed:
                issues.append({"column": name, "text": f"{failed} values cannot be read as dates."})
            else:
                issues.append({"column": name, "text": "Dates are stored as text, but every value converts cleanly."})
        if c["kind"] == "identifier" and ID_LIKE.search(name):
            dups = int(s.duplicated().sum())
            if dups:
                issues.append({"column": name, "text": f"{dups} rows repeat an ID that appears earlier."})
    blanks = sorted([(c["missing"], c["name"]) for c in cols if c["missing"]], reverse=True)
    if blanks:
        txt = ", ".join(f"{n} {name}" for n, name in blanks[:8])
        issues.append({"column": "(blanks)",
                       "text": f"Blank values: {txt}. Do not delete them automatically; ask what each blank means."})
    return issues


def provenance_signals(df: pd.DataFrame, cols: list[dict]) -> dict:
    """Facts that help someone judge whether data looks real. Observations, not proof."""
    out: dict[str, Any] = {"rows": int(len(df))}
    for c in cols:
        if c["kind"] == "text" and re.search(r"text|caption|message|body", c["name"], re.I):
            out["text_column"] = c["name"]
            out["distinct_texts"] = int(df[c["name"]].nunique())
            top = df[c["name"]].value_counts().head(3)
            out["top_texts"] = [{"text": str(k)[:90], "count": int(v)} for k, v in top.items()]
            break
    for c in cols:
        if re.search(r"hashtag", c["name"], re.I):
            tags = df[c["name"]].dropna().astype("string").str.findall(r"#\w+").explode().dropna()
            out["distinct_hashtags"] = int(tags.nunique())
            break
    for c in cols:
        if c["kind"] == "identifier" and re.search(r"user|account|handle", c["name"], re.I):
            out["user_column"] = c["name"]
            out["distinct_users"] = int(df[c["name"]].nunique())
            out["max_posts_by_one_user"] = int(df[c["name"]].value_counts().iloc[0])
            break
    if "distinct_texts" in out and out["rows"] >= 500:
        out["looks_templated"] = out["distinct_texts"] / out["rows"] < 0.2
    return out


# ----------------------------------------------------------------- clean
def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Clean a COPY. Missing values are kept; impossible values become missing, not zero."""
    c = df.copy()
    steps: list[dict] = []
    raw_exact = int(df.duplicated().sum())
    raw_kinds = {name: guess_kind(name, df[name]) for name in df.columns}

    # 1 spelling variants and stray spaces
    merges = {}
    for name in c.columns:
        if _is_texty(c[name]) and raw_kinds[name] in ("categorical", "text", "identifier"):
            st = c[name].astype("string")
            raw_n, tidy_n = st.nunique(), st.str.strip().str.lower().nunique()
            if tidy_n < raw_n and tidy_n <= 100:
                c[name] = harmonise(st)
                merges[name] = {"before": int(raw_n), "after": int(c[name].nunique())}
            else:
                c[name] = st.str.strip()
    for name, m in merges.items():
        steps.append({"title": f"Tidied spellings in {name}",
                      "detail": f"{m['before']} spellings became {m['after']}. Every variant now uses the most common spelling."})

    # 2 numbers stored as text
    converted = []
    for name in c.columns:
        if raw_kinds[name] == "numerical" and _is_texty(c[name]):
            before_missing = int(c[name].isna().sum())
            commas = int(c[name].astype("string").str.contains(",", regex=False).sum())
            c[name] = _num_from_text(c[name])
            newly = int(c[name].isna().sum()) - before_missing
            converted.append(name)
            extra = f" {commas} values had thousands commas." if commas else ""
            bad = f" {newly} values could not be read and are now missing." if newly else ""
            steps.append({"title": f"Converted {name} from text to numbers", "detail": f"Stored as text in the file.{extra}{bad}"})

    # 3 dates
    for name in c.columns:
        if raw_kinds[name] == "date/time" and _is_texty(c[name]):
            before_missing = int(c[name].isna().sum())
            c[name] = _parse_dates(c[name].astype("string"))
            newly = int(c[name].isna().sum()) - before_missing
            msg = "Every value converted." if not newly else f"{newly} values could not be read and are now missing."
            steps.append({"title": f"Converted {name} to date/time", "detail": msg})

    # 4 impossible negatives become MISSING (not zero)
    negatives = {}
    for name in c.columns:
        s = c[name]
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s) and COUNT_LIKE.search(name):
            neg = int((s < 0).sum())
            if neg:
                c[name] = s.astype("float64").mask(s < 0)
                negatives[name] = neg
                steps.append({"title": f"Negative {name} set to missing",
                              "detail": f"{neg} impossible values became missing, not zero. A wrong number is unknown, not zero."})

    # 5 duplicates AFTER tidying (some copies differ only in capitalisation)
    before = len(c)
    c = c.drop_duplicates().reset_index(drop=True)
    removed = before - len(c)
    tidy_only = max(removed - raw_exact, 0)
    detail = f"{removed} duplicate rows removed"
    if tidy_only:
        detail += f" ({raw_exact} were exact copies in the raw file; {tidy_only} more differed only in capitalisation or spacing)"
    steps.append({"title": "Removed duplicate rows", "detail": detail + "."})
    id_dups = {n: int(c[n].duplicated().sum()) for n in c.columns if ID_LIKE.search(n) and c[n].duplicated().any()}

    # 6 derived columns
    derived = []
    for name in c.columns:
        if re.fullmatch(r"hashtags?", name, re.I) and "hashtag_count" not in c.columns:
            c["hashtag_count"] = c[name].fillna("").astype("string").str.count(r"#\w+").astype(int)
            derived.append("hashtag_count")
            steps.append({"title": "Added hashtag_count",
                          "detail": "Number of #tags per post. A blank hashtag cell most likely means the post had none, so it counts as 0 (a judgement about this column only)."})
            break
    eng = engagement_columns(c)
    if len(eng) >= 2:
        c["total_engagement"] = c[eng].sum(axis=1, skipna=False)
        derived.append("total_engagement")
        steps.append({"title": "Added total_engagement",
                      "detail": f"Sum of {', '.join(eng)}. If any part is missing the total is missing (a blank is not a zero)."})
        fol = next((n for n in FOLLOWER_NAMES if n in c.columns), None)
        if fol:
            c["engagement_per_1k_followers"] = c["total_engagement"] / c[fol].where(c[fol] > 0) * 1000
            derived.append("engagement_per_1k_followers")
            steps.append({"title": "Added engagement_per_1k_followers",
                          "detail": "Engagement per 1,000 FOLLOWERS. This is not an engagement rate on reach: the dataset has no reach or impressions column."})

    return c, {
        "rows_before": int(len(df)),
        "rows_after": int(len(c)),
        "duplicates_removed": int(removed),
        "exact_duplicates_raw": raw_exact,
        "spelling_merges": merges,
        "converted_to_numbers": converted,
        "negatives_to_missing": negatives,
        "duplicate_ids_left": id_dups,
        "derived": derived,
        "steps": steps,
        "missing_after": {n: int(c[n].isna().sum()) for n in c.columns if c[n].isna().any()},
        "note": ("Missing values were kept, not filled or dropped. Rows with a missing group label are left out of "
                 "group tables, so group counts add up to fewer than the total."),
    }


def engagement_columns(df: pd.DataFrame) -> list[str]:
    return [n for n in ENGAGEMENT_NAMES if n in df.columns and pd.api.types.is_numeric_dtype(df[n])]


def column_roles(df: pd.DataFrame) -> dict:
    """Which cleaned columns can be grouped by, measured, or used as a date."""
    groups, metrics, dates = [], [], []
    for name in df.columns:
        s = df[name]
        kind = guess_kind(name, s)
        if kind == "categorical" and 2 <= s.nunique() <= MAX_GROUP_LEVELS:
            groups.append(name)
        elif kind == "numerical" and not ID_LIKE.search(name) and pd.api.types.is_numeric_dtype(s):
            metrics.append(name)
        elif kind == "date/time" and pd.api.types.is_datetime64_any_dtype(s):
            dates.append(name)
    return {"groups": groups, "metrics": metrics, "dates": dates}


def focus_options(df: pd.DataFrame, groups: list[str]) -> dict:
    out = {}
    for g in groups:
        vc = df[g].value_counts()
        out[g] = [{"value": str(k), "count": int(v)} for k, v in vc.head(30).items()]
    return out


def apply_focus(df: pd.DataFrame, col: str | None, val: str | None) -> pd.DataFrame:
    if not col or val in (None, ""):
        return df
    if col not in df.columns:
        raise UserError(f"Column '{col}' is not in the data.")
    out = df[df[col].astype("string") == val]
    if out.empty:
        raise UserError(f"No rows where {col} = {val}.")
    return out


# ----------------------------------------------------------------- explore
def _need(df: pd.DataFrame, name: str | None, what: str) -> str:
    if not name or name not in df.columns:
        raise UserError(f"Choose a valid {what}.")
    return name


def group_table(df: pd.DataFrame, group_col: str, metric: str, min_posts: int = 30) -> dict:
    g = df[[group_col, metric]].dropna(subset=[group_col])
    excluded = int(len(df) - len(g))
    t = g.groupby(group_col)[metric].agg(posts="count", median="median", mean="mean")
    t = t[t["posts"] > 0].sort_values("posts", ascending=False).head(MAX_GROUPS_SHOWN)
    t = t.sort_values("median", ascending=False)
    rows = [{"group": str(idx), "posts": int(r.posts), "median": float(r["median"]), "mean": float(r["mean"]),
             "too_few": bool(r.posts < min_posts)} for idx, r in t.iterrows()]
    return {"group_col": group_col, "metric": metric, "rows": rows, "excluded_missing_group": excluded,
            "min_posts": int(min_posts)}


def distribution(s: pd.Series, bins: int = 30) -> dict:
    v = s.dropna().astype(float)
    v = v[np.isfinite(v)]
    if v.empty:
        return {"n": 0}
    counts, edges = np.histogram(v, bins=min(bins, max(5, int(v.nunique()))))
    return {"n": int(len(v)), "edges": edges.tolist(), "counts": counts.tolist(),
            "mean": float(v.mean()), "median": float(v.median()), "std": float(v.std()),
            "min": float(v.min()), "max": float(v.max())}


def top_share(s: pd.Series, frac: float = 0.10) -> dict | None:
    v = s.dropna().astype(float)
    v = v[v >= 0].sort_values(ascending=False)
    if v.empty or v.sum() <= 0:
        return None
    k = max(1, int(len(v) * frac))
    return {"top_n": int(k), "of": int(len(v)), "share": float(v.head(k).sum() / v.sum())}


def spearman(df: pd.DataFrame, a: str, b: str) -> dict:
    pair = df[[a, b]].dropna()
    pts = pair if len(pair) <= 1500 else pair.sample(1500, random_state=1)
    r = None
    if len(pair) >= 3 and pair[a].nunique() > 1 and pair[b].nunique() > 1:
        r = float(pair.corr(method="spearman").iloc[0, 1])
    return {"x": a, "y": b, "n": int(len(pair)), "shown": int(len(pts)), "spearman": r,
            "points": pts.astype(float).values.tolist()}


def by_weekday(df: pd.DataFrame, dt_col: str, metric: str) -> list[dict]:
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    t = (df.assign(_d=df[dt_col].dt.day_name()).dropna(subset=["_d"]).groupby("_d")[metric]
         .agg(posts="count", median="median", mean="mean").reindex(order))
    return [{"day": d, "posts": int(r.posts) if pd.notna(r.posts) else 0,
             "median": None if pd.isna(r["median"]) else float(r["median"]),
             "mean": None if pd.isna(r["mean"]) else float(r["mean"])} for d, r in t.iterrows()]


def explore(df: pd.DataFrame, all_columns: list[str], group_col: str, metric: str, min_posts: int,
            x: str | None, y: str | None, dt_col: str | None, youtube: bool = False) -> dict:
    """Everything the Explore tab needs, for the (already focused) dataframe."""
    roles = column_roles(df)
    _need(df, group_col, "group column")
    _need(df, metric, "metric")
    if group_col not in roles["groups"]:
        raise UserError(f"'{group_col}' has too many different values to group by (limit {MAX_GROUP_LEVELS}).")
    min_posts = int(max(1, min(min_posts, 100000)))
    out: dict[str, Any] = {
        "rows_used": int(len(df)),
        "group": group_table(df, group_col, metric, min_posts),
        "dist": distribution(df[metric]),
        "top_share": top_share(df[metric]),
    }
    if x and y and x in df.columns and y in df.columns:
        out["scatter"] = spearman(df, x, y)
    if dt_col and dt_col in df.columns and pd.api.types.is_datetime64_any_dtype(df[dt_col]):
        out["weekday"] = {"dt_col": dt_col, "rows": by_weekday(df, dt_col, metric)}
    warns = []
    noun = "videos" if youtube else "posts"
    few = [r["group"] for r in out["group"]["rows"] if r["too_few"]]
    if few:
        warns.append(f"These groups have fewer than {min_posts} {noun}, so treat their numbers as weak evidence: {', '.join(few[:8])}.")
    d = out["dist"]
    if d.get("n") and d.get("median") and d["mean"] / d["median"] > 1.5:
        warns.append("The mean is far above the median: a few very large values may dominate the average.")
    if youtube:
        warns.append("Views are not reach: YouTube does not give reach or impressions here, so never call these numbers "
                     "a reach or an engagement rate on reach. Engagement per 1,000 views is a different measure.")
        if metric in ("view_count", "like_count", "comment_count"):
            warns.append("Newer videos have had less time to collect views, likes and comments. Compare videos of "
                         "similar age (the age_days column) before saying one kind of video does better.")
    elif not any(REACH_LIKE.search(n) for n in all_columns):
        warns.append("There is no reach or impressions column, so do not claim an engagement RATE on reach. "
                     "Engagement per follower is a different measure.")
    if "weekday" not in out:
        warns.append("No usable date/time column: make no claims about the best day to post.")
    else:
        counts = [r["posts"] for r in out["weekday"]["rows"]]
        if counts and min(counts) < 30:
            warns.append(f"Some weekdays have fewer than 30 {noun}. Check the {noun} column before claiming a best day.")
    out["warnings"] = warns
    return out


# ----------------------------------------------------------------- scaling
def _available_mb() -> float | None:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return None


def run_scaling(df: pd.DataFrame, group_col: str, metrics: list[str], factors: list[int],
                max_rows: int, repeats: int = 3) -> dict:
    """The SAME analysis on repeated copies of the data. Repeated copies are a scaling
    experiment, not new real-world evidence."""
    _need(df, group_col, "group column")
    metrics = [m for m in metrics if m in df.columns and pd.api.types.is_numeric_dtype(df[m])]
    if not metrics:
        raise UserError("Choose at least one numeric metric.")
    base = df.copy()
    base_mb = base.memory_usage(deep=True).sum() / 1e6
    ops = {
        "group count/mean/median": lambda f: f.groupby(group_col)[metrics].agg(["count", "mean", "median"]),
        "describe": lambda f: f[metrics].describe(),
        "sort, top 10": lambda f: f.sort_values(metrics[0], ascending=False).head(10),
        "value counts": lambda f: f[group_col].value_counts(),
    }
    if len(metrics) >= 2:
        ops["correlation"] = lambda f: f[metrics].corr()
    results = []
    for factor in sorted(set(int(f) for f in factors)):
        rows = len(base) * factor
        if factor < 1:
            continue
        if rows > max_rows:
            results.append({"multiplier": f"{factor}x", "rows": rows, "status": "skipped",
                            "reason": f"Above this server's limit of {max_rows:,} rows. Run scaling_experiment.py on your own computer for bigger sizes."})
            continue
        free = _available_mb()
        if free is not None and base_mb * factor * 3 > 0.6 * free:
            results.append({"multiplier": f"{factor}x", "rows": rows, "status": "skipped",
                            "reason": "Would not fit in this server's free memory. That is a real result: this workflow does not fit at this size here."})
            continue
        big = pd.concat([base] * factor, ignore_index=True)
        buf = big.to_csv(index=False).encode("utf-8")
        del big
        t0 = time.perf_counter()
        loaded = pd.read_csv(io.BytesIO(buf), low_memory=False)
        load_s = time.perf_counter() - t0
        timings = {}
        for name, fn in ops.items():
            best = float("inf")
            for _ in range(repeats):
                t0 = time.perf_counter()
                fn(loaded)
                best = min(best, time.perf_counter() - t0)
            timings[name] = best
        slowest = max(timings, key=timings.get)
        results.append({"multiplier": f"{factor}x", "rows": int(len(loaded)), "status": "ok",
                        "file_mb": round(len(buf) / 1e6, 2), "load_seconds": round(load_s, 4),
                        "analysis_seconds": round(sum(timings.values()), 4), "slowest_operation": slowest,
                        "memory_mb": round(float(loaded.memory_usage(deep=True).sum()) / 1e6, 1)})
        del loaded, buf
    return {"results": results, "group_col": group_col, "metrics": metrics,
            "note": "Repeated copies are a scaling experiment, not new real-world evidence. Repeated rows are also easier "
                    "for a computer than varied real data. There is no universal row count at which pandas fails."}


# ----------------------------------------------------------------- analytics preview
def run_models(df: pd.DataFrame) -> dict:
    """Short, honest demos of classification, clustering and regression.
    The label comes from the engagement metrics, so those metrics are never features."""
    from sklearn.cluster import KMeans
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.metrics import accuracy_score, mean_absolute_error, r2_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    eng = engagement_columns(df)
    if "likes" not in eng or len(eng) < 2:
        return {"available": False,
                "reason": "The demos need a 'likes' column and at least one other engagement column (comments, shares, ...)."}
    leak = set(eng) | {"total_engagement", "engagement_per_1k_followers"}
    num_feats = [n for n in df.columns if n not in leak and pd.api.types.is_numeric_dtype(df[n])
                 and not pd.api.types.is_bool_dtype(df[n]) and not ID_LIKE.search(n) and guess_kind(n, df[n]) == "numerical"]
    cat_feats = [n for n in df.columns if n not in leak and _is_texty(df[n]) and guess_kind(n, df[n]) == "categorical"
                 and 2 <= df[n].nunique() <= 12]
    if not num_feats and not cat_feats:
        return {"available": False, "reason": "No usable feature columns were found."}

    d = df.dropna(subset=eng + num_feats).copy()
    if len(d) < 100:
        return {"available": False, "reason": f"Only {len(d)} complete rows; the demos need at least 100."}
    for n in cat_feats:
        d[n] = d[n].astype("string").fillna("Unknown")
    numX = d[num_feats].astype(float)
    logged = []
    for n in num_feats:                       # heavily skewed counts (e.g. followers) work better on a log scale
        if numX[n].min() >= 0 and numX[n].skew() > 1.5:
            numX[n] = np.log1p(numX[n])
            logged.append(n)
    X = pd.concat([numX, pd.get_dummies(d[cat_feats].astype("string"), drop_first=True).astype(float)], axis=1)
    assert not (set(X.columns) & leak), "Leakage: a target metric is among the features"

    total = d[eng].sum(axis=1)
    out: dict[str, Any] = {"available": True, "rows_used": int(len(d)), "rows_total": int(len(df)),
                           "features": list(X.columns), "log_scaled_features": logged, "engagement_columns": eng,
                           "label_rule": f"HIGH engagement = {' + '.join(eng)} at or above the median ({float(total.median()):g})."}

    y = (total >= total.median()).astype(int)
    if y.nunique() == 2 and y.value_counts().min() >= 10:
        Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
        clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(Xtr, ytr)
        out["classification"] = {"accuracy": float(accuracy_score(yte, clf.predict(Xte))),
                                 "baseline": float(max(yte.mean(), 1 - yte.mean())),
                                 "train": int(len(Xtr)), "test": int(len(Xte))}

    clus_cols = [n for n in (list(FOLLOWER_NAMES) + eng) if n in d.columns]
    if len(clus_cols) >= 2 and len(d) >= 30:
        Z = StandardScaler().fit_transform(np.log1p(d[clus_cols].astype(float).clip(lower=0)))
        km = KMeans(n_clusters=3, n_init=10, random_state=0).fit(Z)
        prof = d[clus_cols].assign(cluster=km.labels_).groupby("cluster").median().round(1)
        prof.insert(0, "posts", pd.Series(km.labels_).value_counts().sort_index())
        prof = prof.sort_values(clus_cols[0])
        out["clustering"] = {"columns": clus_cols,
                             "profile": [{"cluster": f"Group {i + 1}", **{k: float(v) for k, v in r.items()}}
                                         for i, (_, r) in enumerate(prof.iterrows())]}

    y_reg = np.log1p(d["likes"].astype(float).clip(lower=0))
    Xtr, Xte, ytr, yte = train_test_split(X, y_reg, test_size=0.25, random_state=42)
    reg = make_pipeline(StandardScaler(), LinearRegression()).fit(Xtr, ytr)
    pred = np.expm1(reg.predict(Xte))
    actual = np.expm1(yte)
    out["regression"] = {"r2_log": float(r2_score(yte, reg.predict(Xte))),
                         "mae_model": float(mean_absolute_error(actual, pred)),
                         "mae_baseline": float(mean_absolute_error(actual, np.full(len(actual), np.expm1(ytr).median())))}
    out["notes"] = ["Always compare with a baseline. If a model barely beats it, do not present it as useful.",
                    "Leakage guard: likes, comments, shares and anything built from them are excluded from the features.",
                    "These are demos on observational data. They do not show what CAUSES engagement."]
    return out


# ================================================================= YouTube
# Data comes from youtube.py (official API, public data). The same lecture rules apply:
#   hidden counts are MISSING (not zero) | views are not reach | show group sizes |
#   a channel is small, so gate everything by the number of videos | no leakage in models.
YT_COUNTS = ("view_count", "like_count", "comment_count")
YT_LEAK = {"view_count", "like_count", "comment_count", "engagement_per_1k_views", "likes_per_1k_views"}
YT_MIN_VIDEOS = 10          # below this we show the data but make no comparisons
YT_MIN_MODELS = 40          # below this the three model demos are switched off
YT_MIN_GROUP = 10           # a group needs this many videos before we compare it


def clean_youtube(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Clean a COPY of the fetched videos. Hidden counts stay missing; nothing is filled with zero."""
    c = df.copy()
    steps: list[dict] = []
    before = len(c)
    c = c.drop_duplicates(subset="video_id").reset_index(drop=True)
    removed = before - len(c)
    steps.append({"title": "Checked for repeated videos",
                  "detail": f"{removed} repeated video IDs removed." if removed else "Every video ID appears once."})

    negatives: dict[str, int] = {}
    for col in YT_COUNTS + ("duration_seconds",):
        neg = int((c[col] < 0).sum())
        if neg:
            c[col] = c[col].mask(c[col] < 0)
            negatives[col] = neg
            steps.append({"title": f"Negative {col} set to missing", "detail": f"{neg} impossible values became missing, not zero."})

    n = len(c)
    for col, why in (("like_count", "the creator hides likes on those videos"), ("comment_count", "comments are switched off on those videos")):
        miss = int(c[col].isna().sum())
        steps.append({"title": f"{col}: {miss} of {n} blank",
                      "detail": (f"Blank most likely means {why}. They are kept as missing, not counted as 0, "
                                 "and left out of any average that needs them.") if miss else "No blanks."})
    live = int(c["is_live"].sum()) if "is_live" in c else 0
    nodur = int(c["duration_seconds"].isna().sum())
    if nodur:
        steps.append({"title": "Duration missing for some videos",
                      "detail": f"{nodur} videos (live or upcoming streams, {live} flagged live) have no length. Kept as missing."})

    derived = []
    pos = c["view_count"].where(c["view_count"] > 0)
    c["likes_per_1k_views"] = c["like_count"] / pos * 1000
    c["engagement_per_1k_views"] = (c["like_count"] + c["comment_count"]) / pos * 1000
    derived += ["likes_per_1k_views", "engagement_per_1k_views"]
    steps.append({"title": "Added likes_per_1k_views and engagement_per_1k_views",
                  "detail": "Likes (and likes + comments) per 1,000 VIEWS. This is not an engagement rate on reach and not "
                            "per subscriber. If a count is missing, the result is missing."})
    steps.append({"title": "Added publish_hour, publish_weekday, format, age_days",
                  "detail": "Taken from the publish time (UTC). 'Short' means 60 seconds or less, which is only a length rule. "
                            "age_days is days between publishing and the moment the data was fetched."})
    return c, {
        "rows_before": int(before), "rows_after": int(len(c)), "duplicates_removed": int(removed),
        "exact_duplicates_raw": int(removed), "spelling_merges": {}, "converted_to_numbers": [],
        "negatives_to_missing": negatives, "duplicate_ids_left": {}, "derived": derived, "steps": steps,
        "missing_after": {k: int(c[k].isna().sum()) for k in c.columns if c[k].isna().any()},
        "note": "Missing values were kept, not filled or dropped. Averages use only the videos that have a value.",
    }


def youtube_roles(df: pd.DataFrame) -> dict:
    roles = column_roles(df)
    roles["metrics"] = [m for m in roles["metrics"] if df[m].nunique() > 1 and m not in ("channel_subscribers",)]
    roles["groups"] = [g for g in roles["groups"] if g not in ("channel_title",)]
    return roles


def youtube_overview(df: pd.DataFrame) -> dict:
    n = int(len(df))
    v = df["view_count"].dropna()
    dates = df["published_at"].dropna()
    top = df.dropna(subset=["view_count"]).nlargest(10, "view_count")
    return {
        "videos": n,
        "first_published": str(dates.min().date()) if len(dates) else None,
        "last_published": str(dates.max().date()) if len(dates) else None,
        "median_views": float(v.median()) if len(v) else None,
        "mean_views": float(v.mean()) if len(v) else None,
        "total_views_in_sample": float(v.sum()) if len(v) else None,
        "likes_hidden": int(df["like_count"].isna().sum()),
        "comments_off": int(df["comment_count"].isna().sum()),
        "median_duration_min": float(df["duration_seconds"].median() / 60) if df["duration_seconds"].notna().any() else None,
        "enough_for_comparisons": n >= YT_MIN_VIDEOS,
        "enough_for_models": n >= YT_MIN_MODELS,
        "top_videos": [{"video_id": r.video_id, "title": r.title, "views": float(r.view_count),
                        "published": str(r.published_at.date()) if pd.notna(r.published_at) else None}
                       for r in top.itertuples()],
    }


def _med(s: pd.Series):
    return float(s.median()) if s.notna().any() else None


def insights_youtube(df: pd.DataFrame) -> list[dict]:
    """Finding / Evidence / Action / Limitation, written ONLY from numbers in this fetch.
    Each card says how much to trust it. Nothing here claims causes."""
    out: list[dict] = []
    n = len(df)
    if n < YT_MIN_VIDEOS:
        return [{"title": "Too few videos to compare", "strength": "weak",
                 "finding": f"Only {n} videos were fetched, so any comparison would mostly be noise.",
                 "evidence": f"n = {n}; the tool needs at least {YT_MIN_VIDEOS}.",
                 "action": "Fetch more videos, or pick a channel with a longer upload history.",
                 "limitation": "A handful of videos cannot show a pattern."}]
    v = df["view_count"].dropna()
    ts = top_share(v)
    if ts and len(v) >= YT_MIN_VIDEOS:
        mean, med = float(v.mean()), float(v.median())
        ratio = mean / med if med else float("nan")
        out.append({
            "title": "Views are concentrated in a few videos", "strength": "ok",
            "finding": f"The top 10% of videos ({ts['top_n']} of {ts['of']}) hold {ts['share']:.0%} of all views in this sample. "
                       f"The mean is {mean:,.0f} views and the median is {med:,.0f}" + (f" ({ratio:.1f}x higher)." if ratio == ratio else "."),
            "evidence": f"Views column, n = {len(v)}. See the histogram on the Explore page.",
            "action": "Plan around the median video, and study the few hits separately rather than averaging them in.",
            "limitation": "Views are not reach. A few viral videos can dominate any average, so a typical video does worse than the mean suggests."})

    if "format" in df and df["format"].nunique() == 2:
        g = df.dropna(subset=["format", "view_count"]).groupby("format")["view_count"].agg(["count", "median"])
        if len(g) == 2 and g["count"].min() >= YT_MIN_GROUP:
            hi, lo = g["median"].idxmax(), g["median"].idxmin()
            out.append({
                "title": "Shorts and standard videos compared", "strength": "ok",
                "finding": f"“{hi}” has the higher median views: {g.loc[hi, 'median']:,.0f} vs {g.loc[lo, 'median']:,.0f} for “{lo}”.",
                "evidence": f"Group sizes: {hi} n = {int(g.loc[hi, 'count'])}, {lo} n = {int(g.loc[lo, 'count'])}.",
                "action": "Test the same topic in both formats over a few weeks and compare with equal time since publishing.",
                "limitation": "Format is confounded with topic and age; Shorts are also counted and shown differently by YouTube."})
        else:
            small = ", ".join(f"{k} n = {int(r['count'])}" for k, r in g.iterrows())
            out.append({
                "title": "Shorts vs standard videos: not enough videos in one group", "strength": "weak",
                "finding": "One format has too few videos to compare fairly.",
                "evidence": f"{small}; each group needs at least {YT_MIN_GROUP}.",
                "action": "Do not claim one format is better from this fetch.",
                "limitation": "Small groups swing wildly from one video to the next."})

    e = df["engagement_per_1k_views"].dropna()
    if len(e) >= YT_MIN_VIDEOS:
        out.append({
            "title": "How much viewers react", "strength": "ok" if len(e) >= 30 else "weak",
            "finding": f"The median video gets {float(e.median()):,.1f} likes + comments per 1,000 views.",
            "evidence": f"n = {len(e)} videos with both counts visible; {int(df['like_count'].isna().sum())} have likes hidden and "
                        f"{int(df['comment_count'].isna().sum())} have comments off (kept as missing).",
            "action": "Use this as a baseline: a video far above it is worth studying, far below is worth rethinking.",
            "limitation": "This is per view, not per person reached. Videos with hidden counts are left out, which may bias the number."})

    wd = df.dropna(subset=["publish_weekday"]).groupby("publish_weekday").size()
    if len(wd):
        low = int(wd.reindex(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]).fillna(0).min())
        out.append({
            "title": "Best day to post", "strength": "weak",
            "finding": "No best-day claim is made." if low < 30 else "Weekdays all have 30+ videos, so a weekday comparison is possible on the Explore page.",
            "evidence": f"The thinnest weekday has {low} videos (a fair comparison needs about 30).",
            "action": "Keep a posting log and revisit after more uploads." if low < 30 else "Compare weekdays on the Explore page, then test.",
            "limitation": "Channels rarely post evenly across weekdays, and posting day is tied to topic and audience."})

    d = df.dropna(subset=["age_days", "view_count"])
    if len(d) >= 20:
        half = d["age_days"].median()
        newer, older = d[d["age_days"] <= half]["view_count"], d[d["age_days"] > half]["view_count"]
        out.append({
            "title": "Newer vs older videos", "strength": "ok",
            "finding": f"The newer half of videos has a median of {float(newer.median()):,.0f} views; the older half {float(older.median()):,.0f}.",
            "evidence": f"Split at {half:,.0f} days since publishing; n = {len(newer)} and {len(older)}.",
            "action": "When comparing videos, compare ones of similar age, or track views at a fixed number of days.",
            "limitation": "Older videos have had longer to collect views, so the gap partly reflects time, not quality."})

    d = df.dropna(subset=["duration_seconds", "view_count"])
    if len(d) >= 30 and d["duration_seconds"].nunique() > 1:
        r = float(d[["duration_seconds", "view_count"]].corr(method="spearman").iloc[0, 1])
        word = "weak" if abs(r) < 0.3 else "moderate" if abs(r) < 0.6 else "strong"
        out.append({
            "title": "Length and views", "strength": "ok",
            "finding": f"Video length and views have a {word} {'positive' if r >= 0 else 'negative'} relationship (Spearman {r:.2f}).",
            "evidence": f"n = {len(d)} videos with a length and a view count.",
            "action": "If you test a different length, change only the length and keep topic and thumbnail steady.",
            "limitation": "Correlation is not causation, and Shorts mix with long videos in this measure."})
    return out


def run_models_youtube(df: pd.DataFrame) -> dict:
    """Classification, clustering and regression previews for ONE channel's videos.
    Targets: high vs low engagement per 1,000 views; log(views); video profiles.
    Leakage guard: views, likes, comments and anything built from them are never features."""
    from sklearn.cluster import KMeans
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.metrics import accuracy_score, mean_absolute_error, r2_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if len(df) < YT_MIN_MODELS:
        return {"available": False,
                "reason": f"Only {len(df)} videos. The model demos need at least {YT_MIN_MODELS}, "
                          "because with fewer the test set is too small to mean anything."}
    num = [c for c in ("duration_seconds", "title_length", "tag_count", "publish_hour", "age_days")
           if c in df and df[c].nunique() > 1]
    cat = [c for c in ("format", "category", "publish_weekday", "definition")
           if c in df and 2 <= df[c].nunique() <= 12]
    if not num and not cat:
        return {"available": False, "reason": "No usable feature columns were found for this channel."}
    d = df.dropna(subset=["view_count", "like_count", "comment_count"] + num).copy()
    d = d[d["view_count"] > 0]
    if len(d) < YT_MIN_MODELS:
        return {"available": False,
                "reason": f"Only {len(d)} videos have visible views, likes and comments together "
                          f"(the rest have hidden counts, which are never filled with zero). Need {YT_MIN_MODELS}."}
    for c in cat:
        d[c] = d[c].astype("string").fillna("Unknown")
    X = pd.concat([d[num].astype(float),
                   pd.get_dummies(d[cat].astype("string"), drop_first=True).astype(float)], axis=1)
    logged = []
    for c in num:
        if X[c].min() >= 0 and X[c].skew() > 1.5:
            X[c] = np.log1p(X[c])
            logged.append(c)
    assert not (set(X.columns) & YT_LEAK), "Leakage: a target metric is among the features"

    out: dict[str, Any] = {"available": True, "rows_used": int(len(d)), "rows_total": int(len(df)),
                           "features": list(X.columns), "log_scaled_features": logged}
    eng = d["engagement_per_1k_views"]
    out["label_rule"] = (f"HIGH = likes + comments per 1,000 views at or above the median "
                         f"({float(eng.median()):,.1f}).")
    y = (eng >= eng.median()).astype(int)
    if y.value_counts().min() >= 10:
        Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
        clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(Xtr, ytr)
        out["classification"] = {"accuracy": float(accuracy_score(yte, clf.predict(Xte))),
                                 "baseline": float(max(yte.mean(), 1 - yte.mean())),
                                 "train": int(len(Xtr)), "test": int(len(Xte))}
    cols = ["view_count", "like_count", "comment_count", "duration_seconds"]
    cols = [c for c in cols if c in d and d[c].nunique() > 1 and d[c].notna().all()]
    if len(cols) >= 2:
        Z = StandardScaler().fit_transform(np.log1p(d[cols].astype(float).clip(lower=0)))
        km = KMeans(n_clusters=3, n_init=10, random_state=0).fit(Z)
        prof = d[cols].assign(cluster=km.labels_).groupby("cluster").median().round(1)
        prof.insert(0, "posts", pd.Series(km.labels_).value_counts().sort_index())
        prof = prof.sort_values(cols[0])
        out["clustering"] = {"columns": cols,
                             "profile": [{"cluster": f"Group {i + 1}", **{k: float(v) for k, v in r.items()}}
                                         for i, (_, r) in enumerate(prof.iterrows())]}
    y_reg = np.log1p(d["view_count"].astype(float))
    Xtr, Xte, ytr, yte = train_test_split(X, y_reg, test_size=0.25, random_state=42)
    reg = make_pipeline(StandardScaler(), LinearRegression()).fit(Xtr, ytr)
    pred, actual = np.expm1(reg.predict(Xte)), np.expm1(yte)
    out["regression"] = {"r2_log": float(r2_score(yte, reg.predict(Xte))),
                         "mae_model": float(mean_absolute_error(actual, pred)),
                         "mae_baseline": float(mean_absolute_error(actual, np.full(len(actual), np.expm1(ytr).median())))}
    out["notes"] = ["Always compare with a baseline. If a model barely beats it, do not present it as useful.",
                    "Leakage guard: views, likes, comments and anything built from them are excluded from the features.",
                    "Channel subscribers are the same for every video of one channel, so they cannot explain differences between its videos and are not used.",
                    "These are demos on observational data from one channel. They do not show what CAUSES views."]
    return out
