"""
run_tracker.py
Main orchestrator for the AI Brand Visibility Tracker.

Environment variables:
  Required (GitHub Secrets):
    OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY

  Optional (GitHub Variables / defaults shown):
    OPENAI_MODEL        = gpt-4o-mini
    ANTHROPIC_MODEL     = claude-haiku-4-5-20251001
    GEMINI_MODEL        = gemini-1.5-flash
    RUNS_PER_PROMPT     = 5
    DRY_RUN             = false
    MAX_OUTPUT_TOKENS   = 512
    LLM_TEMPERATURE     = 0.3
    RETRY_MAX           = 3
    RETRY_BASE_SECONDS  = 5
    PROVIDERS           = openai,anthropic,gemini   (comma-separated)

Usage:
  python src/run_tracker.py
  DRY_RUN=true python src/run_tracker.py
"""

import json
import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

# Allow running from repo root or src/
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from brand_matcher import load_brand_dictionary, match_brands
from metrics import compute_weekly_metrics, process_matched_responses
from providers import PROVIDER_FNS
from utils import (
    MASTER_BRAND_KEY,
    MASTER_COMPANY_KEY,
    append_master,
    ensure_dirs,
    get_iso_week,
    get_run_date,
    master_brand_filepath,
    master_company_filepath,
    raw_filepath,
    save_csv,
    validate_config,
    weekly_filepath,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("run_tracker")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RUNS_PER_PROMPT     = int(os.environ.get("RUNS_PER_PROMPT", "5"))
DRY_RUN             = os.environ.get("DRY_RUN", "false").lower() in ("1", "true", "yes")
METHODOLOGY_VERSION = "v1"
CONFIG_DIR          = ROOT_DIR / "config"
PROMPTS_PATH        = CONFIG_DIR / "prompts.json"
BRAND_DICT_PATH     = CONFIG_DIR / "Brand_Dictionary_AI_Tracker.xlsx"
BASE_DIR            = str(ROOT_DIR)

# Which providers to run (all by default)
_PROVIDERS_ENV = os.environ.get("PROVIDERS", "openai,anthropic,gemini")
ACTIVE_PROVIDERS = [p.strip() for p in _PROVIDERS_ENV.split(",") if p.strip()]


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------
def load_prompts() -> list[dict]:
    with open(PROMPTS_PATH) as f:
        data = json.load(f)
    return data["prompts"]


# ---------------------------------------------------------------------------
# Single query with metadata
# ---------------------------------------------------------------------------
def run_one(provider: str, prompt: dict, repetition: int, run_date: str, week: str) -> dict:
    """Execute a single provider query and return a raw-response record."""
    fn = PROVIDER_FNS[provider]
    result = fn(prompt["text"])

    return {
        "run_date":           run_date,
        "week":               week,
        "methodology_version":METHODOLOGY_VERSION,
        "provider":           result.get("provider", provider),
        "model":              result.get("model"),
        "prompt_id":          prompt["id"],
        "prompt_text":        prompt["text"],
        "repetition":         repetition,
        "timestamp_utc":      result.get("timestamp_utc"),
        "raw_response":       result.get("raw_response"),
        "prompt_tokens":      result.get("prompt_tokens"),
        "completion_tokens":  result.get("completion_tokens"),
        "error":              result.get("error"),
    }


# ---------------------------------------------------------------------------
# Main tracker run
# ---------------------------------------------------------------------------
def main() -> int:
    run_date = get_run_date()
    week     = get_iso_week()

    logger.info(f"{'='*60}")
    logger.info(f"AI Brand Visibility Tracker — {METHODOLOGY_VERSION}")
    logger.info(f"run_date={run_date}  week={week}")
    logger.info(f"DRY_RUN={DRY_RUN}  RUNS_PER_PROMPT={RUNS_PER_PROMPT}")
    logger.info(f"Active providers: {ACTIVE_PROVIDERS}")
    logger.info(f"{'='*60}")

    # ── DRY RUN ──────────────────────────────────────────────────────────────
    if DRY_RUN:
        logger.info("DRY RUN mode — validating configuration only")
        errors = validate_config(BASE_DIR, str(PROMPTS_PATH), str(BRAND_DICT_PATH))
        if errors:
            for e in errors:
                logger.error(f"  FAIL: {e}")
            logger.info("DRY RUN FAILED — fix the above errors before running for real.")
            return 1
        else:
            logger.info("DRY RUN PASSED — all checks OK.")
            # Also load brand dictionary to validate it
            try:
                brand_entries = load_brand_dictionary(str(BRAND_DICT_PATH))
                logger.info(f"  Brand dictionary: {len(brand_entries)} brands loaded")
            except Exception as e:
                logger.error(f"  FAIL: Cannot load brand dictionary: {e}")
                return 1
            prompts = load_prompts()
            logger.info(f"  Prompts: {len(prompts)} loaded")
            logger.info(f"  Total planned responses: {len(ACTIVE_PROVIDERS)} providers × "
                        f"{len(prompts)} prompts × {RUNS_PER_PROMPT} runs = "
                        f"{len(ACTIVE_PROVIDERS) * len(prompts) * RUNS_PER_PROMPT}")
            return 0

    # ── LIVE RUN ─────────────────────────────────────────────────────────────
    # Load config
    prompts       = load_prompts()
    brand_entries = load_brand_dictionary(str(BRAND_DICT_PATH))
    ensure_dirs(BASE_DIR)

    logger.info(f"Loaded {len(prompts)} prompts, {len(brand_entries)} brands")

    total_planned = len(ACTIVE_PROVIDERS) * len(prompts) * RUNS_PER_PROMPT
    logger.info(f"Total planned responses: {total_planned}")

    all_responses: list[dict] = []
    provider_failed: dict[str, bool] = {p: False for p in ACTIVE_PROVIDERS}

    # ── Query loop ────────────────────────────────────────────────────────────
    for provider in ACTIVE_PROVIDERS:
        if provider not in PROVIDER_FNS:
            logger.error(f"Unknown provider '{provider}' — skipping")
            provider_failed[provider] = True
            continue

        logger.info(f"\n── Provider: {provider.upper()} ──────────────────────")
        provider_errors = 0

        # Gemini free tier: 15 requests/minute → wait 5s between calls to stay safe
        INTER_REQUEST_DELAY = 5.0 if provider == "gemini" else 0.5

        for prompt in prompts:
            for rep in range(1, RUNS_PER_PROMPT + 1):
                try:
                    record = run_one(provider, prompt, rep, run_date, week)
                    if record["error"]:
                        provider_errors += 1
                        logger.warning(
                            f"  [{provider}] prompt={prompt['id']} rep={rep} "
                            f"error={record['error']}"
                        )
                    else:
                        logger.info(
                            f"  [{provider}] prompt={prompt['id']} rep={rep} "
                            f"tokens={record.get('completion_tokens', '?')} OK"
                        )
                    all_responses.append(record)
                    time.sleep(INTER_REQUEST_DELAY)
                except Exception as e:
                    logger.error(
                        f"  [{provider}] prompt={prompt['id']} rep={rep} "
                        f"EXCEPTION: {e}"
                    )
                    all_responses.append({
                        "run_date": run_date, "week": week,
                        "methodology_version": METHODOLOGY_VERSION,
                        "provider": provider, "model": None,
                        "prompt_id": prompt["id"], "prompt_text": prompt["text"],
                        "repetition": rep,
                        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "raw_response": None, "prompt_tokens": None,
                        "completion_tokens": None, "error": str(e),
                    })
                    provider_errors += 1

        planned_per_provider = len(prompts) * RUNS_PER_PROMPT
        if provider_errors == planned_per_provider:
            logger.error(f"Provider {provider} COMPLETELY FAILED ({provider_errors} errors)")
            provider_failed[provider] = True
        else:
            logger.info(f"  {provider}: {planned_per_provider - provider_errors}/"
                        f"{planned_per_provider} responses OK, {provider_errors} errors")

    # ── Save raw responses ────────────────────────────────────────────────────
    responses_df = pd.DataFrame(all_responses)
    raw_path     = raw_filepath(BASE_DIR, run_date)
    save_csv(responses_df, raw_path)
    logger.info(f"\nRaw responses saved → {raw_path}")

    if responses_df.empty:
        logger.error("No responses collected — aborting metrics computation")
        return 1

    # ── Brand matching and position extraction ────────────────────────────────
    logger.info("\nRunning brand matching…")
    detail_df = process_matched_responses(responses_df, brand_entries, match_brands)
    logger.info(f"Detail rows: {len(detail_df)}")

    # ── Weekly metrics ────────────────────────────────────────────────────────
    logger.info("Computing weekly metrics…")
    metrics_df = compute_weekly_metrics(
        detail_df,
        run_date=run_date,
        week=week,
        methodology_version=METHODOLOGY_VERSION,
    )

    weekly_path = weekly_filepath(BASE_DIR, run_date)
    save_csv(metrics_df, weekly_path)
    logger.info(f"Weekly metrics saved → {weekly_path}")

    # ── Master files ──────────────────────────────────────────────────────────
    brand_metrics   = metrics_df[metrics_df["entity_level"] == "brand"].copy()
    company_metrics = metrics_df[metrics_df["entity_level"] == "company"].copy()

    append_master(
        company_metrics,
        master_company_filepath(BASE_DIR),
        MASTER_COMPANY_KEY,
    )
    append_master(
        brand_metrics,
        master_brand_filepath(BASE_DIR),
        MASTER_BRAND_KEY,
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("\n" + "="*60)
    logger.info("RUN SUMMARY")
    logger.info(f"  run_date : {run_date}")
    logger.info(f"  week     : {week}")
    logger.info(f"  total    : {len(responses_df)} responses collected")

    for provider in ACTIVE_PROVIDERS:
        prov_df = responses_df[responses_df["provider"] == provider]
        valid   = prov_df["error"].isna() | (prov_df["error"] == "")
        status  = "FAILED" if provider_failed.get(provider) else "OK"
        logger.info(f"  {provider:12s}: {valid.sum():3d}/{len(prov_df)} valid  [{status}]")

    # Print top mention rates for quick review
    composite = metrics_df[
        (metrics_df["provider"] == "AI Composite") &
        (metrics_df["entity_level"] == "company")
    ].sort_values("mention_rate", ascending=False)

    if not composite.empty:
        logger.info("\n  AI Composite Company Mention Rates:")
        for _, row in composite.iterrows():
            logger.info(f"    {row['company']:30s} {row['mention_rate']:5.1f}%")

    logger.info("="*60)

    # Return non-zero if any provider completely failed
    if any(provider_failed.values()):
        failed_list = [p for p, f in provider_failed.items() if f]
        logger.error(f"Providers with complete failure: {failed_list}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
