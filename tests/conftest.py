"""The sample CSV (data/social_media_sentiment_raw.csv) has no license, so a PUBLIC copy of this repo leaves it out.
Tests that need that file are skipped when it is absent; every other test still runs."""
import inspect
import os

import pytest

CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "social_media_sentiment_raw.csv")
NEEDS_CSV_FILES = ("test_api.py", "test_analysis.py")


def pytest_collection_modifyitems(config, items):
    if os.path.exists(CSV):
        return
    skip = pytest.mark.skip(reason="bundled sample CSV not included (no license); upload-based tests still run")
    for item in items:
        if item.path.name not in NEEDS_CSV_FILES:
            continue
        try:
            src = inspect.getsource(item.function)
        except (OSError, TypeError):
            src = ""
        if "bundled" in src or "raw" in item.fixturenames or "cleaned" in item.fixturenames:
            item.add_marker(skip)
