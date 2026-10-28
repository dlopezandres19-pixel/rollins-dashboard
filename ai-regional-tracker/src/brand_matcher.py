"""
brand_matcher.py — Deterministic regex-based brand matching.

Rules (in force across all tracker variants):
  - Brand matching MUST be deterministic regex, never another LLM call.
  - Do NOT reveal brand names in any system prompt sent to providers.
  - Do NOT tell the model this is a benchmarking exercise.
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Brand registry
# Each entry: canonical name → list of regex patterns (case-insensitive)
# Patterns are checked against the full response text.
# ---------------------------------------------------------------------------
BRANDS: dict[str, list[str]] = {
    "Rollins / Orkin": [
        r"\brollins\b",
        r"\borkin\b",
    ],
    "Rentokil / Terminix": [
        r"\brentokil\b",
        r"\bterminix\b",
    ],
    "Aptive": [
        r"\baptive\b",
    ],
    "Massey": [
        r"\bmassey\b",
    ],
    "Anticimex": [
        r"\banticimex\b",
    ],
    "HomeTeam": [
        r"\bhometeam\b",
        r"\bhome\s+team\b",
    ],
    "Fox Pest Control": [
        r"\bfox\s+pest\b",
    ],
    "Arrow Exterminators": [
        r"\barrow\s+exter",
        r"\barrow\s+pest",
    ],
    "Truly Nolen": [
        r"\btruly\s+nolen\b",
    ],
    "Western Exterminator": [
        r"\bwestern\s+exter",
    ],
    "Ehrlich": [
        r"\behrlich\b",
    ],
    "Presto-X": [
        r"\bpresto[\s\-]x\b",
    ],
    "Mosquito Squad": [
        r"\bmosquito\s+squad\b",
    ],
    "Lawn Doctor": [
        r"\blawn\s+doctor\b",
    ],
    "Northwest Exterminating": [
        r"\bnorthwest\s+exter",
    ],
}

# Pre-compile for performance
_COMPILED: dict[str, list[re.Pattern]] = {
    brand: [re.compile(p, re.IGNORECASE) for p in patterns]
    for brand, patterns in BRANDS.items()
}


def find_mentions(text: str) -> list[str]:
    """Return list of canonical brand names mentioned in *text* (no duplicates, order of first match)."""
    found: list[str] = []
    for brand, patterns in _COMPILED.items():
        for pat in patterns:
            if pat.search(text):
                found.append(brand)
                break  # one match per brand is enough
    return found


def find_first_mentioned(text: str) -> Optional[str]:
    """Return the canonical brand name that appears earliest in *text*, or None."""
    earliest_pos: int = len(text) + 1
    earliest_brand: Optional[str] = None

    for brand, patterns in _COMPILED.items():
        for pat in patterns:
            m = pat.search(text)
            if m and m.start() < earliest_pos:
                earliest_pos = m.start()
                earliest_brand = brand

    return earliest_brand


def find_top_n(text: str, n: int = 3) -> list[str]:
    """
    Return up to *n* brand names in order of first appearance in *text*.
    Used to compute Top-3 Rate and #1 Rate.
    """
    hits: list[tuple[int, str]] = []

    for brand, patterns in _COMPILED.items():
        for pat in patterns:
            m = pat.search(text)
            if m:
                hits.append((m.start(), brand))
                break

    hits.sort(key=lambda x: x[0])
    return [brand for _, brand in hits[:n]]
