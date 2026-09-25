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

# Non-branded pest-control keywords for Market composite
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
# Batches of <=5 keywords, anchor always first
TREND_BATCHES = [
    ["pest control near me", "exterminator near me", "termite treatment",
     "bed bug exterminator", "rodent control"],
    ["pest control near me", "mosquito control", "wildlife removal"],
]

# ── BRAND KEYWORDS (from Excel Brands tab, Google Search = Yes) ───────────────
# All keywords normalized to lowercase (Col E of Brands tab)
BRAND_GROUPS = {
    "rollins": [
        "orkin",
        "clark pest control",
        "fox pest control",
        "hometeam pest defense",
        "northwest exterminating",
        "romex pest control",
        "saela pest control",
    ],
    "rentokil": [
        "terminix",
        "rentokil pest control",
        "ehrlich pest control",
        "western exterminator",
        "florida pest control",
        "hometown pest control",
        "bug out pest control",
        "heron home pest control",
    ],
    "aptive": [
        "aptive pest control",
    ],
    "massey": [
        "massey services pest control",
    ],
    "anticimex": [
        "turner pest control",
        "viking pest control",
        "modern pest services",
        "american pest control",
        "jp mchale pest control",
        "waynes pest control",
    ],
}

# Flat list of all brand keywords (all already lowercase)
ALL_BRAND_KEYWORDS = [kw for kws in BRAND_GROUPS.values() for kw in kws]

# Build brand batches: anchor + up to 4 brand keywords per batch
def make_brand_batches(anchor, brand_keywords, batch_size=4):
    batches = []
    for i in range(0, len(brand_keywords), batch_size):
        chunk = brand_keywords[i:i+batch_size]
        batches.append([anchor] + chunk)
    return batches

BRAND_BATCHES = make_brand_batches(ANCHOR_KW, ALL_BRAND_KEYWORDS)


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


# ── GOOGLE TRENDS HELPERS ─────────────────────────────────────────────────────
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
            print(f"    pytrends retry {attempt+1}/{retries} after {wait}s -- {e}")
            time.sleep(wait)
    return pd.DataFrame()


