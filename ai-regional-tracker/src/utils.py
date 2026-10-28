"""
utils.py — Shared utilities for the regional AI brand tracker.
"""

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
DATA_WEEKLY_DIR = REPO_ROOT / "data" / "weekly"


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj: Any, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------
def load_prompts() -> dict:
    return load_json(CONFIG_DIR / "prompts.json")


def load_regions() -> list[dict]:
    data = load_json(CONFIG_DIR / "regions.json")
    return data["regions"]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def today_iso() -> str:
    return date.today().isoformat()          # "2026-10-27"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")  # "2026-10-27T22:00:00+00:00"


def iso_week(d: str | None = None) -> str:
    """Return ISO week string like '2026-W44' for the given date (or today)."""
    dt = date.fromisoformat(d) if d else date.today()
    return f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"


# ---------------------------------------------------------------------------
# Raw response filename
# ---------------------------------------------------------------------------
def raw_filename(provider: str, region_id: str, prompt_id: int, rep: int) -> str:
    """
    e.g. "openai_southeast_p01_r1_2026-10-27.json"
    """
    return f"{provider}_{region_id}_p{prompt_id:02d}_r{rep}_{today_iso()}.json"


# ---------------------------------------------------------------------------
# Logging helper (simple, no external deps)
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------
def render_prompt(template: str, region_label: str) -> str:
    """Replace [REGION] with the region's prompt_label."""
    return template.replace("[REGION]", region_label)


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------
def require_env(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            "Set it as a GitHub Actions secret or in your local .env file."
        )
    return val
