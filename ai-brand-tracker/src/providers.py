"""
providers.py
Unified interface for querying OpenAI, Anthropic, and Google Gemini.

Model IDs and API keys come from environment variables — never hardcoded.
All providers use low-to-moderate temperature for reproducibility.
"""

import os
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Settings (overridable via env)
# ---------------------------------------------------------------------------
MAX_TOKENS   = int(os.environ.get("MAX_OUTPUT_TOKENS", "512"))
TEMPERATURE  = float(os.environ.get("LLM_TEMPERATURE", "0.3"))
RETRY_MAX    = int(os.environ.get("RETRY_MAX", "3"))
RETRY_BASE_S = float(os.environ.get("RETRY_BASE_SECONDS", "5"))

SYSTEM_CONTEXT = (
    "You are answering a US consumer asking for pest-control recommendations. "
    "Answer the question naturally and independently. "
    "Do not assume any prior conversation context."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _backoff(attempt: int) -> float:
    return RETRY_BASE_S * (2 ** attempt)


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------
def query_openai(prompt_text: str) -> dict:
    import openai

    api_key = os.environ["OPENAI_API_KEY"]
    model   = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client  = openai.OpenAI(api_key=api_key)

    for attempt in range(RETRY_MAX):
        try:
            ts = _utc_now()
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_CONTEXT},
                    {"role": "user",   "content": prompt_text},
                ],
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
            )
            return {
                "provider":         "openai",
                "model":            resp.model,
                "timestamp_utc":    ts,
                "raw_response":     resp.choices[0].message.content,
                "prompt_tokens":    resp.usage.prompt_tokens if resp.usage else None,
                "completion_tokens":resp.usage.completion_tokens if resp.usage else None,
                "error":            None,
            }
        except openai.RateLimitError as e:
            wait = _backoff(attempt)
            logger.warning(f"OpenAI rate limit (attempt {attempt+1}), waiting {wait}s: {e}")
            time.sleep(wait)
        except openai.APITimeoutError as e:
            wait = _backoff(attempt)
            logger.warning(f"OpenAI timeout (attempt {attempt+1}), waiting {wait}s: {e}")
            time.sleep(wait)
        except Exception as e:
            wait = _backoff(attempt)
            logger.warning(f"OpenAI error (attempt {attempt+1}), waiting {wait}s: {e}")
            time.sleep(wait)

    return {"provider": "openai", "model": model, "timestamp_utc": _utc_now(),
            "raw_response": None, "prompt_tokens": None, "completion_tokens": None,
            "error": "failed_after_retries"}


# ---------------------------------------------------------------------------
# Anthropic / Claude
# ---------------------------------------------------------------------------
def query_anthropic(prompt_text: str) -> dict:
    import anthropic

    api_key = os.environ["ANTHROPIC_API_KEY"]
    model   = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    client  = anthropic.Anthropic(api_key=api_key)

    for attempt in range(RETRY_MAX):
        try:
            ts = _utc_now()
            resp = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_CONTEXT,
                messages=[{"role": "user", "content": prompt_text}],
                temperature=TEMPERATURE,
            )
            return {
                "provider":         "anthropic",
                "model":            resp.model,
                "timestamp_utc":    ts,
                "raw_response":     resp.content[0].text,
                "prompt_tokens":    resp.usage.input_tokens if resp.usage else None,
                "completion_tokens":resp.usage.output_tokens if resp.usage else None,
                "error":            None,
            }
        except anthropic.RateLimitError as e:
            wait = _backoff(attempt)
            logger.warning(f"Anthropic rate limit (attempt {attempt+1}), waiting {wait}s: {e}")
            time.sleep(wait)
        except Exception as e:
            wait = _backoff(attempt)
            logger.warning(f"Anthropic error (attempt {attempt+1}), waiting {wait}s: {e}")
            time.sleep(wait)

    return {"provider": "anthropic", "model": model, "timestamp_utc": _utc_now(),
            "raw_response": None, "prompt_tokens": None, "completion_tokens": None,
            "error": "failed_after_retries"}


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------
def query_gemini(prompt_text: str) -> dict:
    import google.generativeai as genai

    api_key = os.environ["GEMINI_API_KEY"]
    model   = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
    genai.configure(api_key=api_key)
    gm = genai.GenerativeModel(
        model_name=model,
        system_instruction=SYSTEM_CONTEXT,
        generation_config=genai.types.GenerationConfig(
            temperature=TEMPERATURE,
            max_output_tokens=MAX_TOKENS,
        ),
    )

    for attempt in range(RETRY_MAX):
        try:
            ts   = _utc_now()
            resp = gm.generate_content(prompt_text)
            text = resp.text
            usage = resp.usage_metadata if hasattr(resp, "usage_metadata") else None
            return {
                "provider":         "gemini",
                "model":            model,
                "timestamp_utc":    ts,
                "raw_response":     text,
                "prompt_tokens":    usage.prompt_token_count if usage else None,
                "completion_tokens":usage.candidates_token_count if usage else None,
                "error":            None,
            }
        except Exception as e:
            # Gemini surfaces rate limits as generic exceptions; check message
            msg = str(e).lower()
            wait = _backoff(attempt)
            if "quota" in msg or "rate" in msg or "429" in msg:
                logger.warning(f"Gemini rate limit (attempt {attempt+1}), waiting {wait}s: {e}")
            else:
                logger.warning(f"Gemini error (attempt {attempt+1}), waiting {wait}s: {e}")
            time.sleep(wait)

    return {"provider": "gemini", "model": model, "timestamp_utc": _utc_now(),
            "raw_response": None, "prompt_tokens": None, "completion_tokens": None,
            "error": "failed_after_retries"}


PROVIDER_FNS = {
    "openai":     query_openai,
    "anthropic":  query_anthropic,
    "gemini":     query_gemini,
}
