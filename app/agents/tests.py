"""Tests agent: flags changed code lacking test coverage in the diff (M2)."""

from llm_client import chat_issues

SYSTEM_PROMPT = (
    "You are a test-coverage reviewer. Your ONLY job is to identify changed "
    "or added functions in the pull request diff that lack corresponding "
    "test coverage. "
    "Look at the files in the diff: when a source file changes but no test "
    "file (test_*.py, *_test.py, tests/, spec files) in the same diff touches "
    "the changed functions, flag the gap. "
    "Do NOT comment on code quality, logic, or security — those are handled "
    "by other reviewers. "
    "Respond with ONLY a valid JSON object in this exact shape: "
    '{"issues": [{"file": "<file path of the untested code>", '
    '"message": "<which function(s) lack coverage and why>"}]}. '
    "Note: there is no severity field — you flag gaps, you do not rank them. "
    "Use an empty array if everything changed has test coverage. Do not "
    "include any text outside the JSON object."
)


def find_gaps(diff_text):
    return chat_issues(SYSTEM_PROMPT, diff_text)
