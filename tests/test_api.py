"""Tests for the Flask API (app.py), using the bundled real dataset."""
import io
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as appmod  # noqa: E402


@pytest.fixture()
def client():
    appmod.app.config.update(TESTING=True)
    appmod._hits.clear()
    appmod._cache.clear()
    return appmod.app.test_client()


def post(client, path, **fields):
    return client.post(path, data=fields, content_type="multipart/form-data")


def csv_file(text, name="x.csv"):
    return (io.BytesIO(text.encode()), name)


def test_health_and_config(client):
    assert client.get("/healthz").get_json() == {"ok": True}
    cfg = client.get("/api/config").get_json()
    assert cfg["max_upload_mb"] == 10 and cfg["cache_minutes"] == 15 and "repo_fetch" not in cfg


def test_home_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and b"Data Detective" in r.data
    assert r.headers["Cache-Control"] == "no-cache"


def test_security_headers(client):
    r = client.get("/")
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    assert client.get("/api/config").headers["Cache-Control"] == "no-store"


def test_inspect_bundled_real_data(client):
    d = post(client, "/api/inspect", source="bundled").get_json()
    p = d["profile"]
    assert "Bundled dataset" in d["label"] and "synthetic" not in d
    assert (p["rows"], p["columns"], p["exact_duplicates"]) == (2260, 13, 44)
    assert p["provenance"]["looks_templated"] is True


def test_clean_defaults_to_instagram_focus(client):
    d = post(client, "/api/clean", source="bundled").get_json()
    assert d["report"]["rows_after"] == 2200
    assert d["focus"] == {"col": "platform", "val": "Instagram", "rows": 595, "of": 2200}
    assert d["default_focus"]["val"] == "Instagram" and "timestamp" in d["roles"]["dates"]


def test_clean_with_no_focus_means_all_rows(client):
    d = post(client, "/api/clean", source="bundled", focus_col="", focus_val="").get_json()
    assert d["focus"]["rows"] == 2200 and d["focus"]["col"] is None


def test_explore_matches_the_analysis_layer(client):
    d = post(client, "/api/explore", source="bundled", focus_col="platform", focus_val="Instagram", apply_focus="1",
             group_col="sentiment", metric="comments", min_posts="30", x="likes", y="comments", dt_col="timestamp").get_json()
    assert d["rows_used"] == 595
    assert [r["group"] for r in d["group"]["rows"]] == ["Positive", "Neutral", "Negative"]
    assert d["scatter"]["spearman"] == pytest.approx(0.515, abs=0.01)


def test_explore_all_rows_when_focus_off(client):
    d = post(client, "/api/explore", source="bundled", focus_col="platform", focus_val="Instagram", apply_focus="0",
             group_col="platform", metric="likes", min_posts="30").get_json()
    assert d["rows_used"] == 2200 and len(d["group"]["rows"]) == 5


@pytest.mark.parametrize("fields,msg", [
    (dict(group_col="user", metric="likes"), "too many"),
    (dict(group_col="nope", metric="likes"), "valid"),
    (dict(group_col="platform", metric="likes", min_posts="abc"), "whole number"),
    (dict(group_col="platform", metric="likes", focus_col="platform", focus_val="MySpace", apply_focus="1"), "No rows"),
])
def test_explore_errors_are_clear(client, fields, msg):
    r = post(client, "/api/explore", source="bundled", **fields)
    assert r.status_code == 400 and msg in r.get_json()["error"]


def test_scaling_endpoint_and_server_limit(client, monkeypatch):
    monkeypatch.setattr(appmod, "SCALING_MAX_ROWS", 30_000)
    d = post(client, "/api/scaling", source="bundled", factors="1,10,100", group_col="platform", metrics="likes,comments").get_json()
    by = {x["multiplier"]: x["status"] for x in d["results"]}
    assert by == {"1x": "ok", "10x": "ok", "100x": "skipped"}


@pytest.mark.parametrize("factors", ["abc", "0", "-5", "999999999", ""])
def test_scaling_rejects_bad_factors(client, factors):
    assert post(client, "/api/scaling", source="bundled", factors=factors, group_col="platform", metrics="likes").status_code == 400


