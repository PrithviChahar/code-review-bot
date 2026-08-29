"""Supervisor layer: merge, dedup, rank, and FP-filter (M4).

Pure Python merge + one LLM call for FP filtering. Follows the same
graceful-degradation pattern: if the LLM call fails, all issues pass
through with likely_fp=False rather than blocking the comment.
"""

import json
import re
import sys

SEVERITY_ORDER = {"critical": 0, "warning": 1, "nit": 2}
MIN_DIFF_LINES = 5


def _normalize_msg(message):
    msg = message.lower().strip()
    msg = re.sub(r"\s+", " ", msg)
    msg = re.sub(r"[^a-z0-9 ]", " ", msg)
    msg = re.sub(r"\s+", " ", msg)
    STOP = {"a", "an", "the", "in", "on", "of", "for", "to", "and", "or",
            "is", "it", "as", "by", "be", "at", "from", "with", "this",
            "that", "does", "do", "not", "no", "are", "was", "were", "has",
            "have", "had", "could", "should", "may", "might"}
    return " ".join(w for w in msg.split() if w not in STOP and len(w) > 1)


def _messages_similar(msg_a, msg_b):
    na, nb = _normalize_msg(msg_a), _normalize_msg(msg_b)
    if not na or not nb:
        return na == nb
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    wa, wb = set(na.split()), set(nb.split())
    inter = wa & wb
    smaller = min(len(wa), len(wb))
    if smaller == 0:
        return False
    return len(inter) / smaller >= 0.6


def _location_key(issue):
    f = issue.get("file", "")
    l = issue.get("line")
    if isinstance(l, int):
        return f"{f}:{l}"
    return f"{f}:"


def merge_and_rank(reviewer_result, security_result, diff_text="", truncated=False):
    """Merge reviewer + security issues, dedup, sort by severity.

    Returns a list of issues with {"severity", "file", "line", "message"}.
    test_result stays separate (no severity field).
    """
    combined = []
    for issue in (reviewer_result or []):
        if not isinstance(issue, dict):
            continue
        combined.append({**issue, "_source": "Reviewer"})
    for issue in (security_result or []):
        if not isinstance(issue, dict):
            continue
        combined.append({**issue, "_source": "Security"})

    if not combined:
        return []

    by_loc = {}
    for issue in combined:
        key = _location_key(issue)
        by_loc.setdefault(key, []).append(issue)

    merged = []
    for group in by_loc.values():
        if len(group) == 1:
            issue = {k: v for k, v in group[0].items() if k != "_source"}
            issue["_source"] = group[0]["_source"]
            merged.append(issue)
            continue

        dominated = False
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if _messages_similar(a.get("message", ""), b.get("message", "")):
                    dominated = True
                    break
            if dominated:
                break

        if dominated:
            sources = sorted(set(i["_source"] for i in group))
            best = min(group, key=lambda i: SEVERITY_ORDER.get(i.get("severity", "nit"), 99))
            merged.append({
                "severity": best.get("severity", "nit"),
                "file": best.get("file", "?"),
                "line": best.get("line"),
                "message": best.get("message", ""),
                "_source": " + ".join(sources),
            })
        else:
            sources = sorted(set(i["_source"] for i in group))
            for issue in group:
                entry = {k: v for k, v in issue.items() if k != "_source"}
                entry["_source"] = " + ".join(sources)
                merged.append(entry)

    merged.sort(key=lambda i: SEVERITY_ORDER.get(i.get("severity", "nit"), 99))
    return merged


def should_skip_review(diff_text):
    """Deterministic check: skip full review for tiny/trivial diffs.

    Returns True if the diff has fewer than MIN_DIFF_LINES meaningful lines
    or is whitespace/comment-only. Saves all Groq calls when true.
    """
    lines = diff_text.strip().splitlines()
    meaningful = 0
    for line in lines:
        stripped = line.lstrip()
        if not stripped:
            continue
        if stripped.startswith("+++") or stripped.startswith("---"):
            continue
        if stripped.startswith("+") or stripped.startswith("-"):
            content = stripped[1:].strip()
            if content and not re.match(r"^(#[^\n]*|//[^\n]*|/\*|\*|#)", content):
                meaningful += 1
    return meaningful < MIN_DIFF_LINES


def filter_false_positives(merged_issues):
    """One LLM call: flag likely false positives without removing them.

    Returns the same list with "likely_fp": bool on each item.
    If the LLM call fails, falls back to likely_fp=False for everything.
    """
    from llm_client import chat_json, UnparseableResponse, RateLimitedError

    if not merged_issues:
        return merged_issues

    issues_for_llm = [
        {"id": i, "severity": iss["severity"], "file": iss.get("file", "?"),
         "line": iss.get("line"), "message": iss.get("message", "")}
        for i, iss in enumerate(merged_issues)
    ]

    system_prompt = (
        "You are a false-positive reviewer for a code review bot. "
        "Given a list of issues flagged by automated reviewers, decide which "
        "are likely false positives. Mark ONLY clear false positives — when in "
        "doubt, keep the issue. Never silently remove items.\n\n"
        "IMPORTANT EXAMPLES from this project's history:\n\n"
        "EXAMPLE 1 — False positive (flag as likely_fp=True):\n"
        'Issue: "Flagging SYSTEM_PROMPT (all-caps constant name) as a magic '
        'number is a false positive — all-caps naming for constants is correct '
        'PEP8, not a bug"\n'
        "Reason: ALL_CAPS for module-level constants is standard PEP8 convention.\n\n"
        "EXAMPLE 2 — False positive (flag as likely_fp=True):\n"
        'Issue: "Flagging a PATH-existence check as missing when the code '
        'already performs that exact check earlier in the same function is a '
        'false positive — verify the flagged behavior is not already present '
        'before including it"\n'
        "Reason: the code already performs the check the reviewer says is missing.\n\n"
        "Respond with ONLY a valid JSON object: "
        '{"flags": [{"id": <int>, "likely_fp": <bool>, "reason": "<short reason or empty string>"}]}.\n'
        "If unsure, set likely_fp to false. Do not include any text outside the JSON."
    )

    user_content = json.dumps(issues_for_llm, indent=1)

    try:
        result = chat_json(system_prompt, user_content)
    except (UnparseableResponse, RateLimitedError, Exception) as err:
        print(f"WARNING: FP filter failed ({err}); marking all as likely_fp=False", file=sys.stderr)
        return [{**iss, "likely_fp": False} for iss in merged_issues]

    flags = result.get("flags") if isinstance(result, dict) else []
    flag_map = {}
    if isinstance(flags, list):
        for f in flags:
            fid = f.get("id")
            if isinstance(fid, int) and 0 <= fid < len(merged_issues):
                flag_map[fid] = f.get("likely_fp", False)

    return [
        {**iss, "likely_fp": flag_map.get(i, False)}
        for i, iss in enumerate(merged_issues)
    ]
