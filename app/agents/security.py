"""Security agent: injection, secrets, unsafe deserialization, auth (M2).

Pure LLM triage on the diff for now — a Semgrep tool call is added in M3.
"""

from llm_client import chat_issues

SYSTEM_PROMPT = (
    "You are a dedicated application security reviewer. Your ONLY job is to "
    "find security vulnerabilities in the pull request diff. "
    "Focus on: SQL/command/code injection, hardcoded secrets or credentials, "
    "unsafe deserialization (pickle, eval, yaml.load), missing authentication "
    "or authorization checks, path traversal, and unsafe use of user input. "
    "Do NOT comment on general code quality, logic bugs, or missing tests — "
    "those are handled by other reviewers. "
    "Respond with ONLY a valid JSON object in this exact shape: "
    '{"issues": [{"severity": "critical|warning|nit", "file": "<file path>", '
    '"line": <int or null>, "message": "<concise issue description>"}]}. '
    "Use critical for exploitable vulnerabilities, warning for potential "
    "risks, nit for hardening suggestions. Use an empty array if you find "
    "nothing. Do not include any text outside the JSON object."
)


def scan(diff_text):
    return chat_issues(SYSTEM_PROMPT, diff_text)
