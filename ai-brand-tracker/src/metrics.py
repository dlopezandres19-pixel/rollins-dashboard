"""
metrics.py
Compute weekly brand-visibility metrics from matched-response data.

Metrics calculated:
- Mention Rate (%)           = hits / valid_responses × 100
- Top-3 Inclusion Rate (%)   = top3_hits / valid_responses × 100
- #1 Recommendation Rate (%) = number1_hits / valid_responses × 100
- Average Position           = mean of numeric positions (None when no numbered list)
- Share of Brand Mentions    = brand_hits / total_tracked_hits × 100
- AI Composite               = equal-weighted average across available providers
"""

import re
import pandas as pd
import numpy as np
from typing import Optional


# ---------------------------------------------------------------------------
# Position extraction
# ---------------------------------------------------------------------------
_POSITION_PATTERNS = [
    # "1. Orkin", "1) Orkin", "1: Orkin"
    re.compile(r"^(\d+)[.):\s]\s*(.+)", re.MULTILINE),
    # "#1 Orkin"
    re.compile(r"^#\s*(\d+)\s+(.+)", re.MULTILINE),
]

def extract_positions(response_text: str) -> dict[str, int]:
    """
    Extract brand positions from numbered lists in the response.
    Returns dict of {lowered_text_fragment: position} or {} if not a numbered list.
    Only returns positions if the response contains at least 3 consecutive numbered items.
    """
    if not response_text:
        return {}

    all_positions: list[tuple[int, str]] = []
    for pat in _POSITION_PATTERNS:
        matches = pat.findall(response_text)
        if matches:
            for rank_str, label in matches:
                try:
                    rank = int(rank_str)
                    all_positions.append((rank, label.lower().strip()))
                except ValueError:
                    pass
            if all_positions:
                break

    # Only trust positions if there's a proper numbered sequence (at least 3 items)
    if len(all_positions) < 3:
        return {}

    # Verify it looks like a real sequence (ranks 1, 2, 3 present)
    ranks = {p[0] for p in all_positions}
    if not ({1, 2, 3} <= ranks):
        return {}

    return {label: rank for rank, label in all_positions}


def get_brand_position(brand_lower: str, positions: dict[str, int]) -> Optional[int]:
    """
    Find the position of a brand in the positions dict.
    Uses substring matching since the position label may include more text.
    """
    for label, rank in positions.items():
        if brand_lower in label or label in brand_lower:
            return rank
    return None


# ---------------------------------------------------------------------------
# Response-level match processing
# ---------------------------------------------------------------------------
def process_matched_responses(
    responses_df: pd.DataFrame,
    brand_entries: list[dict],
    match_fn,
) -> pd.DataFrame:
    """
    Take the raw responses DataFrame, run brand matching, extract positions,
    and return a long-format DataFrame with one row per (response, brand).

    responses_df must have columns:
      run_date, week, methodology_version, provider, model,
      prompt_id, prompt_text, repetition, timestamp_utc,
      raw_response, prompt_tokens, completion_tokens, error
    """
    rows = []

    valid_mask = (
        responses_df["error"].isna() | (responses_df["error"] == "")
    ) & responses_df["raw_response"].notna()

    for _, resp in responses_df.iterrows():
        is_valid = valid_mask.loc[resp.name]
        raw = resp["raw_response"] if is_valid else ""

        # Extract positions from numbered lists
        positions = extract_positions(str(raw)) if raw else {}

        # Run brand matching
        if is_valid and raw:
            brand_results = match_fn(str(raw), brand_entries)
        else:
            # Failed response — mark as null (not zero-hit)
            brand_results = [
                {"brand": e["brand"], "company": e["company"],
                 "brand_hit": None, "company_hit": None, "parent_ambiguous": e.get("parent_ambiguous", False)}
                for e in brand_entries
            ]

        for br in brand_results:
            brand_lower = br["brand"].lower()

            # Position metrics (only when brand_hit=1 and numbered list found)
            position = None
            in_top3  = None
            is_num1  = None

            if br["brand_hit"] == 1 and positions:
                position = get_brand_position(brand_lower, positions)
                if position is not None:
                    in_top3 = 1 if position <= 3 else 0
                    is_num1 = 1 if position == 1 else 0
                else:
                    in_top3 = 0
                    is_num1 = 0
            elif br["brand_hit"] == 0:
                in_top3 = 0
                is_num1 = 0

            rows.append({
                "run_date":           resp.get("run_date"),
                "week":               resp.get("week"),
                "methodology_version":resp.get("methodology_version"),
                "provider":           resp.get("provider"),
                "model":              resp.get("model"),
                "prompt_id":          resp.get("prompt_id"),
                "repetition":         resp.get("repetition"),
                "company":            br["company"],
                "brand":              br["brand"],
                "brand_hit":          br["brand_hit"],
                "company_hit":        br.get("company_hit"),
                "parent_ambiguous":   br.get("parent_ambiguous", False),
                "position":           position,
                "in_top3":            in_top3,
                "is_num1":            is_num1,
                "response_valid":     1 if is_valid else 0,
            })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Weekly aggregation
