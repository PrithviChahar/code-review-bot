# PR Review Bot (M1)

Minimal multi-agent PR review bot — milestone 1: one workflow, one LLM call, one
posted comment. Triggered on every pull request (`opened`, `synchronize`,
`reopened`), it fetches the diff via the GitHub API, asks Groq
(`llama-3.3-70b-versatile`) for a structured JSON review, and posts a single
Markdown comment grouped by severity (critical / warning / nit).

Later milestones add parallel review agents (LangGraph), a supervisor, Semgrep
security scanning, test-coverage analysis, dedup, and an eval harness.

## Setup (deploy to Actions)

1. Push this repo to GitHub.
2. Go to repo **Settings → Secrets and variables → Actions**.
3. Add `GROQ_API_KEY` (get a free key at https://console.groq.com).
4. Open a pull request on the repo — the bot reviews it and comments.

No servers to host; GitHub Actions is the runtime.

## Testing locally against a fake diff

Before wiring up Actions, you can run the bot locally. It will call the real
Groq API but won't need a real PR — and posting the comment will fail softly
(no token / no repo), so only the review logic runs.

1. Install dependencies: `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and set `GROQ_API_KEY`.
3. Create a fake event file `event.json` with: `{"number": 1}`
4. Run:

```powershell
$env:GITHUB_EVENT_PATH = "C:\path\to\event.json"
$env:GITHUB_REPOSITORY = "you/your-repo"   # fake repo is fine
$env:GITHUB_TOKEN = ""                     # skip real posting
python app/main.py
```

Expected output: it logs the diff size, calls Groq, prints
`WARNING: could not post comment` (fine locally), and prints the formatted
comment text it would have posted.

To see the actual rendered comment without posting, run a one-liner:

```powershell
python -c "from app.main import format_comment, parse_issues; print(format_comment(parse_issues(open('sample_llm_output.json').read())))"
```

## Known M1 limitations

- **Fork PRs:** under the default `pull_request` trigger, forked-repo PRs get
  a read-only `GITHUB_TOKEN` and no secrets, so `GROQ_API_KEY` is absent and
  comment posting fails. Expected for M1; not a bug to fix here.
- **Large diffs:** diffs over ~6000 tokens are truncated to the first changed
  files, with a note appended to the review.
- No dedup: a new comment is posted on every push to the PR (`synchronize`).
