"""
providers.py — API calls to OpenAI and Gemini with web search ENABLED.

Regional tracker methodology (v1-regional):
  - Web search is ON for both providers.
  - Claude/Anthropic is excluded: no native web search in the Anthropic API.
    Adding Claude here would require an external search API + manual injection,
    which is a different methodology and not comparable to the other two.
  - AI Composite for regional = average of OpenAI + Gemini only (noted in dashboard).

Security constraints (must not be relaxed):
  - API keys are NEVER in source code. Read from environment variables only.
  - System prompt must NOT mention any tracked brand names.
  - System prompt must NOT reveal that this is a benchmarking exercise.
  - Do NOT instruct the model to return a fixed number of companies.
  - Do NOT tell the model which companies are being monitored.
"""

import json
import time
from typing import Optional

from utils import log, require_env


# ---------------------------------------------------------------------------
# OpenAI — web search via the built-in web_search_preview tool
# ---------------------------------------------------------------------------

def call_openai(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str = "gpt-4o",
    max_tokens: int = 1024,
    temperature: float = 0.7,
    retries: int = 3,
    backoff: float = 5.0,
) -> Optional[str]:
    """
    Call OpenAI with web_search_preview enabled.
    Returns the text of the final assistant message, or None on failure.
    """
    try:
        import openai
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install openai")

    api_key = require_env("OPENAI_API_KEY")
    client = openai.OpenAI(api_key=api_key)

    for attempt in range(1, retries + 1):
        try:
            response = client.responses.create(
                model=model,
                tools=[{"type": "web_search_preview"}],
                tool_choice="auto",
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
            # Extract the last text output block
            for item in reversed(response.output):
                if getattr(item, "type", None) == "message":
                    for block in item.content:
                        if getattr(block, "type", None) == "output_text":
                            return block.text
            log(f"[OpenAI] No text output in response (attempt {attempt})")
        except Exception as exc:
            log(f"[OpenAI] Error attempt {attempt}/{retries}: {exc}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None


# ---------------------------------------------------------------------------
# Gemini — web search via google_search grounding
# ---------------------------------------------------------------------------

def call_gemini(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str = "gemini-2.0-flash-001",
    max_tokens: int = 1024,
    temperature: float = 0.7,
    retries: int = 3,
    backoff: float = 5.0,
) -> Optional[str]:
    """
    Call Gemini with google_search grounding enabled.
    Returns the text of the response, or None on failure.
    """
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError(
            "google-generativeai package not installed. "
            "Run: pip install google-generativeai"
        )

    api_key = require_env("GEMINI_API_KEY")
    genai.configure(api_key=api_key)

    generation_config = {
        "max_output_tokens": max_tokens,
        "temperature": temperature,
    }

    # google_search tool enables grounding with live web results
    tools = [{"google_search": {}}]

    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    for attempt in range(1, retries + 1):
        try:
            model_obj = genai.GenerativeModel(
                model_name=model,
                generation_config=generation_config,
                tools=tools,
                system_instruction=system_prompt,
            )
            response = model_obj.generate_content(user_prompt)
            if response.text:
                return response.text
            log(f"[Gemini] Empty response (attempt {attempt})")
        except Exception as exc:
            log(f"[Gemini] Error attempt {attempt}/{retries}: {exc}")
            if attempt < retries:
                time.sleep(backoff * attempt)
    return None


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, callable] = {
    "openai": call_openai,
    "gemini": call_gemini,
}

PROVIDER_MODELS: dict[str, str] = {
    "openai": "gpt-4o",
    "gemini": "gemini-2.0-flash-001",
}
