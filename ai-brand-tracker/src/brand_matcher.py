"""
brand_matcher.py
Loads Brand_Dictionary_AI_Tracker.xlsx and performs deterministic brand matching
against LLM response text.

Key design decisions:
- Word-boundary regex for most brands
- Conservative aliases only for genuinely ambiguous short names
- Northwest Exterminating flagged as parent_ambiguous (appears in both Rollins & Anticimex)
- Bug Out, The Killers, American Pest, General Pest Control get conservative patterns
"""

import re
import unicodedata
import openpyxl


# ---------------------------------------------------------------------------
# Brands that need conservative matching (word-boundary alone not enough)
# Keys are lowercased brand names from the dictionary.
# ---------------------------------------------------------------------------
CONSERVATIVE_BRANDS = {
    # Generic phrase — only match when pest context nearby or exact phrase
    "bug out": {
        "pattern": r"\bbug\s+out\b",
        "require_context": True,   # must appear near pest-related word
        "context_pattern": r"pest|exterminator|termite|rodent|insect|control|service",
    },
    "the killers": {
        "pattern": r"\bthe\s+killers\s+pest\b|\bthe\s+killers\s+exterminator\b",
        "require_context": False,   # very specific compound needed
    },
    "american pest": {
        "pattern": r"\bamerican\s+pest\b",
        "require_context": True,
        "context_pattern": r"pest|exterminator|termite|rodent|insect|control|service",
    },
    "general pest control": {
        "pattern": r"\bgeneral\s+pest\s+control\b",
        "require_context": False,
    },
    # Waynes — short common word, require full standalone match
    "waynes": {
        "pattern": r"\bwaynes?\s+pest\b|\bwaynes?\s+exterminator\b|\bwaynes?\s+services?\b|\bwaynes\b",
        "require_context": True,
        "context_pattern": r"pest|exterminator|termite|rodent|insect|control|service",
    },
    # Bugco — short, could appear in compounds
    "bugco": {
        "pattern": r"\bbugco\b",
        "require_context": False,
    },
    # MissQuito — uncommon, fine with word boundary
    "missquito": {
        "pattern": r"\bmissquito\b",
        "require_context": False,
    },
}

# Brands where parent company is ambiguous (appear under multiple parents)
AMBIGUOUS_BRANDS = {"northwest exterminating"}


def _normalize(text: str) -> str:
    """Lowercase, normalize unicode apostrophes and whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _build_pattern(brand_lower: str) -> re.Pattern:
    """Build a compiled regex pattern for a brand name."""
    if brand_lower in CONSERVATIVE_BRANDS:
        cfg = CONSERVATIVE_BRANDS[brand_lower]
        return re.compile(cfg["pattern"], re.IGNORECASE)
    # Default: escape and wrap in word boundaries
    escaped = re.escape(brand_lower)
    return re.compile(r"\b" + escaped + r"\b", re.IGNORECASE)


def load_brand_dictionary(xlsx_path: str) -> list[dict]:
    """
    Load Brand_Dictionary_AI_Tracker.xlsx.
    Returns list of dicts: {company, brand, brand_lower, pattern, parent_ambiguous}
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    entries = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        company, brand = row[0], row[1]
        if not company or not brand:
            continue
        company = str(company).strip()
        brand   = str(brand).strip()
        brand_lower = _normalize(brand)
        ambiguous = brand_lower in AMBIGUOUS_BRANDS
        entries.append({
            "company":          company,
            "brand":            brand,
            "brand_lower":      brand_lower,
            "pattern":          _build_pattern(brand_lower),
            "parent_ambiguous": ambiguous,
            "conservative_cfg": CONSERVATIVE_BRANDS.get(brand_lower),
        })
    wb.close()
    return entries


def match_brands(response_text: str, brand_entries: list[dict]) -> list[dict]:
    """
    Match all brands against a single response text.

    Returns list of hit dicts:
      brand, company, brand_hit, company_hit, parent_ambiguous

    Rules:
    - Multiple brands can hit in one response
    - A company gets company_hit=1 if >= 1 non-ambiguous brand hits
      (ambiguous brands like Northwest Exterminating do NOT count toward company_hit)
    - parent_ambiguous=True means the hit cannot be safely attributed to one parent
    """
    norm = _normalize(response_text)
    hits = []
    companies_hit = set()

    for entry in brand_entries:
        cfg = entry["conservative_cfg"]
        matched = False

        if cfg and cfg.get("require_context"):
            # Brand pattern must match AND context pattern must be nearby
            if entry["pattern"].search(norm):
                ctx_pat = re.compile(cfg["context_pattern"], re.IGNORECASE)
                if ctx_pat.search(norm):
                    matched = True
        else:
            if entry["pattern"].search(norm):
                matched = True

        if matched:
            if not entry["parent_ambiguous"]:
                companies_hit.add(entry["company"])
            hits.append({
                "brand":            entry["brand"],
                "company":          entry["company"],
                "brand_hit":        1,
                "parent_ambiguous": entry["parent_ambiguous"],
            })

    # Build full result: one row per brand in dictionary
    results = []
    hit_brands = {h["brand"] for h in hits}
    hit_map    = {h["brand"]: h for h in hits}

    for entry in brand_entries:
        if entry["brand"] in hit_brands:
            h = hit_map[entry["brand"]]
            company_hit = 1 if (entry["company"] in companies_hit and not entry["parent_ambiguous"]) else 0
            results.append({
                "brand":            entry["brand"],
                "company":          entry["company"],
                "brand_hit":        1,
                "company_hit":      company_hit,
                "parent_ambiguous": entry["parent_ambiguous"],
            })
        else:
            results.append({
                "brand":            entry["brand"],
                "company":          entry["company"],
                "brand_hit":        0,
                "company_hit":      0,
                "parent_ambiguous": False,
            })

    return results
