"""Start the real app with a FAKE YouTube API (no key, no network) for browser tests.
    PORT=8766 python tests/serve_fake.py
The numbers behind it are invented test data; see tests/yt_fixtures.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as appmod  # noqa: E402
import yt_fixtures as fx  # noqa: E402
import youtube as yt  # noqa: E402

N = int(os.environ.get("FAKE_VIDEOS", "120"))
appmod.make_client = lambda: yt.YouTubeClient("fake-key", http=fx.fake_http(N))
appmod.FETCH_LIMIT_PER_MIN = 100
appmod.FETCH_LIMIT_PER_HOUR = 1000
appmod.app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8766")), debug=False)
