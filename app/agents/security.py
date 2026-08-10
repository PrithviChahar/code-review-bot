"""Security agent: triages Semgrep findings + catches pattern-missed issues (M3).

Receives the Semgrep findings (structured) alongside the diff. Its job is to
triage and explain Semgrep's output, filter false positives, and still catch
what pattern matching misses (e.g. business-logic auth issues).
"""

from llm_client import chat_issues

SYSTEM_PROMPT = (
    "You are a security triage specialist in a code review pipeline. "
    "You receive TWO inputs: (1) findings from Semgrep, an automated static "
    "analysis tool, and (2) the pull request diff. "
    "PRIMARY JOB — triage Semgrep's findings: decide which are real and "
    "relevant to THIS diff, merge duplicates, correct severity (Semgrep "
    "tends to over-report), filter obvious false positives and findings not "
    "related to files changed in the diff, and explain each kept finding in "
    "plain English with its file and line. "
    "SECONDARY JOB — find security issues Semgrep's pattern matching misses, "
    "for example business-logic authentication or authorization gaps, unsafe "
    "handling of user input, insecure defaults. "
    "Anchor your output on the Semgrep findings; when a finding came from "
    "Semgrep, say so in the message. If Semgrep reported nothing, review the "
    "diff directly. "
    'Respond with ONLY a valid JSON object in this exact shape: '
    '{"issues": [{"severity": "critical|warning|nit", "file": "<file path>", '
    '"line": <int or null>, "message": "<concise issue description>"}]}. '
    "Use critical for exploitable vulnerabilities, warning for potential "
    "risks, nit for hardening suggestions. Use an empty array if nothing is "
    "real. Do not include any text outside the JSON object."
)


def _format_findings(findings):
    if not findings:
        return "Semgrep reported no findings."
    lines = []
    for f in findings:
        loc = f"{f.get('file', '?')}:{f.get('line') or '?'}"
        lines.append(
            f"- [{f.get('severity', '?')}] {f.get('rule_id', '?')} @ {loc} — "
            f"{f.get('message', '')}"
        )
    return "Semgrep findings:\n" + "\n".join(lines)


def scan(diff_text, semgrep_findings):
    user_content = (
        f"{_format_findings(semgrep_findings)}\n\n"
        f"Here is the pull request diff:\n\n{diff_text}"
    )
    return chat_issues(SYSTEM_PROMPT, user_content)
