"""Markdown report for one stored analysis. Built on the server from the cached snapshot,
so a shared link and the download always agree. Every claim comes from the data or is a fixed caveat."""
from __future__ import annotations

import analysis as an
import sentiment as sn


def _n(v, d=0):
    return "–" if v is None else (f"{v:,.{d}f}")


def _esc(s) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def _table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(_esc(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def build_report(entry: dict, scaling: dict, models: dict, explore: dict) -> str:
    ch, snap, rep = entry["channel"], entry["snapshot"], entry["report"]
    df = entry["clean"]
    ov = an.youtube_overview(df)
    L: list[str] = []
    L += [f"# Data Detective report: {ch['title']}", "",
          "**Business question:** Which videos on this channel get attention, and what should it publish or test next?", ""]
    L += ["## 1. Data snapshot", "",
          f"- Source: {snap['source']}",
          f"- Fetched: {snap['fetched_at_utc']}  (live data changes daily; this report describes this fetch only)",
          f"- What was typed: `{snap['query']}`   Channel ID: `{snap['channel_id']}`",
          f"- Videos fetched: {snap['videos_fetched']} (asked for up to {snap['videos_requested']}; the channel lists {_n(snap.get('channel_video_count'))} public videos)",
          f"- Subscribers: {'hidden by the channel' if snap.get('subscribers_hidden') else _n(snap.get('subscribers'))}",
          f"- YouTube API units used: {snap['api_units_used']}", "",
          f"One row is **one public video**. Dates run from {ov['first_published']} to {ov['last_published']}. "
          f"Likes are hidden on {ov['likes_hidden']} videos and comments are off on {ov['comments_off']}; those are kept as missing, not zero.", ""]
    if not ov["enough_for_comparisons"]:
        L += [f"> Only {ov['videos']} videos: too few to compare groups. Treat everything below as description, not evidence.", ""]
    L += ["## 2. Cleaning (on a copy)", ""]
    L += [f"- **{s['title']}.** {s['detail']}" for s in rep["steps"]]
    L += ["", f"Rows: {rep['rows_before']} before, {rep['rows_after']} after cleaning. {rep['note']}", ""]
    L += ["## 3. Exploration", ""]
    if explore:
        g = explore["group"]
        L += [f"Median and mean **{g['metric']}** by **{g['group_col']}** (groups under {g['min_posts']} videos are flagged):", "",
              _table([g["group_col"], "Videos", "Median", "Mean", "Group size"],
                     [[r["group"], r["posts"], _n(r["median"], 1), _n(r["mean"], 1), "few videos" if r["too_few"] else "ok"] for r in g["rows"]]), ""]
        d = explore["dist"]
        if d.get("n"):
            ts = explore.get("top_share")
            L += [f"Spread of {g['metric']}: mean {_n(d['mean'], 1)}, median {_n(d['median'], 1)}, range {_n(d['min'])} to {_n(d['max'])}"
                  + (f". The top 10% of videos hold {ts['share']:.0%} of the total." if ts else "."), ""]
        L += ["Cautions shown by the tool:"] + [f"- {w}" for w in explore["warnings"]] + [""]
    L += ["## 4. What it means: Finding / Evidence / Action / Limitation", ""]
    for i, c in enumerate(an.insights_youtube(df), 1):
        L += [f"### {i}. {c['title']}  _(confidence: {'low, small groups' if c['strength'] == 'weak' else 'ordinary'})_", "",
              f"- **Finding:** {c['finding']}", f"- **Evidence:** {c['evidence']}",
              f"- **Action:** {c['action']}", f"- **Limitation:** {c['limitation']}", ""]
    L += ["## 5. Scaling experiment", ""]
    if scaling:
        L += [_table(["Multiplier", "Rows", "File MB", "Load s", "Analysis s", "Slowest operation", "Memory MB", "Result"],
                     [[r["multiplier"], r["rows"], r.get("file_mb", ""), r.get("load_seconds", ""), r.get("analysis_seconds", ""),
                       r.get("slowest_operation", ""), r.get("memory_mb", ""), "ok" if r["status"] == "ok" else "skipped"]
                      for r in scaling["results"]]), "", f"_{scaling['note']}_", ""]
    else:
        L += ["_Not run._", ""]
    L += ["## 6. Models preview", ""]
    if models and models.get("available"):
        if models.get("classification"):
            c = models["classification"]
            L.append(f"- Classification (high vs low engagement per 1,000 views): {c['accuracy']:.0%} test accuracy vs {c['baseline']:.0%} for always guessing the bigger class.")
        if models.get("regression"):
            r = models["regression"]
            L.append(f"- Regression (views): off by {_n(r['mae_model'])} views on average vs {_n(r['mae_baseline'])} for guessing the median (R² on log scale {r['r2_log']:.2f}).")
        if models.get("clustering"):
            L.append(f"- Clustering: three video profiles on {', '.join(models['clustering']['columns'])}.")
        L += ["", models["label_rule"], "", *[f"- {n}" for n in models["notes"]], ""]
    else:
        L += [f"_{(models or {}).get('reason', 'Not run.')}_", ""]
    com = entry.get("comments")
    if com is not None and len(com["df"]):
        sm = sn.summarize(com["df"])
        o, pr = sm["overall"], com["params"]
        L += ["## 7. Comment sentiment", "",
              f"- Collected: {com['snapshot']['fetched_at_utc']}; source: {pr['source']}; up to {pr['max_videos']} videos and {pr['max_comments']} comments per video"
              + (f"; comments from {pr['date_from'] or 'the start'} to {pr['date_to'] or 'today'}" if pr['date_from'] or pr['date_to'] else ""),
              f"- Comments scored: {sm['n']} (from {sm['first_comment']} to {sm['last_comment']}). Scorer: {com['scoring']['note']}",
              f"- Positive {o['positive']:.0%}, neutral {o['neutral']:.0%}, negative {o['negative']:.0%}; net sentiment {o['net'] * 100:+.0f} points.", "",
              _table(["Group", "Comments", "Positive", "Neutral", "Negative", "Note"],
                     [[x["group"], x["n"], f"{x['positive']:.0%}", f"{x['neutral']:.0%}", f"{x['negative']:.0%}",
                       "few comments" if x["few"] else "ok"] for x in sm["by_source"] + sm["by_language"]]), ""]
        if sm["topics"]:
            L += ["What people mention (a comment can mention several topics):", "",
                  _table(["Topic", "Comments", "Positive", "Negative", "Net", "Note"],
                         [[t["topic"], t["n"], f"{t['positive']:.0%}", f"{t['negative']:.0%}", f"{t['net'] * 100:+.0f}",
                           "few comments" if t["few"] else "ok"] for t in sm["topics"]]), ""]
        L += ["Cautions:"] + [f"- {w}" for w in sm["warnings"]] + [""]
    L += ["---", "",
          "Caveats: views are not reach, and nothing here is an engagement rate on reach. Hidden counts are missing, not zero. "
          "Repeated rows in the scaling experiment are not new evidence. Only public YouTube data was used. Comment text, when collected, was kept in memory for this analysis only, with no author names.",
          f"Video links: https://www.youtube.com/channel/{snap['channel_id']}"]
    return "\n".join(L)
