"""Shared Groq LLM client with 429 retry and JSON parse fallback (M2).

All agents call through this module so the retry/parse logic lives once.
"""

import json
import os
import random
import sys
import time

import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "qwen/qwen3.8-27b"
GROQ_MAX_TOKENS = 2048
GROQ_MAX_429_ATTEMPTS = 3


class UnparseableResponse(Exception):
    """Raised when the LLM output is not valid JSON after a re-prompt."""

    def __init__(self, raw_text):
        super().__init__("LLM response was not valid JSON after re-prompt")
        self.raw_text = raw_text


class RateLimitedError(Exception):
    """Raised when Groq keeps returning 429 after all retry attempts."""


def get_api_key():
    return os.environ.get("GROQ_API_KEY", "")


def chat_raw(system_prompt, user_content, parse_error=None, api_key=None):
    """Single chat completion call; retries once on HTTP 429.

    When parse_error is given, the previous invalid response and the parse
    error are appended so the model can self-correct.
    """
    api_key = api_key or get_api_key()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set (use .env for local testing, secrets for Actions).")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    if parse_error:
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON. Parse error: "
                    f"{parse_error}. Respond again with ONLY valid JSON."
                ),
            }
        )

    body = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": GROQ_MAX_TOKENS,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    for attempt in range(GROQ_MAX_429_ATTEMPTS):
        resp = requests.post(GROQ_API_URL, headers=headers, json=body, timeout=120)
        if resp.status_code == 429 and attempt < GROQ_MAX_429_ATTEMPTS - 1:
            retry_after = resp.headers.get("Retry-After")
            delay = (float(retry_after) if retry_after else 5.0) + random.uniform(0, 3)
            print(f"Rate limited (HTTP 429); retrying in {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)
            continue
        if resp.status_code == 429:
            raise RateLimitedError(f"Groq rate limit persisted after {GROQ_MAX_429_ATTEMPTS} attempts")
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    raise RateLimitedError(f"Groq rate limit persisted after {GROQ_MAX_429_ATTEMPTS} attempts")


def parse_json(text):
    """Strip markdown code fences (if any) and parse JSON. Raises on failure."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            line for line in cleaned.splitlines() if not line.strip().startswith("```")
        ).strip()
        cleaned = cleaned.removeprefix("json").strip()
    return json.loads(cleaned)


def chat_json(system_prompt, user_content, api_key=None):
    """Chat then parse as JSON; re-prompts once with the parse error on failure.

    Raises UnparseableResponse (with raw_text) if it still fails.
    """
    text = chat_raw(system_prompt, user_content, api_key=api_key)
    try:
        return parse_json(text)
    except (json.JSONDecodeError, ValueError) as err:
        text = chat_raw(system_prompt, user_content, parse_error=str(err), api_key=api_key)
        try:
            return parse_json(text)
        except (json.JSONDecodeError, ValueError):
            raise UnparseableResponse(text)


def chat_issues(system_prompt, diff_text, api_key=None):
    """Structured 'issues' call with a graceful fallback.

    Returns a list of issue dicts. If the response is unparseable after the
    re-prompt, returns a single placeholder issue carrying the raw text so
    the workflow never crashes on a bad parse.
    """
    user_content = f"Here is the pull request diff:\n\n{diff_text}"
    try:
        data = chat_json(system_prompt, user_content, api_key=api_key)
    except UnparseableResponse as err:
        return [{"file": "?", "message": f"[unparseable response] {err.raw_text[:400]}"}]
    except RateLimitedError as err:
        return [{"file": "?", "message": f"[rate limited - review skipped] {err}"}]
    issues = data.get("issues")
    if not isinstance(issues, list):
        return [{"file": "?", "message": f"[unexpected schema] {str(data)[:400]}"}]
    return issues
