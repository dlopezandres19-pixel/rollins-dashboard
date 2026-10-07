# AI Brand Visibility Tracker

An automated weekly measurement of how often pest-control brands are mentioned or recommended by major large language models (LLMs).

---

## 1. What It Measures

The tracker queries **OpenAI (ChatGPT)**, **Anthropic (Claude)**, and **Google (Gemini)** with a fixed set of 20 consumer-facing pest-control questions. It records which brands each model mentions and calculates weekly **Mention Rates** — the share of responses in which each company or brand appears.

The core question: *how visible are Rollins, Rentokil/Terminix, Aptive, Anticimex, and Massey Services when a consumer turns to an AI for pest-control advice?*

---

## 2. Methodology

| Dimension | Value |
|-----------|-------|
| Prompts | 20 fixed questions (see `config/prompts.json`) |
| Repetitions per prompt | 5 independent runs |
| Providers | OpenAI, Anthropic, Gemini |
| Total responses per week | 300 (100 per provider) |
| Methodology version | `v1` |

**Key design choices:**
- Every request is a fresh, independent conversation — no cross-request memory.
- The system prompt is minimal and neutral; it does not mention any tracked brand.
- Brand matching is deterministic regex — no second LLM is used for matching.
- Temperature is low-to-moderate (`0.3`) for reproducibility.
- External web search / browsing is **disabled** — responses reflect the model's base training.

**Primary KPI:**
> **Mention Rate** = responses containing the brand ÷ valid responses × 100 %

Additional metrics: Top-3 Inclusion Rate, #1 Recommendation Rate, Average Position (all `null` when the response is prose without a numbered list), Share of Brand Mentions.

**AI Composite:** equal-weighted average of the three provider mention rates. One provider having fewer valid responses does not change the weighting.

---

## 3. Repository Structure

```
ai-brand-tracker/
├── config/
│   ├── prompts.json                  # 20 fixed prompts (methodology v1)
│   └── Brand_Dictionary_AI_Tracker.xlsx  # Brand universe (source of truth)
├── data/
│   ├── raw/         YYYY-MM-DD_responses.csv     # Every individual LLM response
│   ├── weekly/      YYYY-MM-DD_brand_metrics.csv # Weekly metrics snapshot
│   └── master/
│       ├── ai_brand_visibility_company.csv       # Append-only company history
│       └── ai_brand_visibility_brand.csv         # Append-only brand history
├── src/
│   ├── run_tracker.py   # Main orchestrator
│   ├── providers.py     # OpenAI / Anthropic / Gemini query functions
│   ├── brand_matcher.py # Deterministic regex brand matching
│   ├── metrics.py       # Mention Rate, Top-3, position, AI Composite
│   └── utils.py         # CSV I/O, week helpers, path helpers
├── .github/
│   └── workflows/
│       └── ai-brand-tracker.yml   # Automated Friday run
└── requirements.txt
```

---

## 4. Brand Dictionary

`config/Brand_Dictionary_AI_Tracker.xlsx` has two columns:

| Company | Brand |
|---------|-------|
| Rollins | Orkin |
| Rollins | Northwest Exterminating |
| … | … |

**Rules:**
- This file is the **only** source of truth for the brand universe. Do not hardcode brands in Python.
- Add or remove brands here; the Python code picks them up automatically on the next run.
- **Northwest Exterminating** appears under both Rollins and Anticimex. The tracker records this as `parent_ambiguous = true` and does **not** assign the company hit to either parent automatically.
- Ambiguous / generic brand names (e.g., *Bug Out*, *The Killers*) use conservative context-aware patterns to avoid false positives.

---

## 5. Required API Keys

Store these as **GitHub Secrets** (Settings → Secrets and variables → Actions → New repository secret):

| Secret name | Description |
|-------------|-------------|
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `GEMINI_API_KEY` | Google Gemini API key |

> ⚠️ Never put API keys in source code, config files, or commit history.

---

## 6. GitHub Secrets Setup

1. Go to your repository → **Settings** → **Secrets and variables** → **Actions**.
2. Under **Secrets**, click **New repository secret** for each key above.
3. Under **Variables** (same page), add the model variables below.

---

## 7. Model Variables

Store these as **GitHub Variables** (not Secrets) so you can update them without changing code:

| Variable name | Recommended default | Notes |
|---------------|---------------------|-------|
| `OPENAI_MODEL` | `gpt-4o-mini` | Change to `gpt-4o` for higher quality |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Or any Claude model |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Or `gemini-1.5-pro` |

Historical records always store the **exact model ID** used, so model changes are tracked automatically in the data.

---

## 8. Running Locally

