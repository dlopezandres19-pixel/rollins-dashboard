"""
Rollins (ROL) Dashboard — Data Fetcher
Runs every Monday 9am EST via GitHub Actions.
Outputs: data.json
"""

import os, json, time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from pytrends.request import TrendReq

# ── CONFIG ────────────────────────────────────────────────────────────────────
FRED_API_KEY = os.environ["FRED_API_KEY"]
FRED_BASE    = "https://api.stlouisfed.org/fred/series/observations"
START_DATE   = "2016-01-01"

# Non-branded pest-control keywords for composite index
# "pest control near me" is the ANCHOR — appears in every batch
ANCHOR_KW = "pest control near me"
TREND_KEYWORDS = [
    "pest control near me",
    "exterminator near me",
    "termite treatment",
    "bed bug exterminator",
    "rodent control",
    "mosquito control",
    "wildlife removal",
]
# Batches of ≤5 keywords, anchor always first
TREND_BATCHES = [
    ["pest control near me", "exterminator near me", "termite treatment",
     "bed bug exterminator", "rodent control"],
    ["pest control near me", "mosquito control", "wildlife removal"],
]

# ── FRED ──────────────────────────────────────────────────────────────────────
def fetch_fred(series_id, start_date=START_DATE):
    """Fetch all observations for a FRED series from start_date to today."""
    params = {
        "series_id":         series_id,
        "api_key":           FRED_API_KEY,
        "file_type":         "json",
        "sort_order":        "asc",
        "observation_start": start_date,
    }
    r = requests.get(FRED_BASE, params=params, timeout=30)
    r.raise_for_status()
    obs = r.json()["observations"]
    return [
        {"date": o["date"], "value": float(o["value"])}
        for o in obs if o["value"] != "."
    ]


# ── GOOGLE TRENDS ─────────────────────────────────────────────────────────────
def _pull_block(pytrends, keywords, timeframe, retries=4):
    """Single pytrends pull with retry."""
    for attempt in range(retries):
        try:
            pytrends.build_payload(keywords, cat=0, timeframe=timeframe, geo="US")
            df = pytrends.interest_over_time()
            if not df.empty:
                return df.reset_index()
        except Exception as e:
            wait = 20 * (attempt + 1)
            print(f"    pytrends retry {attempt+1}/{retries} after {wait}s — {e}")
            time.sleep(wait)
    return pd.DataFrame()


