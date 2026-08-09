"""PR review bot entrypoint (M1): one LLM call, one posted comment.

Reads the PR number from the GitHub Actions event payload (GITHUB_EVENT_PATH),
fetches the diff, asks Groq for a structured JSON review, and posts a single
Markdown comment grouped by severity.
"""

import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

try:
    from github_client import GitHubClient
except ImportError:
    from app.github_client import GitHubClient

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_MAX_TOKENS = 2048

SEVERITY_ORDER = {"critical": 0, "warning": 1, "nit": 2}

SYSTEM_PROMPT = (
    "You are a senior code reviewer. Review the provided pull request diff "
    "and respond with ONLY a valid JSON object in this exact shape: "
    '{"issues": [{"severity": "critical|warning|nit", "file": "<file path>", '
    '"line": <int or null>, "message": "<concise issue description>"}]}. '
    "Use critical for bugs or security problems, warning for likely problems, "
    "nit for minor style. Use an empty array if the diff is clean. "
    "Do not include any text outside the JSON object."
)


def load_event_payload():
    """Read and parse the GitHub Actions event payload file."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise SystemExit(
            "GITHUB_EVENT_PATH is not set; run inside GitHub Actions, or set "
            "it to a local event JSON for testing."
        )
    with open(event_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_pr_number():
    payload = load_event_payload()
    if "number" not in payload:
        raise SystemExit("No 'number' field in event payload.")
    return payload["number"]


def call_groq(diff, api_key, parse_error=None):
    """Single chat completion call; retries once on HTTP 429.

    When parse_error is given, the previous invalid response and the parse
    error are appended so the model can self-correct.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Here is the pull request diff:\n\n{diff}"},
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

    for attempt in range(2):
        resp = requests.post(GROQ_API_URL, headers=headers, json=body, timeout=120)
        if resp.status_code == 429 and attempt == 0:
            retry_after = resp.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else 5.0
            print(f"Rate limited (HTTP 429); retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    raise RuntimeError("Groq rate limit persisted after retry")


def parse_issues(text):
    """Extract the issues list from the LLM response. Raises on bad parse."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            line for line in cleaned.splitlines() if not line.strip().startswith("```")
        ).strip()
        cleaned = cleaned.removeprefix("json").strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
        raise ValueError("Response JSON is missing an 'issues' list")
    return data["issues"]


def format_comment(issues, truncated=False):
    """Render the issues list as a single Markdown comment grouped by severity."""
    if not issues:
        return "### Code Review Bot\n\nNo issues found in this diff."
    lines = ["### Code Review Bot", ""]
    if truncated:
        lines.append(
            "> Diff was too large; only the first changed files were reviewed.\n"
        )
    grouped = {}
    for issue in issues:
        severity = issue.get("severity")
        if severity not in SEVERITY_ORDER:
            severity = "nit"
        grouped.setdefault(severity, []).append(issue)
    for severity in sorted(grouped, key=lambda s: SEVERITY_ORDER[s]):
        lines.append(f"**{severity.capitalize()} ({len(grouped[severity])})**")
        lines.append("")
        for issue in grouped[severity]:
            location = f"`{issue.get('file', '?')}`"
            line = issue.get("line")
            if isinstance(line, int):
                location += f":{line}"
            lines.append(f"- {location} — {issue.get('message', '')}")
        lines.append("")
    return "\n".join(lines)


def post_raw_comment(client, pr_number, text):
    """Fallback: post the raw LLM text when structured parsing fails."""
    body = f"### Code Review Bot\n\nParsed response was invalid JSON; showing raw output:\n\n{text}"
    url = client.post_comment(pr_number, body)
    print(f"Raw comment posted: {url}")


def main():
    load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise SystemExit("GROQ_API_KEY is not set (use .env for local testing, secrets for Actions).")

    pr_number = get_pr_number()
    client = GitHubClient()

    diff, truncated = client.fetch_pr_diff(pr_number)
    print(f"Reviewing PR #{pr_number} ({len(diff)} chars of diff, truncated={truncated})")

    text = call_groq(diff, api_key)
    try:
        issues = parse_issues(text)
    except (json.JSONDecodeError, ValueError) as err:
        print(f"Initial parse failed ({err}); re-prompting with parse error", file=sys.stderr)
        try:
            text = call_groq(diff, api_key, parse_error=str(err))
            issues = parse_issues(text)
        except (json.JSONDecodeError, ValueError, requests.RequestException) as err2:
            print(f"Parse still failed after re-prompt ({err2}); posting raw text", file=sys.stderr)
            try:
                post_raw_comment(client, pr_number, text)
            except requests.RequestException as post_err:
                print(f"WARNING: could not post raw comment: {post_err}", file=sys.stderr)
            return

    body = format_comment(issues, truncated)
    try:
        url = client.post_comment(pr_number, body)
        print(f"Comment posted: {url}")
    except requests.RequestException as err:
        # Expected for fork PRs under the plain pull_request trigger (M1 limitation).
        print(f"WARNING: could not post comment: {err}", file=sys.stderr)


if __name__ == "__main__":
    main()
