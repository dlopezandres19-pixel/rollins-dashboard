"""
run_tracker.py — Weekly regional AI brand visibility tracker.

Methodology: v1-regional
  - Web search ON (OpenAI + Gemini only).
  - 10 prompts × 3 reps × 4 regions × 2 providers = 240 API calls/week.
  - [REGION] replaced at runtime with each region's prompt_label.
  - Brand matching: deterministic regex (brand_matcher.py).
  - Output: one CSV per (provider, region, week) + weekly aggregate JSON.

Usage:
  python run_tracker.py                     # run all providers × all regions
  python run_tracker.py --provider openai   # one provider only
  python run_tracker.py --region southeast  # one region only
  python run_tracker.py --dry-run           # print prompts, no API calls
"""

import argparse
import csv
import json
import time
from pathlib import Path

import brand_matcher as bm
from providers import PROVIDERS, PROVIDER_MODELS
from utils import (
    DATA_RAW_DIR,
    DATA_WEEKLY_DIR,
    iso_week,
    load_prompts,
    load_regions,
    log,
    now_utc_iso,
    raw_filename,
    render_prompt,
    today_iso,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPS = 3          # repetitions per (prompt × region × provider)
SLEEP_BETWEEN = 1.5  # seconds between API calls (rate-limit buffer)


# ---------------------------------------------------------------------------
# Core: run one (provider, region, prompt, rep) cell
# ---------------------------------------------------------------------------
def run_cell(
    provider_id: str,
    region: dict,
    prompt: dict,
    rep: int,
    system_context: str,
    dry_run: bool = False,
) -> dict:
    """
    Execute a single API call and return a result record.
    """
    region_id = region["id"]
    region_label = region["prompt_label"]
    prompt_id = prompt["id"]
    rendered = render_prompt(prompt["text"], region_label)

    record = {
        "run_date": today_iso(),
        "iso_week": iso_week(),
        "provider": provider_id,
        "model": PROVIDER_MODELS.get(provider_id, "unknown"),
        "region_id": region_id,
        "region_label": region["label"],
        "prompt_id": prompt_id,
        "prompt_text": rendered,
        "rep": rep,
        "response_text": None,
        "mentioned_brands": [],
        "first_mentioned": None,
        "top3_brands": [],
        "error": None,
        "timestamp_utc": now_utc_iso(),
    }

    if dry_run:
        log(f"[DRY-RUN] {provider_id} | {region_id} | p{prompt_id} r{rep} → {rendered}")
        return record

    call_fn = PROVIDERS[provider_id]
    response_text = call_fn(
        system_prompt=system_context,
        user_prompt=rendered,
    )

    if response_text is None:
        record["error"] = "API call failed after retries"
        log(f"  ✗ {provider_id} | {region_id} | p{prompt_id} r{rep} → ERROR")
        return record

    record["response_text"] = response_text
    record["mentioned_brands"] = bm.find_mentions(response_text)
    record["first_mentioned"] = bm.find_first_mentioned(response_text)
    record["top3_brands"] = bm.find_top_n(response_text, n=3)
    record["has_unknown"] = bm.has_unrecognized_mention(response_text)

    mentioned_str = ", ".join(record["mentioned_brands"]) or ("(local/unknown)" if record["has_unknown"] else "(none)")
    log(f"  ✓ {provider_id} | {region_id} | p{prompt_id} r{rep} → {mentioned_str}")

    return record


# ---------------------------------------------------------------------------
# Save raw response
# ---------------------------------------------------------------------------
def save_raw(record: dict) -> None:
    fname = raw_filename(
        record["provider"], record["region_id"], record["prompt_id"], record["rep"]
    )
    path = DATA_RAW_DIR / record["provider"] / record["region_id"] / fname
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------------------
# Aggregate: compute metrics from a batch of records
# ---------------------------------------------------------------------------
def compute_metrics(records: list[dict], brands_list: list[str]) -> list[dict]:
    """
    Compute per-brand metrics for a set of records from one (provider, region, week).
    Returns a list of metric rows, one per brand.
    """
    total = len([r for r in records if r["error"] is None])
    if total == 0:
        return []

    rows = []
    for brand in brands_list:
        mention_hits = sum(1 for r in records if brand in r["mentioned_brands"] and not r["error"])
        top3_hits    = sum(1 for r in records if brand in r["top3_brands"] and not r["error"])
        rank1_hits   = sum(1 for r in records if r["first_mentioned"] == brand and not r["error"])

        rows.append({
            "brand": brand,
            "mention_hits": mention_hits,
            "top3_hits": top3_hits,
            "rank1_hits": rank1_hits,
            "total_responses": total,
            "mention_rate": round(mention_hits / total, 4) if total else 0,
            "top3_rate":    round(top3_hits    / total, 4) if total else 0,
            "rank1_rate":   round(rank1_hits   / total, 4) if total else 0,
        })

    # Synthetic row: Local / Unknown brands
    local_hits = sum(1 for r in records if r.get("has_unknown") and not r["error"])
    rows.append({
        "brand": "__local_unknown__",
        "mention_hits": local_hits,
        "top3_hits": 0,  # not trackable without knowing the brand
        "rank1_hits": 0,
        "total_responses": total,
        "mention_rate": round(local_hits / total, 4) if total else 0,
        "top3_rate":    0,
        "rank1_rate":   0,
    })

    return rows


# ---------------------------------------------------------------------------
# Save weekly CSV
# ---------------------------------------------------------------------------
def save_weekly_csv(metrics: list[dict], provider: str, region_id: str, week: str) -> Path:
    filename = f"{provider}_{region_id}_{week}_metrics.csv"
    path = DATA_WEEKLY_DIR / provider / region_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "week", "provider", "region_id", "brand",
        "mention_hits", "top3_hits", "rank1_hits", "total_responses",
        "mention_rate", "top3_rate", "rank1_rate",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in metrics:
            writer.writerow({
                "week": week,
                "provider": provider,
                "region_id": region_id,
                **row,
            })
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Regional AI brand visibility tracker")
    parser.add_argument("--provider", choices=list(PROVIDERS.keys()), help="Run one provider only")
    parser.add_argument("--region",   help="Run one region ID only (e.g. southeast)")
    parser.add_argument("--dry-run",  action="store_true", help="Print prompts, skip API calls")
    args = parser.parse_args()

    prompts_cfg   = load_prompts()
    system_context = prompts_cfg["system_context"]
    prompts        = prompts_cfg["prompts"]
    all_regions    = load_regions()
    week           = iso_week()

    # Filter if requested
    providers_to_run = [args.provider] if args.provider else list(PROVIDERS.keys())
    regions_to_run   = [r for r in all_regions if (not args.region or r["id"] == args.region)]

    if not regions_to_run:
        log(f"No region found with id='{args.region}'")
        return

    brands_list = list(bm.BRANDS.keys())

    log(f"=== Regional tracker run — week {week} ===")
    log(f"Providers : {providers_to_run}")
    log(f"Regions   : {[r['id'] for r in regions_to_run]}")
    log(f"Prompts   : {len(prompts)}, Reps: {REPS}")
    log(f"Total calls: {len(providers_to_run) * len(regions_to_run) * len(prompts) * REPS}")
    log("")

    for provider_id in providers_to_run:
        for region in regions_to_run:
            region_id = region["id"]
            log(f"--- {provider_id.upper()} × {region['label']} ---")
            records: list[dict] = []

            for prompt in prompts:
                for rep in range(1, REPS + 1):
                    record = run_cell(
                        provider_id, region, prompt, rep,
                        system_context=system_context,
                        dry_run=args.dry_run,
                    )
                    records.append(record)
                    if not args.dry_run:
                        save_raw(record)
                        time.sleep(SLEEP_BETWEEN)

            if not args.dry_run:
                metrics = compute_metrics(records, brands_list)
                csv_path = save_weekly_csv(metrics, provider_id, region_id, week)
                log(f"  → Saved {csv_path.name}")

            log("")

    log("=== Run complete ===")


if __name__ == "__main__":
    main()
