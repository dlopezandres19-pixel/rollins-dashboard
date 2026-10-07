"""
utils.py
Shared utilities: week calculation, CSV I/O with deduplication, path helpers.
"""

import os
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Week / date helpers
# ---------------------------------------------------------------------------
def get_iso_week(run_date: date | None = None) -> str:
    """
    Return the ISO-8601 week start (Monday) for the given date as YYYY-MM-DD.
    Defaults to today if run_date is None.
    Example: 2026-10-05 (Monday of the week containing Oct 5).
    """
    d = run_date or date.today()
    monday = d - timedelta(days=d.weekday())
    return monday.strftime("%Y-%m-%d")


def get_run_date(run_date: date | None = None) -> str:
    """Return today's date as YYYY-MM-DD."""
    d = run_date or date.today()
    return d.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def ensure_dirs(base_dir: str) -> dict[str, Path]:
    """
    Ensure all required output directories exist.
    Returns dict of {name: Path}.
    """
    base = Path(base_dir)
    paths = {
        "raw":    base / "data" / "raw",
        "weekly": base / "data" / "weekly",
        "master": base / "data" / "master",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def raw_filepath(base_dir: str, run_date: str) -> Path:
    paths = ensure_dirs(base_dir)
    return paths["raw"] / f"{run_date}_responses.csv"


def weekly_filepath(base_dir: str, run_date: str) -> Path:
    paths = ensure_dirs(base_dir)
    return paths["weekly"] / f"{run_date}_brand_metrics.csv"


def master_company_filepath(base_dir: str) -> Path:
    paths = ensure_dirs(base_dir)
    return paths["master"] / "ai_brand_visibility_company.csv"


def master_brand_filepath(base_dir: str) -> Path:
    paths = ensure_dirs(base_dir)
    return paths["master"] / "ai_brand_visibility_brand.csv"


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
MASTER_COMPANY_KEY = ["week", "provider", "model", "company"]
MASTER_BRAND_KEY   = ["week", "provider", "model", "company", "brand"]


def save_csv(df: pd.DataFrame, path: Path, overwrite: bool = True) -> None:
    """Save DataFrame to CSV, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    logger.info(f"Saved {len(df)} rows → {path}")


def append_master(
    new_df: pd.DataFrame,
    master_path: Path,
    dedup_keys: list[str],
) -> pd.DataFrame:
    """
    Append new_df to master CSV, deduplicating on dedup_keys.
    If the master file does not exist, it is created.
    On duplicate keys, new rows replace old rows (idempotent reruns).
    """
    if master_path.exists():
        existing = pd.read_csv(master_path, dtype=str)
    else:
        existing = pd.DataFrame(columns=new_df.columns)
        logger.info(f"Creating new master file: {master_path}")

    # Drop rows from existing that match any key in new_df
    # Keep existing rows whose keys don't appear in new_df
    available_keys = [k for k in dedup_keys if k in existing.columns and k in new_df.columns]

    if available_keys and len(existing) > 0:
        # Create a merge key from the key columns
        existing_keys = existing[available_keys].astype(str).agg("||".join, axis=1)
        new_keys      = new_df[available_keys].astype(str).agg("||".join, axis=1)
        mask_keep     = ~existing_keys.isin(set(new_keys))
        existing      = existing[mask_keep]

    combined = pd.concat([existing, new_df], ignore_index=True)
    save_csv(combined, master_path, overwrite=True)
    logger.info(f"Master updated: {len(combined)} total rows in {master_path}")
    return combined


# ---------------------------------------------------------------------------
# Config validation (DRY_RUN)
# ---------------------------------------------------------------------------
def validate_config(base_dir: str, prompts_path: str, brand_dict_path: str) -> list[str]:
    """
    Validate configuration without making API calls.
    Returns list of error strings (empty = all good).
    """
    import json

    errors = []

    # Check required env vars
    required_secrets = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
    for var in required_secrets:
        if not os.environ.get(var):
            errors.append(f"Missing env var: {var}")

    optional_vars = ["OPENAI_MODEL", "ANTHROPIC_MODEL", "GEMINI_MODEL"]
    for var in optional_vars:
        val = os.environ.get(var, "(default)")
        logger.info(f"  {var} = {val}")

    # Check brand dictionary
    if not Path(brand_dict_path).exists():
        errors.append(f"Brand dictionary not found: {brand_dict_path}")

    # Check prompts
    if not Path(prompts_path).exists():
        errors.append(f"Prompts file not found: {prompts_path}")
    else:
        try:
            with open(prompts_path) as f:
                prompts = json.load(f)
            if "prompts" not in prompts:
                errors.append("prompts.json missing 'prompts' key")
            else:
                logger.info(f"  Prompts loaded: {len(prompts['prompts'])} prompts")
        except Exception as e:
            errors.append(f"Error reading prompts.json: {e}")

    # Check output paths are writable
    try:
        paths = ensure_dirs(base_dir)
        for name, p in paths.items():
            test_file = p / ".write_test"
            test_file.touch()
            test_file.unlink()
    except Exception as e:
        errors.append(f"Output directory not writable: {e}")

    return errors
