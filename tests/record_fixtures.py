"""Record REAL API responses (needs your key). Usage:  YOUTUBE_API_KEY=... python tests/record_fixtures.py @handle
Saves tests/fixtures/recorded/<handle>.json with the key scrubbed. Costs about 1 + 2*ceil(n/50) quota units."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import youtube as yt

def main():
    if len(sys.argv) < 2:
        sys.exit("usage: record_fixtures.py @handle_or_channel_id")
    log = []
    real = yt._default_http
    def rec(url):
        status, body = real(url)
        scrubbed = yt.urllib.parse.urlparse(url)._replace(query="&".join(p for p in yt.urllib.parse.urlparse(url).query.split("&") if not p.startswith("key="))).geturl()
        log.append({"url": scrubbed, "status": status, "body": body})
        return status, body
    client = yt.YouTubeClient(http=rec)
    res = yt.fetch_channel_snapshot(client, yt.parse_query(sys.argv[1]), 100)
    os.makedirs("tests/fixtures/recorded", exist_ok=True)
    path = f"tests/fixtures/recorded/{sys.argv[1].strip('@')}.json"
    json.dump(log, open(path, "w"), indent=1)
    print("saved", path, "units used:", client.units_used, "videos:", len(res["df"]))
main()
