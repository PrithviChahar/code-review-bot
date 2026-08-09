"""GitHub API client for the PR review bot (M1)."""

import os

import requests

GITHUB_API_URL = "https://api.github.com"

# ~6000 token budget for the diff (rough 4 chars/token estimate).
MAX_DIFF_CHARS = 24000


class GitHubClient:
    """Thin wrapper over the GitHub REST API using GITHUB_TOKEN."""

    def __init__(self, token=None, repository=None):
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.repository = repository or os.environ.get("GITHUB_REPOSITORY", "")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _url(self, path):
        return f"{GITHUB_API_URL}/repos/{self.repository}{path}"

    def fetch_pr_diff(self, pr_number):
        """Fetch the PR diff via the files endpoint.

        Returns (diff_text, truncated). If the diff exceeds ~6000 tokens,
        only the first N files are kept and a truncation note is appended.
        """
        resp = requests.get(
            self._url(f"/pulls/{pr_number}/files"),
            headers=self.headers,
            timeout=30,
        )
        resp.raise_for_status()
        files = resp.json()

        parts = []
        used_chars = 0
        included = 0
        truncated = False
        for f in files:
            header = f"### {f.get('filename', '?')} ({f.get('status', '?')}, +{f.get('additions', 0)}/-{f.get('deletions', 0)})\n"
            patch = f.get("patch", "")
            block = f"{header}{patch}\n\n"
            if used_chars + len(block) > MAX_DIFF_CHARS:
                truncated = True
                break
            parts.append(block)
            used_chars += len(block)
            included += 1

        diff_text = "".join(parts).strip()
        if truncated:
            skipped = len(files) - included
            diff_text += (
                f"\n\n[Note: diff truncated to the first {included} changed "
                f"file(s); {skipped} file(s) not reviewed]"
            )
        return diff_text, truncated

    def post_comment(self, pr_number, body):
        """Post a single issue (PR) comment. Returns the comment URL."""
        resp = requests.post(
            self._url(f"/issues/{pr_number}/comments"),
            headers=self.headers,
            json={"body": body},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["html_url"]
