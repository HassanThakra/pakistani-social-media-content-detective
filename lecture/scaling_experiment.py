#!/usr/bin/env python3
"""
Big Data Analytics, Project 1 · Step 8: scaling experiment

Runs the SAME simple analysis on your CSV, then on repeated copies of it
(1x, 10x, 100x, and optionally 1000x), and records how long loading and
analysis take, how big the file is, and how much memory the data uses.

IMPORTANT: repeated copies are a scaling experiment, NOT new real-world evidence.
Repeated rows are also easier for a computer than varied real data, so treat the
timings as a rough guide.

Pandas may handle millions of rows on some computers. There is no universal row
count at which it "fails". The need for Spark or distributed systems depends on
data size, the operation, hardware, and service requirements.

Examples
    python scaling_experiment.py --csv data/social_media_sentiment_raw.csv
    python scaling_experiment.py --csv data/social_media_sentiment_raw.csv --include-1000x
    python scaling_experiment.py --csv mydata.csv --group-col platform --metrics likes comments
"""
import argparse
import os
import sys
import tempfile
import time

import pandas as pd


# ----------------------------------------------------------------- helpers
def process_peak_mb():
    """Peak memory used by this whole process so far, in MB (None if unavailable)."""
    try:
        import resource
    except ImportError:                      # Windows has no `resource` module
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1e6 if sys.platform == "darwin" else peak / 1e3   # macOS: bytes, Linux: KB


def available_mb():
    """Free memory in MB if psutil is installed, otherwise None."""
    try:
        import psutil
    except ImportError:
        return None
    return psutil.virtual_memory().available / 1e6


def prepare(base, group_col, metrics):
    """Light cleaning so the analysis runs. Missing values stay missing."""
    base = base.copy()
    for c in metrics:
        base[c] = pd.to_numeric(base[c], errors="coerce")
    base[group_col] = base[group_col].astype("string").str.strip().str.title()
    return base


def pick_columns(df, group_col, metrics):
    """Use the requested columns if they exist; otherwise choose sensible ones and say so."""
    if group_col not in df.columns:
        candidates = [c for c in df.columns
                      if not pd.api.types.is_numeric_dtype(df[c]) and 1 < df[c].nunique() <= 50]
        if not candidates:
            sys.exit(f"Column '{group_col}' not found and no suitable text column to group by. "
                     f"Columns: {list(df.columns)}")
        print(f"NOTE: '{group_col}' not found; grouping by '{candidates[0]}' instead.")
        group_col = candidates[0]
    found = [m for m in metrics if m in df.columns]
    if len(found) < len(metrics):
        numeric = [c for c in df.columns
                   if pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.9 and c not in found]
        found = (found + numeric)[:max(2, len(found))]
        print(f"NOTE: using metric columns {found}")
    if not found:
        sys.exit("No numeric metric columns found. Use --metrics to name them.")
    return group_col, found


def make_operations(group_col, metrics):
    """The same set of simple operations is timed at every size."""
    ops = {
        "groupby count/mean/median": lambda f: f.groupby(group_col)[metrics].agg(["count", "mean", "median"]),
        "describe": lambda f: f[metrics].describe(),
        "sort and take top 10": lambda f: f.sort_values(metrics[0], ascending=False).head(10),
        "value counts": lambda f: f[group_col].value_counts(),
    }
    if len(metrics) >= 2:
        ops["correlation"] = lambda f: f[metrics].corr()
    return ops


def time_operations(frame, ops, repeats):
    """Best-of-N seconds for each operation (best-of reduces timing noise)."""
    out = {}
    for name, fn in ops.items():
        best = float("inf")
        for _ in range(repeats):
            t0 = time.perf_counter()
            fn(frame)
            best = min(best, time.perf_counter() - t0)
        out[name] = best
    return out


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Project 1 scaling experiment (Step 8)")
    ap.add_argument("--csv", required=True, help="path to your CSV (the original; it is never modified)")
    ap.add_argument("--group-col", default="platform", help="categorical column to group by")
    ap.add_argument("--metrics", nargs="+", default=["likes", "comments"], help="numeric columns to analyse")
    ap.add_argument("--factors", nargs="+", type=int, default=[1, 10, 100], help="row multipliers")
    ap.add_argument("--include-1000x", action="store_true",
                    help="also run 1000x (about 2 million rows); needs several GB of free memory")
    ap.add_argument("--repeats", type=int, default=3, help="repeat each timing and keep the best")
    ap.add_argument("--output", default="scaling_results.csv", help="where to save the results table")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        sys.exit(f"File not found: {args.csv}")

    raw = pd.read_csv(args.csv)
    group_col, metrics = pick_columns(raw, args.group_col, args.metrics)
    base = prepare(raw, group_col, metrics)
    base_mb = base.memory_usage(deep=True).sum() / 1e6
    print(f"Base data: {len(base):,} rows, {base.shape[1]} columns, {base_mb:.1f} MB in memory")
    print(f"Grouping by '{group_col}', metrics {metrics}\n")

    factors = list(args.factors)
    if args.include_1000x and 1000 not in factors:
        factors.append(1000)

    ops = make_operations(group_col, metrics)
    results = []
    for factor in factors:
        # A scaled copy, the saved CSV and the reloaded copy can all exist at once.
        needed_mb = base_mb * factor * 3
        free_mb = available_mb()
        if free_mb is not None and needed_mb > 0.7 * free_mb:
            print(f"SKIPPED {factor}x: needs about {needed_mb:,.0f} MB but only {free_mb:,.0f} MB is free. "
                  f"That is a real result too: this workflow does not fit on this machine at this size.")
            results.append({"multiplier": f"{factor}x", "rows": len(base) * factor, "status": "skipped (memory)"})
            continue

        print(f"Running {factor}x ...", flush=True)
        big = pd.concat([base] * factor, ignore_index=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scaled.csv")
            big.to_csv(path, index=False)
            file_mb = os.path.getsize(path) / 1e6
            del big
            t0 = time.perf_counter()
            loaded = pd.read_csv(path)
            load_s = time.perf_counter() - t0

        loaded = prepare(loaded, group_col, metrics)
        per_op = time_operations(loaded, ops, args.repeats)
        slowest = max(per_op, key=per_op.get)
        peak = process_peak_mb()
        results.append({
            "multiplier": f"{factor}x",
            "rows": len(loaded),
            "file_mb": round(file_mb, 1),
            "load_seconds": round(load_s, 3),
            "analysis_seconds": round(sum(per_op.values()), 4),
            "slowest_operation": slowest,
            "data_memory_mb": round(loaded.memory_usage(deep=True).sum() / 1e6, 1),
            "process_peak_mb": round(peak, 1) if peak is not None else "n/a",
            "status": "ok",
        })
        del loaded

    table = pd.DataFrame(results)
    print("\n=== Scaling results (repeated copies of the same data) ===")
    print(table.to_string(index=False))
    table.to_csv(args.output, index=False)
    print(f"\nSaved: {args.output}")

    print("""
Notes for your report
- Repeated copies are a scaling experiment, not new real-world evidence.
- 'data_memory_mb' is pandas' own estimate for the table; it can differ from what the operating
  system reports. 'process_peak_mb' is the highest memory this whole process has used so far,
  so it only goes up. Use both as rough guides, not exact measurements.
- Timings change between runs and between computers. Run it twice and compare.
- Which operation became slowest or most inconvenient? Did the data still fit in memory?
- There is no universal row count at which pandas fails. Say what YOUR results show,
  then describe what would change at 100 GB, with data arriving continuously, or with a team sharing it.""")


if __name__ == "__main__":
    main()
