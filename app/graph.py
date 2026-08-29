"""LangGraph orchestration: parallel agents + semgrep + supervisor (M4).

Topology:
    START -+-> reviewer ----+
           |-> tests   ----+
           |-> summary ----+-> supervisor -> combine -> END
           +-> semgrep -> security --------+

reviewer/tests/summary run in parallel; semgrep must complete before the
security agent runs. Supervisor merges reviewer+security, dedupes, ranks,
and runs FP filtering. combine consumes the supervisor's output.
"""

import random
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agents import reviewer, security, summary, tests
from semgrep_runner import run_semgrep

SEVERITY_ORDER = {"critical": 0, "warning": 1, "nit": 2}

STAGGER_MIN = 0.5
STAGGER_MAX = 2.0


def _stagger():
    """Random start delay to desync the agent burst and ease the Groq
    30-RPM free-tier window. Keeps the graph parallel; just offsets starts.
    Applied only to the still-parallel agents (reviewer/tests/summary)."""
    time.sleep(random.uniform(STAGGER_MIN, STAGGER_MAX))


class ReviewState(TypedDict):
    diff_text: str
    truncated: bool
    repo_path: str
    reviewer_result: list
    security_result: list
    test_result: list
    summary_result: str
    semgrep_findings: list
    supervisor_result: list
    comment: str


def reviewer_node(state):
    _stagger()
    return {"reviewer_result": reviewer.review(state["diff_text"])}


def tests_node(state):
    _stagger()
    return {"test_result": tests.find_gaps(state["diff_text"])}


def summary_node(state):
    _stagger()
    return {"summary_result": summary.summarize(state["diff_text"])}


def semgrep_node(state):
    return {"semgrep_findings": run_semgrep(state["repo_path"])}


def security_node(state):
    return {"security_result": security.scan(state["diff_text"], state.get("semgrep_findings") or [])}


def supervisor_node(state):
    """Merge and dedup reviewer+security, then FP-filter. One LLM call."""
    from supervisor import merge_and_rank, filter_false_positives

    merged = merge_and_rank(
        state.get("reviewer_result") or [],
        state.get("security_result") or [],
        state.get("diff_text", ""),
        state.get("truncated", False),
    )
    flagged = filter_false_positives(merged)
    return {"supervisor_result": flagged}


def _format_issue_section(issues):
    """Format issues grouped by severity. Likely FPs get their own subsection."""
    real = [i for i in issues if not i.get("likely_fp")]
    fps = [i for i in issues if i.get("likely_fp")]

    if not real and not fps:
        return "No issues found."

    parts = []
    if real:
        grouped = {}
        for issue in real:
            severity = issue.get("severity")
            if severity not in SEVERITY_ORDER:
                severity = "nit"
            grouped.setdefault(severity, []).append(issue)
        for severity in sorted(grouped, key=lambda s: SEVERITY_ORDER[s]):
            parts.append(f"**{severity.capitalize()} ({len(grouped[severity])})**")
            parts.append("")
            for issue in grouped[severity]:
                location = f"`{issue.get('file', '?')}`"
                line = issue.get("line")
                if isinstance(line, int):
                    location += f":{line}"
                source = issue.get("_source", "")
                src_tag = f" _{source}_" if source else ""
                parts.append(f"- {location} — {issue.get('message', '')}{src_tag}")
            parts.append("")

    if fps:
        parts.append("<details>")
        parts.append(f"<summary>Possible false positives ({len(fps)})</summary>")
        parts.append("")
        for issue in fps:
            location = f"`{issue.get('file', '?')}`"
            line = issue.get("line")
            if isinstance(line, int):
                location += f":{line}"
            source = issue.get("_source", "")
            src_tag = f" _{source}_" if source else ""
            parts.append(f"- {location} — {issue.get('message', '')}{src_tag}")
        parts.append("")
        parts.append("</details>")
        parts.append("")

    return "\n".join(parts).rstrip()


def _format_gap_section(issues):
    """Format a gap list (tests agent: no severity) as plain bullets."""
    if not issues:
        return "No issues found."
    lines = []
    for issue in issues:
        location = f"`{issue.get('file', '?')}`"
        lines.append(f"- {location} — {issue.get('message', '')}")
    return "\n".join(lines)


def combine_node(state):
    """M4 combine: supervisor output replaces separate reviewer/security sections.

    Fixed order: Summary, Issues (from supervisor), Tests.
    """
    parts = ["### Code Review Bot", ""]
    if state.get("truncated"):
        parts.append("> Diff was too large; only the first changed files were reviewed.\n")
    parts.append("## Summary")
    parts.append("")
    parts.append(state.get("summary_result") or "No summary provided.")
    parts.append("")
    parts.append("## Issues")
    parts.append("")
    parts.append(_format_issue_section(state.get("supervisor_result") or []))
    parts.append("")
    parts.append("## Tests")
    parts.append("")
    parts.append(_format_gap_section(state.get("test_result") or []))
    return {"comment": "\n".join(parts)}


def build_graph():
    builder = StateGraph(ReviewState)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("security", security_node)
    builder.add_node("tests", tests_node)
    builder.add_node("summary", summary_node)
    builder.add_node("semgrep", semgrep_node)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("combine", combine_node)
    builder.add_edge(START, "reviewer")
    builder.add_edge(START, "tests")
    builder.add_edge(START, "summary")
    builder.add_edge(START, "semgrep")
    builder.add_edge("semgrep", "security")
    builder.add_edge("reviewer", "supervisor")
    builder.add_edge("security", "supervisor")
    builder.add_edge("supervisor", "combine")
    builder.add_edge("tests", "combine")
    builder.add_edge("summary", "combine")
    builder.add_edge("combine", END)
    return builder.compile()
