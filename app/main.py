"""PR review bot entrypoint (M4): should_skip + supervisor layer.

Reads the PR number from the GitHub Actions event payload (GITHUB_EVENT_PATH),
fetches the diff, optionally short-circuits on tiny diffs, runs the agent graph
with supervisor merge/dedup/rank/FP-filter, and posts the combined comment.
"""

import json
import os
import sys

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from github_client import GitHubClient  # noqa: E402
from graph import build_graph  # noqa: E402
from supervisor import should_skip_review  # noqa: E402

GRAPH = build_graph()

SMALL_DIFF_COMMENT = (
    "### Code Review Bot\n\n"
    "This diff is too small for a full review (fewer than 5 meaningful "
    "changed lines or whitespace/comment-only). No issues to report."
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


def main():
    load_dotenv()
    if not os.environ.get("GROQ_API_KEY"):
        raise SystemExit("GROQ_API_KEY is not set (use .env for local testing, secrets for Actions).")

    pr_number = get_pr_number()
    client = GitHubClient()

    diff, truncated = client.fetch_pr_diff(pr_number)
    print(f"Reviewing PR #{pr_number} ({len(diff)} chars of diff, truncated={truncated})")

    if should_skip_review(diff):
        print("Diff too small for full review; posting short comment and skipping agents.")
        try:
            url = client.post_comment(pr_number, SMALL_DIFF_COMMENT)
            print(f"Comment posted: {url}")
        except requests.RequestException as err:
            print(f"WARNING: could not post comment: {err}", file=sys.stderr)
        return

    state = GRAPH.invoke(
        {
            "diff_text": diff,
            "truncated": truncated,
            "repo_path": os.getcwd(),
            "reviewer_result": [],
            "security_result": [],
            "test_result": [],
            "summary_result": "",
            "semgrep_findings": [],
            "supervisor_result": [],
        }
    )

    try:
        url = client.post_comment(pr_number, state["comment"])
        print(f"Comment posted: {url}")
    except requests.RequestException as err:
        # Expected for fork PRs under the plain pull_request trigger (M1 limitation).
        print(f"WARNING: could not post comment: {err}", file=sys.stderr)


if __name__ == "__main__":
    main()
