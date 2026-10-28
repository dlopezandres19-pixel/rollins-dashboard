# AI Regional Brand Tracker — `v1-regional`

Measures pest-control brand visibility in AI responses **with web search enabled**, broken down by US region.

## How it differs from the national tracker (`v1`)

| Dimension | National (`v1`) | Regional (`v1-regional`) |
|-----------|-----------------|--------------------------|
| Web search | **OFF** — measures model prior only | **ON** — measures prior + live retrieval |
| Providers | OpenAI, Anthropic, Gemini | **OpenAI, Gemini only** (Anthropic has no native web search API) |
| Geography | Single national query | 4 regions: Southeast, Northeast, Midwest, West |
| Prompts | 20 | 10 (regional variants, `[REGION]` replaced at runtime) |
| Reps | 5 | 3 |
| Cadence | Weekly | Weekly |
| API calls/week | 300 | 240 |

## What this measures

> **Hypothesis:** Does the Rollins vs. Rentokil/Terminix balance change by region when web retrieval is active?

When web search is ON, the model can pull live local content — reviews, local landing pages, Google Business Profiles — before answering. This tests whether Rollins's local digital presence (or lack of it) affects brand visibility differently by geography.

## Metrics

- **Mention Rate** — % of responses that mention the brand
- **Top-3 Rate** — % of responses where brand appears in first 3 mentions
- **#1 Rate** — % of responses where brand is mentioned first (proxy for "recommended first")

Share of Voice is calculated client-side in the dashboard from `mention_hits`.

## AI Composite (regional)

AI Composite = average of OpenAI + Gemini only (Claude excluded — no comparable web-search methodology).
This is noted in the dashboard.

## Setup

### GitHub Secrets required

```
OPENAI_API_KEY
GEMINI_API_KEY
```

Set these in **Settings → Secrets and variables → Actions**.

### Local test run

```bash
cd ai-regional-tracker/src
pip install -r ../requirements.txt

# Dry run (no API calls, just prints prompts)
python run_tracker.py --dry-run

# Single provider + region
OPENAI_API_KEY=sk-... python run_tracker.py --provider openai --region southeast

# Full run
OPENAI_API_KEY=sk-... GEMINI_API_KEY=AI... python run_tracker.py
```

### Folder structure

```
ai-regional-tracker/
├── config/
│   ├── prompts.json        # 10 prompts with [REGION] placeholder
│   └── regions.json        # 4 regions with prompt_label and state list
├── src/
│   ├── run_tracker.py      # Main entry point
│   ├── providers.py        # OpenAI (web_search_preview) + Gemini (google_search)
│   ├── brand_matcher.py    # Deterministic regex brand matching
│   └── utils.py            # Paths, dates, helpers
├── data/
│   ├── raw/                # One JSON per API call (never committed to main branch)
│   └── weekly/             # Aggregated CSV per (provider, region, week)
├── requirements.txt
└── README.md
```

## Security constraints

These must never be relaxed:

- API keys never in source code, config files, logs or committed files
- System prompt must NOT mention any tracked brand name
- System prompt must NOT reveal this is a benchmarking exercise
- Do NOT instruct the model to return a fixed number of companies
- Do NOT tell the model which companies are being monitored
- Brand matching is deterministic regex — never another LLM call