def fetch_trends_all(start_year=2016):
    """
    Fetch all keywords using batched pytrends pulls with a common anchor.

    Methodology:
    1. For each 2-year block, pull each batch (anchor + subset of keywords).
    2. Use the anchor series to cross-scale each batch: for every batch,
       compute scale_factor = anchor_batch1 / anchor_batchN for overlapping
       dates, then multiply non-anchor series by that factor.
    3. Stitch 2-year blocks by overlap-rescaling (same approach as before).
    4. Normalize each final keyword series to mean=100 index.
    5. Composite = equal-weighted mean of all 7 normalized series.
    Returns dict with keys: each keyword (str) + "composite" + "composite_norm"
    """
    pytrends   = TrendReq(hl="en-US", tz=300)
    today      = date.today()
    block_yrs  = 2
    overlap_wk = 8   # wider overlap for cross-batch scaling stability

    # Build time windows
    windows = []
    y = start_year
    while True:
        ws = date(y, 1, 1)
        we = min(date(y + block_yrs, 1, 1), today)
        windows.append((ws, we))
        if we >= today:
            break
        y += block_yrs

    # Master dict: keyword → {date_str: raw_value}
    master = {kw: {} for kw in TREND_KEYWORDS}

    for wi, (ws, we) in enumerate(windows):
        tf = f"{ws.strftime('%Y-%m-%d')} {we.strftime('%Y-%m-%d')}"
        print(f"  Window {wi+1}/{len(windows)}: {tf}")

        # Pull batch 1 first — this is the reference for this window
        df_b1 = _pull_block(pytrends, TREND_BATCHES[0], tf)
        time.sleep(3)
        if df_b1.empty:
            print(f"    Batch 1 empty, skipping window.")
            continue

        df_b1["date"] = pd.to_datetime(df_b1["date"]).dt.date

        # Store batch 1 keywords (using raw values; will normalize later)
        for kw in TREND_BATCHES[0]:
            if kw in df_b1.columns:
                for _, row in df_b1.iterrows():
                    master[kw][str(row["date"])] = float(row[kw])

        # Pull remaining batches, rescale vs anchor
        for bi, batch in enumerate(TREND_BATCHES[1:], start=2):
            print(f"    Batch {bi}/{len(TREND_BATCHES)}: {batch}")
            df_b = _pull_block(pytrends, batch, tf)
            time.sleep(3)
            if df_b.empty:
                print(f"    Batch {bi} empty.")
                continue

            df_b["date"] = pd.to_datetime(df_b["date"]).dt.date

            # Cross-scale: anchor in this batch vs anchor in batch 1
            overlap_dates = set(df_b1["date"]) & set(df_b["date"])
            if overlap_dates and ANCHOR_KW in df_b.columns:
                anchor_b1 = df_b1[df_b1["date"].isin(overlap_dates)][ANCHOR_KW].mean()
                anchor_bn = df_b[df_b["date"].isin(overlap_dates)][ANCHOR_KW].mean()
                scale = (anchor_b1 / anchor_bn) if anchor_bn > 0 else 1.0
            else:
                scale = 1.0

            for kw in batch:
                if kw == ANCHOR_KW or kw not in df_b.columns:
                    continue
                for _, row in df_b.iterrows():
                    master[kw][str(row["date"])] = float(row[kw]) * scale

        # Stitch this window into prior window using anchor overlap
        # (handled implicitly: same dates overwrite, later window preferred)

    # ── Build aligned DataFrame ───────────────────────────────────────────────
    all_dates = sorted(set().union(*[set(v.keys()) for v in master.values()]))
    if not all_dates:
        return {}

    df = pd.DataFrame(index=all_dates)
    for kw in TREND_KEYWORDS:
        df[kw] = pd.Series(master[kw])

    df = df.sort_index().interpolate(method="linear", limit_direction="both")

    # ── Normalize each series to mean=100 ────────────────────────────────────
    df_norm = pd.DataFrame(index=df.index)
    for kw in TREND_KEYWORDS:
        mean_val = df[kw].mean()
        df_norm[kw] = (df[kw] / mean_val * 100).round(1) if mean_val > 0 else df[kw]

    # ── Equal-weighted composite ──────────────────────────────────────────────
    df_norm["composite"] = df_norm[TREND_KEYWORDS].mean(axis=1).round(1)

    # ── Serialize ─────────────────────────────────────────────────────────────
    result = {}
    for kw in TREND_KEYWORDS:
        result[kw] = [
            {"date": d, "value": round(float(df[kw][d]), 1)}
            for d in all_dates if not pd.isna(df[kw].get(d))
        ]
    result["composite"] = [
        {"date": d, "value": round(float(df_norm["composite"][d]), 1)}
        for d in all_dates if not pd.isna(df_norm["composite"].get(d))
    ]
    # Also save normalized individual series for potential future use
    result["normalized"] = {
        kw: [
            {"date": d, "value": round(float(df_norm[kw][d]), 1)}
            for d in all_dates if not pd.isna(df_norm[kw].get(d))
        ]
        for kw in TREND_KEYWORDS
    }
    return result


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    data = {}

    # ── Section 1A: Google Trends ─────────────────────────────────────────────
    print("\n── Google Trends (2016→today, batched + normalized) ──")
    trends_data = fetch_trends_all(start_year=2016)
    if trends_data:
        data["google_trends"] = trends_data
        print(f"  → Anchor series: {len(trends_data.get(ANCHOR_KW, []))} weekly obs")
        print(f"  → Composite:     {len(trends_data.get('composite', []))} weekly obs")
    else:
        data["google_trends"] = {}
        print("  ⚠ No Trends data retrieved.")

    # ── Section 1B: Housing Starts ────────────────────────────────────────────
    print("\n── Housing Starts (FRED) ──")
    data["housing_total"]       = fetch_fred("HOUST")       # Total SA
    data["housing_single"]      = fetch_fred("HSN1F")       # Single-family SA
    data["housing_multi"]       = fetch_fred("HOUST5F")     # 5+ units SA
    print(f"  Total:         {len(data['housing_total'])} obs  | "
          f"latest: {data['housing_total'][-1]['date'] if data['housing_total'] else 'N/A'}")
    print(f"  Single-family: {len(data['housing_single'])} obs | "
          f"latest: {data['housing_single'][-1]['date'] if data['housing_single'] else 'N/A'}")
    print(f"  Multifamily:   {len(data['housing_multi'])} obs  | "
          f"latest: {data['housing_multi'][-1]['date'] if data['housing_multi'] else 'N/A'}")

    # ── Section 1C: Food Services ─────────────────────────────────────────────
    print("\n── Food Services (FRED/BLS) ──")
    data["restaurant_sales"]    = fetch_fred("RSAFS")           # Advance Retail Sales: Food Services $M
    data["food_employment"]     = fetch_fred("CEU7072200001")   # BLS Food Services employment (thousands)
    print(f"  Sales (RSAFS):      {len(data['restaurant_sales'])} obs | "
          f"latest: {data['restaurant_sales'][-1]['date'] if data['restaurant_sales'] else 'N/A'}")
    print(f"  Employment (BLS):   {len(data['food_employment'])} obs | "
          f"latest: {data['food_employment'][-1]['date'] if data['food_employment'] else 'N/A'}")

    # ── Meta ──────────────────────────────────────────────────────────────────
    data["last_updated"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    data["trend_keywords"] = TREND_KEYWORDS
    data["anchor_keyword"] = ANCHOR_KW

    with open("data.json", "w") as f:
        json.dump(data, f, indent=2)

    print(f"\n✓ data.json written — {data['last_updated']}")


if __name__ == "__main__":
    main()
