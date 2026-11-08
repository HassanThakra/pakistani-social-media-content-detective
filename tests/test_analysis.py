"""Tests for analysis.py. The golden numbers come from the bundled real dataset."""
import io
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analysis as an  # noqa: E402

CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "social_media_sentiment_raw.csv")


@pytest.fixture(scope="module")
def raw():
    with open(CSV, "rb") as f:
        return an.read_csv_bytes(f.read())


@pytest.fixture(scope="module")
def cleaned(raw):
    return an.clean(raw)


# ------------------------------------------------------------------ reading files
def test_real_file_shape(raw):
    assert raw.shape == (2260, 13)
    assert list(raw.columns)[:3] == ["post_id", "timestamp", "platform"]


@pytest.mark.parametrize("data,msg", [
    (b"", "empty"),
    (b"   \n", "empty"),
    (b"a,b\n", "no data rows"),
    (b"only\n1\n2\n", "one column"),
])
def test_bad_files_give_clear_errors(data, msg):
    with pytest.raises(an.UserError, match=msg):
        an.read_csv_bytes(data)


def test_row_limit_is_enforced():
    big = ("a,b\n" + "\n".join(f"{i},{i}" for i in range(50))).encode()
    with pytest.raises(an.UserError, match="more than 10 rows"):
        an.read_csv_bytes(big, max_rows=10)


def test_latin1_files_are_read():
    df = an.read_csv_bytes("name,likes\ncaf\xe9,3\nbar,4\n".encode("latin-1"))
    assert df.shape == (2, 2)


# ------------------------------------------------------------------ profile
def test_profile_finds_the_known_problems(raw):
    p = an.profile(raw)
    assert p["rows"] == 2260 and p["columns"] == 13
    assert p["exact_duplicates"] == 44
    text = " ".join(i["text"] for i in p["issues"])
    assert "negative" in text and "spellings" in text and "stored as text" in text
    kinds = {c["name"]: c["kind"] for c in p["cols"]}
    assert kinds["followers_count"] == "numerical"
    assert kinds["timestamp"] == "date/time"
    assert kinds["platform"] == "categorical"
    assert kinds["text"] == "text"
    assert kinds["post_id"] == "identifier"


def test_provenance_flags_repetitive_text(raw):
    pv = an.profile(raw)["provenance"]
    assert pv["distinct_texts"] == 150
    assert pv["looks_templated"] is True


# ------------------------------------------------------------------ cleaning
def test_cleaning_the_real_file(cleaned):
    c, rep = cleaned
    assert rep["rows_before"] == 2260 and rep["rows_after"] == 2200
    assert rep["duplicates_removed"] == 60 and rep["exact_duplicates_raw"] == 44
    assert sorted(c["platform"].dropna().unique()) == ["Facebook", "Instagram", "LinkedIn", "TikTok", "Twitter"]
    assert c["country"].nunique() == 12
    assert pd.api.types.is_numeric_dtype(c["followers_count"])
    assert pd.api.types.is_datetime64_any_dtype(c["timestamp"])
    assert rep["negatives_to_missing"] == {"likes": 8}
    assert (c["likes"].dropna() >= 0).all()
    assert not c["post_id"].duplicated().any()


def test_missing_is_never_turned_into_zero(raw, cleaned):
    c, _ = cleaned
    assert c["comments"].isna().sum() > 0                       # blanks stay blank
    both = c.dropna(subset=["likes", "comments", "retweets_shares"])
    assert (c.loc[c["comments"].isna(), "total_engagement"].isna()).all()
    assert len(both) < len(c)


def test_negative_likes_become_missing_not_zero():
    df = pd.DataFrame({"platform": ["a", "b", "c"], "likes": [5, -1, 7], "comments": [1, 2, 3]})
    c, rep = an.clean(df)
    assert pd.isna(c.loc[1, "likes"])
    assert rep["negatives_to_missing"] == {"likes": 1}


def test_spellings_unify_to_the_most_common():
    df = pd.DataFrame({"platform": ["Twitter"] * 5 + ["TWITTER", "twitter  ", "Facebook", "Facebook"], "likes": range(9)})
    c, rep = an.clean(df)
    assert set(c["platform"].unique()) == {"Twitter", "Facebook"}
    assert rep["spelling_merges"]["platform"] == {"before": 4, "after": 2}


def test_duplicates_that_differ_only_in_case_are_removed():
    df = pd.DataFrame({"platform": ["Twitter", "TWITTER", "Facebook"], "likes": [1, 1, 2], "comments": [0, 0, 1]})
    c, rep = an.clean(df)
    assert len(c) == 2 and rep["duplicates_removed"] == 1 and rep["exact_duplicates_raw"] == 0


