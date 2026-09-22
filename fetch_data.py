import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, date
from pytrends.request import TrendReq

# ── FRED API ──────────────────────────────────────────────────────────────────
FRED_API_KEY = os.environ["FRED_API_KEY"]
FRED_BASE    = "https://api.stlouisfed.org/fred/series/observations"

def fetch_fred(series_id, start_date="2016-01-01"):
    """Fetch a FRED series from start_date to today, all observations."""
    params = {
        "series_id":         series_id,
        "api_key":           FRED_API_KEY,
        "file_type":         "json",
        "sort_order":        "asc",
        "observation_start": start_date,
    }
    r = requests.get(FRED_BASE, params=params)
    r.raise_for_status()
    obs = r.json()["observations"]
    # drop missing values (FRED marks them as ".")
    return [
        {"date": o["date"], "value": float(o["value"])}
        for o in obs if o["value"] != "."
    ]

# ── GOOGLE TRENDS ─────────────────────────────────────────────────────────────
def fetch_trends(keyword="pest control near me", geo="US", start_year=2016):
    """
    Fetch weekly Google Trends from start_year to today.

    pytrends caps a single request at ~5 years for weekly resolution.
    We split into overlapping 2-year blocks and stitch them together,
    using the overlap to re-scale each block to the same index base
    (the same approach Google's own CSV export uses internally).
    """
    pytrends = TrendReq(hl="en-US", tz=300)

    today      = date.today()
    block_yrs  = 2          # each pull = 2 years of weekly data
    overlap_wk = 4          # weeks of overlap for stitching

    # Build date windows: [start, end] pairs stepping by ~2 years
    windows = []
    y = start_year
    while True:
        w_start = date(y, 1, 1)
        w_end   = date(min(y + block_yrs, today.year + 1), 1, 1)
        if w_end > today:
            w_end = today
        windows.append((w_start, w_end))
        if w_end >= today:
            break
        y += block_yrs

    all_series = {}   # date_str -> value (float, will re-scale)

    prev_tail = None  # last `overlap_wk` rows of the previous block

    for i, (ws, we) in enumerate(windows):
        tf = f"{ws.strftime('%Y-%m-%d')} {we.strftime('%Y-%m-%d')}"
        print(f"  Trends block {i+1}/{len(windows)}: {tf}")

        for attempt in range(4):
            try:
                pytrends.build_payload([keyword], cat=0, timeframe=tf, geo=geo)
                df = pytrends.interest_over_time()
                break
            except Exception as e:
                wait = 15 * (attempt + 1)
                print(f"    Retry {attempt+1} after {wait}s ({e})")
                time.sleep(wait)
        else:
            print(f"  Skipping block {i+1} after 4 failed attempts.")
            continue

        if df.empty:
            continue

        df = df.reset_index()[["date", keyword]].copy()
        df["date"] = df["date"].dt.date

        if prev_tail is not None and not df.empty:
            # Find overlap rows present in both blocks
            overlap_dates = set(prev_tail["date"]) & set(df["date"])
            if overlap_dates:
                prev_vals = prev_tail[prev_tail["date"].isin(overlap_dates)][keyword].mean()
                curr_vals = df[df["date"].isin(overlap_dates)][keyword].mean()
                if curr_vals > 0:
                    scale = prev_vals / curr_vals
                    df[keyword] = df[keyword] * scale

        # Merge into master dict (prefer later block for overlap dates)
        for _, row in df.iterrows():
            all_series[str(row["date"])] = float(row[keyword])

        # Save tail for next block's overlap
        tail_start = we - pd.Timedelta(weeks=overlap_wk)
        prev_tail  = df[df["date"] >= tail_start].copy()

        time.sleep(2)   # be polite to pytrends

    if not all_series:
        return []

    # Sort by date, clamp to 0–100
    sorted_dates = sorted(all_series)
    values       = [all_series[d] for d in sorted_dates]
    max_val      = max(values) if values else 1
    scaled       = [round(v / max_val * 100, 1) for v in values]

    return [{"date": d, "value": s} for d, s in zip(sorted_dates, scaled)]


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    data = {}

    print("Fetching Google Trends (2016 → today, weekly blocks)...")
    data["google_trends"] = fetch_trends()
    print(f"  → {len(data['google_trends'])} weekly observations")

    print("Fetching Housing Starts (FRED: HOUST, 2016→today)...")
    data["housing_starts"] = fetch_fred("HOUST", start_date="2016-01-01")
    print(f"  → {len(data['housing_starts'])} monthly observations")

    print("Fetching Restaurant Sales (FRED: RSAFS, 2016→today)...")
    data["restaurant_sales"] = fetch_fred("RSAFS", start_date="2016-01-01")
    print(f"  → {len(data['restaurant_sales'])} monthly observations")

    data["last_updated"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    with open("data.json", "w") as f:
        json.dump(data, f, indent=2)

    print(f"\nDone. data.json written. Last updated: {data['last_updated']}")

if __name__ == "__main__":
    main()