def test_models_endpoint(client):
    d = post(client, "/api/models", source="bundled").get_json()
    assert d["available"] and d["classification"]["accuracy"] > d["classification"]["baseline"]


def test_upload_works_and_is_labelled(client):
    text = "platform,likes,comments\n" + "\n".join(f"{'AB'[i % 2]},{i % 9},{i % 4}" for i in range(60)) + "\n"
    r = client.post("/api/inspect", data={"source": "upload", "file": csv_file(text, "mine.csv")}, content_type="multipart/form-data")
    d = r.get_json()
    assert r.status_code == 200 and d["label"] == "Your file: mine.csv" and d["profile"]["rows"] == 60


def test_upload_filename_cannot_inject_paths_or_html(client):
    text = "a,b\n1,2\n3,4\n"
    r = client.post("/api/inspect", data={"source": "upload", "file": csv_file(text, "../../etc/<img src=x>.csv")},
                    content_type="multipart/form-data")
    assert r.status_code == 200 and "/" not in r.get_json()["label"].split(": ", 1)[1]


@pytest.mark.parametrize("payload,msg", [
    (None, "Choose a CSV"),
    ("", "empty"),
    ("a,b\n", "no data rows"),
    ("just_one\n1\n2\n", "one column"),
])
def test_upload_errors(client, payload, msg):
    data = {"source": "upload"}
    if payload is not None:
        data["file"] = csv_file(payload)
    r = client.post("/api/inspect", data=data, content_type="multipart/form-data")
    assert r.status_code == 400 and msg in r.get_json()["error"]


def test_binary_garbage_is_rejected_without_a_crash(client):
    r = client.post("/api/inspect", data={"source": "upload", "file": (io.BytesIO(os.urandom(500)), "x.csv")},
                    content_type="multipart/form-data")
    assert r.status_code == 400 and "error" in r.get_json()


def test_unknown_source_and_unknown_route(client):
    assert post(client, "/api/inspect", source="nope").status_code == 400
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and "error" in r.get_json()


def test_oversize_upload_gets_413(client):
    appmod.app.config["MAX_CONTENT_LENGTH"] = 2000
    try:
        big = "a,b\n" + "1,2\n" * 2000
        r = client.post("/api/inspect", data={"source": "upload", "file": csv_file(big)}, content_type="multipart/form-data")
        assert r.status_code == 413 and "limit" in r.get_json()["error"]
    finally:
        appmod.app.config["MAX_CONTENT_LENGTH"] = appmod.MAX_UPLOAD_MB * 1024 * 1024


def test_row_limit_message(client, monkeypatch):
    monkeypatch.setattr(appmod, "MAX_ROWS", 100)
    r = post(client, "/api/inspect", source="bundled")
    assert r.status_code == 400 and "more than 100 rows" in r.get_json()["error"]


def test_rate_limit_returns_a_friendly_error(client, monkeypatch):
    monkeypatch.setattr(appmod, "HEAVY_LIMIT_PER_MIN", 2)
    codes = [post(client, "/api/models", source="bundled").status_code for _ in range(3)]
    assert codes == [200, 200, 400]
    assert "Too many requests" in post(client, "/api/models", source="bundled").get_json()["error"]


def test_cached_data_expires(client, monkeypatch):
    post(client, "/api/inspect", source="bundled")
    assert len(appmod._cache) == 1
    monkeypatch.setattr(appmod, "CACHE_TTL_SECONDS", 0)
    time.sleep(0.01)
    post(client, "/api/inspect", source="bundled")          # purges the stale entry, then re-adds one
    assert len(appmod._cache) == 1 and all(time.time() - v["t"] < 5 for v in appmod._cache.values())


def test_cache_is_bounded(client):
    for i in range(appmod.CACHE_SIZE + 3):
        text = "platform,likes,comments\n" + "\n".join(f"A,{i + j},{j}" for j in range(20)) + "\n"
        client.post("/api/inspect", data={"source": "upload", "file": csv_file(text)}, content_type="multipart/form-data")
    assert len(appmod._cache) <= appmod.CACHE_SIZE