def fetch_trends_batched(target_keywords, batches, anchor_kw, start_year=2016, label=""):
    """
    Generic batched pytrends fetch for any set of keywords.

    Methodology:
    1. For each 2-year block, pull each batch (anchor + subset of target keywords).
    2. Cross-scale each batch using anchor_kw so keyword values are comparable.
    3. Stitch 2-year blocks (later window preferred for overlapping dates).
    4. Normalize each final keyword series to mean=100 index.
    Returns dict: keyword -> list of {date, value} (normalized to mean=100)
    """
    pytrends  = TrendReq(hl="en-US", tz=300)
    today     = date.today()
    block_yrs = 2

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

    # Master dict: keyword -> {date_str: raw_value}
    master = {kw: {} for kw in target_keywords}

    for wi, (ws, we) in enumerate(windows):
        tf = f"{ws.strftime('%Y-%m-%d')} {we.strftime('%Y-%m-%d')}"
        print(f"  {label}Window {wi+1}/{len(windows)}: {tf}")

        # Pull batch 0 (contains anchor + first group of target keywords)
        df_b0 = _pull_block(pytrends, batches[0], tf)
        time.sleep(3)
        if df_b0.empty:
            print(f"    Batch 0 empty, skipping window.")
            continue

        df_b0["date"] = pd.to_datetime(df_b0["date"]).dt.date

        # Store batch 0 keywords
        for kw in batches[0]:
            if kw in df_b0.columns and kw in master:
                for _, row in df_b0.iterrows():
                    master[kw][str(row["date"])] = float(row[kw])

        # Pull remaining batches, rescale vs anchor
        for bi, batch in enumerate(batches[1:], start=1):
            print(f"    Batch {bi+1}/{len(batches)}: {batch[:3]}...")
            df_b = _pull_block(pytrends, batch, tf)
            time.sleep(3)
            if df_b.empty:
                print(f"    Batch {bi+1} empty.")
                continue

            df_b["date"] = pd.to_datetime(df_b["date"]).dt.date

            # Cross-scale: anchor in this batch vs anchor in batch 0
            overlap_dates = set(df_b0["date"]) & set(df_b["date"])
            if overlap_dates and anchor_kw in df_b.columns:
                anchor_b0 = df_b0[df_b0["date"].isin(overlap_dates)][anchor_kw].mean()
                anchor_bn = df_b[df_b["date"].isin(overlap_dates)][anchor_kw].mean()
                scale = (anchor_b0 / anchor_bn) if anchor_bn > 0 else 1.0
            else:
                scale = 1.0

            for kw in batch:
                if kw == anchor_kw or kw not in df_b.columns or kw not in master:
                    continue
                for _, row in df_b.iterrows():
                    master[kw][str(row["date"])] = float(row[kw]) * scale

    # ── Build aligned DataFrame ───────────────────────────────────────────────
    all_dates = sorted(set().union(*[set(v.keys()) for v in master.values() if v]))
    if not all_dates:
        return {}

    df = pd.DataFrame(index=all_dates)
    for kw in target_keywords:
        df[kw] = pd.Series(master[kw])

    # Light interpolation for small gaps (<=2 missing weeks), forward only
    df = df.sort_index().interpolate(method="linear", limit=2, limit_direction="forward")

    # ── Normalize each series to mean=100 ────────────────────────────────────
    df_norm = pd.DataFrame(index=df.index)
    for kw in target_keywords:
        col = df[kw].dropna()
        if len(col) == 0:
            df_norm[kw] = df[kw]
            continue
        mean_val = col.mean()
        df_norm[kw] = (df[kw] / mean_val * 100).round(1) if mean_val > 0 else df[kw]

    # ── Serialize ─────────────────────────────────────────────────────────────
    result = {}
    for kw in target_keywords:
        result[kw] = [
            {"date": d, "value": round(float(df_norm[kw][d]), 1)}
            for d in all_dates if not pd.isna(df_norm[kw].get(d, float("nan")))
        ]
    return result


# ── MARKET TRENDS (non-branded) ───────────────────────────────────────────────
def fetch_trends_all(start_year=2016):
    """
    Fetch non-branded market keywords.
    Returns dict with keys: each keyword, "composite", "normalized".
    """
    result = fetch_trends_batched(
        target_keywords=TREND_KEYWORDS,
        batches=TREND_BATCHES,
        anchor_kw=ANCHOR_KW,
        start_year=start_year,
        label="[Market] "
    )

    if not result:
        return {}

    # Build composite from normalized individual series
    all_dates = sorted(set().union(*[{r["date"] for r in v} for v in result.values() if v]))
    kw_maps = {kw: {r["date"]: r["value"] for r in result[kw]} for kw in TREND_KEYWORDS if kw in result}

    composite = []
    for d in all_dates:
        vals = [kw_maps[kw][d] for kw in TREND_KEYWORDS if kw in kw_maps and d in kw_maps[kw]]
        if vals:
            composite.append({"date": d, "value": round(sum(vals)/len(vals), 1)})

    result["composite"] = composite
    # Keep normalized as a sub-dict for individual keywords
    result["normalized"] = {kw: result[kw] for kw in TREND_KEYWORDS if kw in result}

    return result