def test_text_numbers_with_commas_convert():
    df = pd.DataFrame({"followers_count": ["1,125", "668.0", None, "20"], "likes": [1, 2, 3, 4]})
    c, _ = an.clean(df)
    assert c["followers_count"].tolist()[:2] == [1125.0, 668.0] and pd.isna(c["followers_count"][2])


def test_original_dataframe_is_not_modified(raw):
    before = raw.copy()
    an.clean(raw)
    pd.testing.assert_frame_equal(raw, before)


# ------------------------------------------------------------------ explore
def test_instagram_focus_and_group_table(cleaned):
    c, _ = cleaned
    ig = an.apply_focus(c, "platform", "Instagram")
    assert len(ig) == 595
    t = an.group_table(ig, "sentiment", "comments", min_posts=30)
    rows = {r["group"]: r for r in t["rows"]}
    assert {k: v["posts"] for k, v in rows.items()} == {"Positive": 216, "Neutral": 184, "Negative": 170}
    assert rows["Positive"]["median"] == 4.0 and rows["Neutral"]["median"] == 3.0
    assert t["excluded_missing_group"] == 9
    assert not any(r["too_few"] for r in t["rows"])


def test_small_groups_are_flagged(cleaned):
    c, _ = cleaned
    ig = an.apply_focus(c, "platform", "Instagram")
    t = an.group_table(ig, "country", "likes", 30)
    assert any(r["too_few"] for r in t["rows"])


def test_explore_bundle_and_cautions(cleaned):
    c, _ = cleaned
    ig = an.apply_focus(c, "platform", "Instagram")
    out = an.explore(ig, list(c.columns), "sentiment", "comments", 30, "likes", "comments", "timestamp")
    assert out["scatter"]["spearman"] == pytest.approx(0.515, abs=0.01)
    assert len(out["weekday"]["rows"]) == 7
    assert out["top_share"]["share"] == pytest.approx(0.27, abs=0.02)
    assert any("no reach or impressions" in w.lower() for w in out["warnings"])


def test_explore_rejects_bad_columns(cleaned):
    c, _ = cleaned
    with pytest.raises(an.UserError):
        an.explore(c, list(c.columns), "nope", "likes", 30, None, None, None)
    with pytest.raises(an.UserError, match="too many"):
        an.explore(c, list(c.columns), "user", "likes", 30, None, None, None)


def test_unknown_focus_value_is_an_error(cleaned):
    with pytest.raises(an.UserError):
        an.apply_focus(cleaned[0], "platform", "MySpace")


def test_jsonable_removes_nan_and_numpy():
    out = an.jsonable({"a": np.int64(3), "b": float("nan"), "c": [np.float64(1.5), pd.NA], "d": np.bool_(True)})
    assert out == {"a": 3, "b": None, "c": [1.5, None], "d": True}


# ------------------------------------------------------------------ scaling
def test_scaling_runs_and_respects_limits(cleaned):
    c, _ = cleaned
    r = an.run_scaling(c, "platform", ["likes", "comments"], [1, 10, 1000], max_rows=50_000, repeats=1)
    by = {x["multiplier"]: x for x in r["results"]}
    assert by["1x"]["status"] == "ok" and by["1x"]["rows"] == 2200
    assert by["10x"]["rows"] == 22000 and by["10x"]["file_mb"] > by["1x"]["file_mb"]
    assert by["1000x"]["status"] == "skipped" and "limit" in by["1000x"]["reason"]
    assert "not new real-world evidence" in r["note"]


def test_scaling_rejects_missing_columns(cleaned):
    with pytest.raises(an.UserError):
        an.run_scaling(cleaned[0], "nope", ["likes"], [1], 1000)
    with pytest.raises(an.UserError):
        an.run_scaling(cleaned[0], "platform", ["nope"], [1], 1000)


# ------------------------------------------------------------------ models
def test_models_beat_their_baselines_and_never_leak(cleaned):
    c, _ = cleaned
    m = an.run_models(c)
    assert m["available"]
    leak = {"likes", "comments", "retweets_shares", "total_engagement", "engagement_per_1k_followers"}
    assert not leak & set(m["features"])
    assert m["classification"]["accuracy"] > m["classification"]["baseline"] + 0.05
    assert m["regression"]["mae_model"] < m["regression"]["mae_baseline"]
    assert len(m["clustering"]["profile"]) == 3
    assert "followers_count" in m["log_scaled_features"]


def test_models_explain_when_columns_are_missing():
    m = an.run_models(pd.DataFrame({"a": range(300), "b": range(300)}))
    assert m["available"] is False and "likes" in m["reason"]
