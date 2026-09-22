import os
import json
import requests
from datetime import datetime, timedelta
from pytrends.request import TrendReq

# ── FRED API ──────────────────────────────────────────────
FRED_API_KEY = os.environ["FRED_API_KEY"]
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

def fetch_fred(series_id, limit=24):
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit
    }
    r = requests.get(FRED_BASE, params=params)
    r.raise_for_status()
    obs = r.json()["observations"]
    # reverse to chronological order, filter missing
    obs = [o for o in reversed(obs) if o["value"] != "."]
    return [{"date": o["date"], "value": float(o["value"])} for o in obs]

# ── GOOGLE TRENDS ─────────────────────────────────────────
def fetch_trends():
    pytrends = TrendReq(hl="en-US", tz=300)
    pytrends.build_payload(
        ["pest control near me"],
        cat=0,
        timeframe="today 12-m",
        geo="US"
    )
    df = pytrends.interest_over_time()
    if df.empty:
        return []
    df = df.reset_index()
    return [
        {"date": str(row["date"].date()), "value": int(row["pest control near me"])}
        for _, row in df.iterrows()
    ]

# ── MAIN ──────────────────────────────────────────────────
def main():
    data = {}

    print("Fetching Google Trends...")
    data["google_trends"] = fetch_trends()

    print("Fetching Housing Starts (FRED: HOUST)...")
    data["housing_starts"] = fetch_fred("HOUST", limit=24)

    print("Fetching OpenTable (FRED: DININGOUT)...")
    data["opentable"] = fetch_fred("DININGOUT", limit=52)

    data["last_updated"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    with open("data.json", "w") as f:
        json.dump(data, f, indent=2)

    print(f"Done. Last updated: {data['last_updated']}")

if __name__ == "__main__":
    main()