# ---------------------------------------------------------------------------
def _safe_rate(hits, total) -> Optional[float]:
    """Return percentage rate, or None if total is 0."""
    if total == 0:
        return None
    return round(hits / total * 100, 2)


def _agg_entity(group: pd.DataFrame, total_valid: int, total_brand_hits: int) -> dict:
    """Aggregate one (provider, entity) group into metric dict."""
    valid_rows = group[group["response_valid"] == 1]

    hit_rows    = valid_rows[valid_rows["brand_hit"] == 1]
    mention_hits = int(hit_rows["brand_hit"].count())          # count non-null

    top3_hits   = int(valid_rows["in_top3"].sum()) if "in_top3" in valid_rows else 0
    num1_hits   = int(valid_rows["is_num1"].sum()) if "is_num1" in valid_rows else 0

    positions   = valid_rows["position"].dropna()
    avg_pos     = round(float(positions.mean()), 2) if len(positions) > 0 else None

    share = _safe_rate(mention_hits, total_brand_hits) if total_brand_hits else None

    return {
        "total_runs":    total_valid,
        "mention_hits":  mention_hits,
        "mention_rate":  _safe_rate(mention_hits, total_valid),
        "top3_hits":     top3_hits,
        "top3_rate":     _safe_rate(top3_hits, total_valid),
        "number1_hits":  num1_hits,
        "number1_rate":  _safe_rate(num1_hits, total_valid),
        "avg_position":  avg_pos,
        "share_of_mentions": share,
    }


