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
        r"\bclark\s+pest\b",
        r"\bfox\s+pest\b",
        r"\bhometeam\s+pest\b",
        r"\bhome\s+team\s+pest\b",
        r"\bnorthwest\s+exterminating\b",
        r"\bramex\b",
        r"\bsaela\b",
    ],
    "Rentokil / Terminix": [
        r"\brentokil\b",
        r"\bterminix\b",
        r"\behrlich\b",
        r"\bwestern\s+exterminator\b",
        r"\bflorida\s+pest\s+control\b",
        r"\bhometown\s+pest\b",
        r"\bbug\s+out\b",
        r"\bheron\s+home\b",
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
    "Arrow Exterminators": [
        r"\barrow\s+exter",
        r"\barrow\s+pest",
    ],
    "Truly Nolen": [
        r"\btruly\s+nolen\b",
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


def has_unrecognized_mention(text: str) -> bool:
    """
    Return True if *text* appears to mention a pest control company
    that is NOT in our brand registry.

    Heuristic: look for phrases like "pest control", "exterminator",
    "termite", "mosquito" etc. near a capitalized proper noun that is
    not already matched by find_mentions(). This is intentionally
    conservative — we flag the response, not try to name the company.
    """
    # Patterns that suggest a pest control company name is nearby
    _PEST_CONTEXT = re.compile(
        r'(?:pest\s+control|exterminator|termite|fumigation|mosquito\s+(?:control|treatment)|'
        r'bed\s+bug|rodent\s+control|wildlife\s+removal)',
        re.IGNORECASE,
    )
    if not _PEST_CONTEXT.search(text):
        return False  # no pest context at all — don't flag

    # Words that end a real company name (whitelist approach — more robust than a geographic blacklist)
    _COMPANY_SUFFIXES: frozenset[str] = frozenset({
        "pest", "control", "exterminators", "exterminating", "exterminator",
        "services", "solutions", "management", "protection", "specialists",
        "professionals", "experts", "squad", "pros", "team", "group",
        "company", "inc", "llc", "corp",
    })

    # Common prepositions/articles that start a sentence (sentence-start capitalization artifact)
    _LEAD_WORDS: frozenset[str] = frozenset({
        "in", "at", "on", "of", "the", "a", "an", "for", "by", "to",
        "from", "with", "near", "across", "throughout", "within",
    })

    # Look for capitalized company-like names (2+ words, Title Case) not in known brands
    _COMPANY_LIKE = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
    known_lower = {b.lower() for b in BRANDS}
    for m in _COMPANY_LIKE.finditer(text):
        raw = m.group(1).lower()
        # Strip leading common prepositions/articles
        parts = raw.split()
        while parts and parts[0] in _LEAD_WORDS:
            parts = parts[1:]
        candidate = " ".join(parts)
        if not candidate:
            continue
        # Must have 2+ words after stripping lead words
        if len(parts) < 2:
            continue
        # Must end with a company-name suffix word
        if parts[-1] not in _COMPANY_SUFFIXES:
            continue
        # Skip known brands
        if any(k in candidate or candidate in k for k in known_lower):
            continue
        return True  # found a plausible unknown company name

    return False


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