```bash
# Install dependencies
pip install -r ai-brand-tracker/requirements.txt

# Set environment variables
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="AIza..."
export OPENAI_MODEL="gpt-4o-mini"
export ANTHROPIC_MODEL="claude-haiku-4-5-20251001"
export GEMINI_MODEL="gemini-1.5-flash"

# Dry run (validates config, no API calls)
cd ai-brand-tracker
DRY_RUN=true python src/run_tracker.py

# Test run (2 prompts × 1 rep for quick validation)
RUNS_PER_PROMPT=1 PROVIDERS=openai python src/run_tracker.py

# Full production run (20 prompts × 5 reps × 3 providers = 300 responses)
python src/run_tracker.py
```

Output files are written to `data/raw/`, `data/weekly/`, and `data/master/` relative to the `ai-brand-tracker/` directory.

---

## 9. Triggering a Manual Run via GitHub Actions

1. Go to your repository → **Actions** → **AI Brand Visibility Tracker**.
2. Click **Run workflow**.
3. Optionally set:
   - **DRY_RUN** = `true` to validate without making API calls
   - **providers** = e.g., `openai` to run only one provider
   - **runs_per_prompt** = e.g., `1` for a quick test
4. Click **Run workflow** (green button).

---

## 10. Automated Weekly Job

The GitHub Actions workflow (`.github/workflows/ai-brand-tracker.yml`) runs automatically **every Friday at 07:00 UTC** (03:00 AM ET / 09:00 AM CET).

After a successful run it:
1. Saves `data/raw/YYYY-MM-DD_responses.csv` (every individual response)
2. Saves `data/weekly/YYYY-MM-DD_brand_metrics.csv` (aggregated weekly metrics)
3. Appends new rows to `data/master/ai_brand_visibility_company.csv` and `data/master/ai_brand_visibility_brand.csv`
4. Commits and pushes the new data files back to the repository

The job uses a **concurrency lock** so two simultaneous runs cannot corrupt the master files.

---

## 11. Output Data

### Raw responses (`data/raw/`)
One row per API call:

| Field | Description |
|-------|-------------|
| `run_date` | Date of the run (YYYY-MM-DD) |
| `week` | ISO week start (Monday, YYYY-MM-DD) |
| `methodology_version` | Always `v1` for this set of prompts |
| `provider` | `openai` / `anthropic` / `gemini` |
| `model` | Exact model ID returned by the API |
| `prompt_id` | 1–20 |
| `prompt_text` | Full prompt text |
| `repetition` | 1–5 |
| `timestamp_utc` | ISO 8601 UTC timestamp |
| `raw_response` | Full LLM response text |
| `prompt_tokens` | Input tokens (when available) |
| `completion_tokens` | Output tokens (when available) |
| `error` | `null` on success; error string on failure |

### Weekly metrics (`data/weekly/`) and master files (`data/master/`)
One row per (week × provider × entity):

| Field | Description |
|-------|-------------|
| `week` | ISO week start |
| `run_date` | Actual run date |
| `provider` | Provider name or `AI Composite` |
| `model` | Model ID (null for Composite) |
| `entity_level` | `brand` or `company` |
| `company` | Parent company name |
| `brand` | Brand name (null for company rows) |
| `parent_ambiguous` | `true` only for Northwest Exterminating |
| `total_runs` | Valid responses used as denominator |
| `mention_hits` | Responses containing this entity |
| `mention_rate` | Mention Rate (%) |
| `top3_hits` | Responses where entity appeared in positions 1–3 |
| `top3_rate` | Top-3 Inclusion Rate (%) |
| `number1_hits` | Responses where entity was #1 |
| `number1_rate` | #1 Recommendation Rate (%) |
| `avg_position` | Average position in numbered lists (null for prose) |
| `share_of_mentions` | Share of total tracked brand hits (%) |
| `methodology_version` | `v1` |

---

## 12. Model Changes

The exact model ID is stored with every observation. When you update `OPENAI_MODEL`, `ANTHROPIC_MODEL`, or `GEMINI_MODEL` in GitHub Variables:

- **Historical records are unchanged** — they retain the old model ID.
- **Future runs** use the new model ID automatically.
- The `model` column in the master files lets you later mark model transitions in a dashboard.
- Never regenerate historical observations to match a new model.

---

## Notes

- **Failed responses** are recorded with `error` set and excluded from the Mention Rate denominator. A failed response is never treated as a zero-hit.
- **Duplicate prevention**: if the weekly Action is re-run for the same week (e.g., after a partial failure), new rows replace old ones in the master files using the composite key `(week, provider, model, company/brand)`.
- **Prompts are fixed** for the lifetime of methodology `v1`. If prompts change, increment the methodology version and document the change date.