# ── BRAND TRENDS ─────────────────────────────────────────────────────────────
def fetch_brand_trends(start_year=2016):
    """
    Fetch branded search keywords for all competitor companies.
    Returns dict: keyword (lowercase) -> [{date, value}] (normalized to mean=100).

    Uses the same anchor-cross-scaling methodology as market trends,
    so brand values are on the same relative scale as market keywords.
    """
    print(f"\n-- Brand Trends ({len(ALL_BRAND_KEYWORDS)} keywords, {len(BRAND_BATCHES)} batches) --")

    result = fetch_trends_batched(
        target_keywords=ALL_BRAND_KEYWORDS,
        batches=BRAND_BATCHES,
        anchor_kw=ANCHOR_KW,
        start_year=start_year,
        label="[Brand] "
    )

    if not result:
        print("  WARNING: No brand trends data retrieved.")
        return {}

    # Report coverage
    for parent, kws in BRAND_GROUPS.items():
        covered = sum(1 for kw in kws if kw in result and result[kw])
        print(f"  {parent}: {covered}/{len(kws)} keywords with data")

    return result


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    data = {}

    # ── Section 1A: Google Trends -- Market (non-branded) ────────────────────
    print("\n-- Google Trends Market (2016->today, batched + normalized) --")
    trends_data = fetch_trends_all(start_year=2016)
    if trends_data:
        data["google_trends"] = trends_data
        print(f"  -> Anchor series: {len(trends_data.get(ANCHOR_KW, []))} weekly obs")
        print(f"  -> Composite:     {len(trends_data.get('composite', []))} weekly obs")
    else:
        data["google_trends"] = {}
        print("  WARNING: No market Trends data retrieved.")

    # ── Section 1B: Google Trends -- Brand keywords ──────────────────────────
    brand_data = fetch_brand_trends(start_year=2016)
    data["brand_trends"] = brand_data
    covered = sum(1 for v in brand_data.values() if v)
    print(f"  -> Brand keywords fetched: {covered}/{len(ALL_BRAND_KEYWORDS)}")

    # ── Section 1C: Housing Starts ────────────────────────────────────────────
    print("\n-- Housing Starts (FRED) --")
    data["housing_total"]  = fetch_fred("HOUST")      # Total SA
    data["housing_single"] = fetch_fred("HSN1F")      # Single-family SA
    data["housing_multi"]  = fetch_fred("HOUST5F")    # 5+ units SA
    print(f"  Total:         {len(data['housing_total'])} obs  | "
          f"latest: {data['housing_total'][-1]['date'] if data['housing_total'] else 'N/A'}")
    print(f"  Single-family: {len(data['housing_single'])} obs | "
          f"latest: {data['housing_single'][-1]['date'] if data['housing_single'] else 'N/A'}")
    print(f"  Multifamily:   {len(data['housing_multi'])} obs  | "
          f"latest: {data['housing_multi'][-1]['date'] if data['housing_multi'] else 'N/A'}")

    # ── Section 1D: Food Services ─────────────────────────────────────────────
    print("\n-- Food Services (FRED/BLS) --")
    data["restaurant_sales"] = fetch_fred("RSAFS")          # Advance Retail Sales: Food Services $M
    data["food_employment"]  = fetch_fred("CEU7072200001")  # BLS Food Services employment (thousands)
    print(f"  Sales (RSAFS):    {len(data['restaurant_sales'])} obs | "
          f"latest: {data['restaurant_sales'][-1]['date'] if data['restaurant_sales'] else 'N/A'}")
    print(f"  Employment (BLS): {len(data['food_employment'])} obs | "
          f"latest: {data['food_employment'][-1]['date'] if data['food_employment'] else 'N/A'}")

    # ── Meta ──────────────────────────────────────────────────────────────────
    data["last_updated"]   = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    data["trend_keywords"] = TREND_KEYWORDS
    data["anchor_keyword"] = ANCHOR_KW
    data["brand_groups"]   = BRAND_GROUPS        # group mapping for reference
    data["brand_keywords"] = ALL_BRAND_KEYWORDS  # flat list

    with open("data.json", "w") as f:
        json.dump(data, f, indent=2)

    print(f"\nOK data.json written -- {data['last_updated']}")
    print(f"  Market keywords: {len(TREND_KEYWORDS)}")
    print(f"  Brand keywords:  {len(ALL_BRAND_KEYWORDS)}")


if __name__ == "__main__":
    main()