def compute_weekly_metrics(
    detail_df: pd.DataFrame,
    run_date: str,
    week: str,
    methodology_version: str,
) -> pd.DataFrame:
    """
    Compute weekly metrics at both brand and company level, per provider.
    Returns a DataFrame with one row per (provider, entity_level, company, brand).
    Also appends AI Composite rows.
    """
    output_rows = []

    providers = detail_df["provider"].unique()

    for provider in providers:
        prov_df = detail_df[detail_df["provider"] == provider]
        model   = prov_df["model"].dropna().iloc[0] if len(prov_df) > 0 else ""

        # Dedupe: one row per (prompt_id, repetition) — count valid unique responses
        resp_keys = prov_df[["prompt_id", "repetition", "response_valid"]].drop_duplicates(
            subset=["prompt_id", "repetition"]
        )
        total_valid = int(resp_keys["response_valid"].sum())

        # Total brand hits (for Share of Brand Mentions denominator)
        total_brand_hits = int(
            prov_df[prov_df["response_valid"] == 1]["brand_hit"]
            .fillna(0).sum()
        )

        # ── Brand-level ──────────────────────────────────────────────────────
        for brand_name, bgroup in prov_df.groupby("brand"):
            company_name = bgroup["company"].iloc[0]
            parent_ambig = bool(bgroup["parent_ambiguous"].any())

            m = _agg_entity(bgroup, total_valid, total_brand_hits)
            output_rows.append({
                "week":               week,
                "run_date":           run_date,
                "provider":           provider,
                "model":              model,
                "entity_level":       "brand",
                "company":            company_name,
                "brand":              brand_name,
                "parent_ambiguous":   parent_ambig,
                "methodology_version":methodology_version,
                **m,
            })

        # ── Company-level ────────────────────────────────────────────────────
        # A response counts as a company hit if any non-ambiguous brand hits.
        # Collapse to one row per (prompt_id, repetition, company).
        comp_agg = (
            prov_df[prov_df["response_valid"] == 1]
            .groupby(["prompt_id", "repetition", "company"])
            .agg(
                company_hit=("company_hit", "max"),
                response_valid=("response_valid", "max"),
                in_top3=("in_top3", "max"),
                is_num1=("is_num1", "max"),
                position=("position", "min"),   # best position across brands
            )
            .reset_index()
        )

        # Total company brand hits (for share of mentions)
        total_comp_hits = int(comp_agg["company_hit"].fillna(0).sum())

        for company_name, cgroup in comp_agg.groupby("company"):
            mention_hits = int(cgroup["company_hit"].fillna(0).sum())
            top3_hits    = int(cgroup["in_top3"].fillna(0).sum())
            num1_hits    = int(cgroup["is_num1"].fillna(0).sum())
            positions    = cgroup["position"].dropna()
            avg_pos      = round(float(positions.mean()), 2) if len(positions) > 0 else None
            share        = _safe_rate(mention_hits, total_comp_hits) if total_comp_hits else None

            output_rows.append({
                "week":               week,
                "run_date":           run_date,
                "provider":           provider,
                "model":              model,
                "entity_level":       "company",
                "company":            company_name,
                "brand":              None,
                "parent_ambiguous":   False,
                "methodology_version":methodology_version,
                "total_runs":         total_valid,
                "mention_hits":       mention_hits,
                "mention_rate":       _safe_rate(mention_hits, total_valid),
                "top3_hits":          top3_hits,
                "top3_rate":          _safe_rate(top3_hits, total_valid),
                "number1_hits":       num1_hits,
                "number1_rate":       _safe_rate(num1_hits, total_valid),
                "avg_position":       avg_pos,
                "share_of_mentions":  share,
            })

    # ── AI Composite ──────────────────────────────────────────────────────────
    metrics_df = pd.DataFrame(output_rows)
    composite_rows = _compute_composite(metrics_df, run_date, week, methodology_version)

    return pd.concat([metrics_df, pd.DataFrame(composite_rows)], ignore_index=True)


def _compute_composite(
    metrics_df: pd.DataFrame,
    run_date: str,
    week: str,
    methodology_version: str,
) -> list[dict]:
    """Equal-weighted average of provider-level mention rates → AI Composite rows."""
    rows = []
    if metrics_df.empty:
        return rows

    for entity_level in ["brand", "company"]:
        sub = metrics_df[metrics_df["entity_level"] == entity_level]
        if sub.empty:
            continue

        group_cols = ["company", "brand", "parent_ambiguous"] if entity_level == "brand" \
                     else ["company"]

        for keys, grp in sub.groupby(group_cols, dropna=False):
            if isinstance(keys, str):
                keys = (keys,)

            rates = grp["mention_rate"].dropna()
            if rates.empty:
                continue

            composite_rate = round(float(rates.mean()), 2)

            # Weighted sums for top3/number1 (equal-weight average)
            top3_avg  = round(float(grp["top3_rate"].dropna().mean()), 2) if grp["top3_rate"].notna().any() else None
            num1_avg  = round(float(grp["number1_rate"].dropna().mean()), 2) if grp["number1_rate"].notna().any() else None
            avg_pos   = round(float(grp["avg_position"].dropna().mean()), 2) if grp["avg_position"].notna().any() else None

            row = {
                "week":               week,
                "run_date":           run_date,
                "provider":           "AI Composite",
                "model":              None,
                "entity_level":       entity_level,
                "methodology_version":methodology_version,
                "total_runs":         None,
                "mention_hits":       None,
                "mention_rate":       composite_rate,
                "top3_hits":          None,
                "top3_rate":          top3_avg,
                "number1_hits":       None,
                "number1_rate":       num1_avg,
                "avg_position":       avg_pos,
                "share_of_mentions":  None,
            }

            if entity_level == "brand":
                row["company"]          = keys[0] if len(keys) > 0 else None
                row["brand"]            = keys[1] if len(keys) > 1 else None
                row["parent_ambiguous"] = keys[2] if len(keys) > 2 else False
            else:
                row["company"]          = keys[0] if len(keys) > 0 else None
                row["brand"]            = None
                row["parent_ambiguous"] = False

            rows.append(row)

    return rows
