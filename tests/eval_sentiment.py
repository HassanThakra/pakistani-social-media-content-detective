"""Measure the sentiment scorer against comments a PERSON has labelled. This is where the accuracy number comes from.

  1. Get real comments to label (needs YOUTUBE_API_KEY; about 200 units):
         python tests/eval_sentiment.py sample @khaadi 150            -> data/to_label.csv
  2. Open data/to_label.csv in Excel or Sheets. In the `label` column type positive, neutral or negative for each
     comment, as YOU read it (not as you think the scorer will). Save as data/sentiment_labelled.csv. Aim for 100 or more.
  3. Score and report:
         python tests/eval_sentiment.py score                         -> prints the numbers, saves data/sentiment_accuracy.json

Run step 3 with the same SENTIMENT_BACKEND the site will use (lexicon, or model). The Sentiment page shows the saved
figure next to the results, but only if it was measured for the scorer in use.
Label before you look at the scorer's answers, and label comments from more than one channel if you can.
"""
import json
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import comments as cm  # noqa: E402
import sentiment as sn  # noqa: E402
import youtube as yt  # noqa: E402

TO_LABEL, LABELLED = os.path.join(ROOT, "data", "to_label.csv"), os.path.join(ROOT, "data", "sentiment_labelled.csv")


def sample(handle: str, n: int) -> None:
    client = yt.YouTubeClient()
    if not client.configured:
        sys.exit("Set YOUTUBE_API_KEY first.")
    ch = client.channel_info(yt.parse_query(handle))
    got = cm.gather_comments(client, ch["title"], "both", channel=ch, max_videos=20, max_comments_per_video=100)
    df = got["df"]
    if df.empty:
        sys.exit("No usable comments found.")
    df = df.sample(min(n, len(df)), random_state=1)[["text", "language", "source"]].assign(label="")
    df.to_csv(TO_LABEL, index=False, encoding="utf-8-sig")
    print(f"Wrote {len(df)} comments to {TO_LABEL}. Fill the label column, save as {LABELLED}. Units used: {client.units_used}")


def score() -> None:
    if not os.path.exists(LABELLED):
        sys.exit(f"Missing {LABELLED}. See the steps at the top of this file.")
    res = sn.evaluate(pd.read_csv(LABELLED, encoding="utf-8-sig"))
    print(f"scorer: {res['backend']}   labelled comments: {res['n']}   {res['labels']}")
    print(f"accuracy {res['accuracy']:.1%}   always-guess-the-biggest-class baseline {res['baseline']:.1%}   macro-F1 {res['macro_f1']:.2f}")
    print("confusion (rows = human, columns = scorer; order positive, neutral, negative):")
    for lab, row in zip(sn.LABELS, res["confusion"]["matrix"]):
        print(f"  {lab:9s}", row)
    for lg, v in res["by_language"].items():
        print(f"  {lg}: n={v['n']} accuracy {v['accuracy']:.1%}")
    for c in res["caution"]:
        print("CAUTION:", c)
    with open(sn.ACCURACY_FILE, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    print(f"Saved {sn.ACCURACY_FILE}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "sample":
        sample(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 150)
    elif len(sys.argv) == 2 and sys.argv[1] == "score":
        score()
    else:
        print(__doc__)
