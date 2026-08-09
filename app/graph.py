"""LangGraph orchestration: 4 parallel agents + combine (M2).

Topology:
    START -+-> reviewer -+
           |-> security -|
           |-> tests    -+-> combine -> END
           +-> summary  -+
"""

import random
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agents import reviewer, security, summary, tests

SEVERITY_ORDER = {"critical": 0, "warning": 1, "nit": 2}

STAGGER_MIN = 0.5
STAGGER_MAX = 2.0


def _stagger():
    """Random start delay to desync the 4-agent burst and ease the Groq
    30-RPM free-tier window. Keeps the graph parallel; just offsets starts."""
    time.sleep(random.uniform(STAGGER_MIN, STAGGER_MAX))


class ReviewState(TypedDict):
    diff_text: str
    truncated: bool
    reviewer_result: list
    security_result: list
    test_result: list
    summary_result: str
    comment: str


def reviewer_node(state):
    _stagger()
    return {"reviewer_result": reviewer.review(state["diff_text"])}


def security_node(state):
    _stagger()
    return {"security_result": security.scan(state["diff_text"])}


def tests_node(state):
    _stagger()
    return {"test_result": tests.find_gaps(state["diff_text"])}


def summary_node(state):
    _stagger()
    return {"summary_result": summary.summarize(state["diff_text"])}


def _format_issue_section(issues):
    """Format an issues list grouped by severity. Empty list -> 'No issues found'."""
    if not issues:
        return "No issues found."
    lines = []
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
    return "\n".join(lines).rstrip()


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
    """M2 combine: concatenate each agent's output under its own section.

    Fixed order: Summary, Reviewer, Security, Tests. No ranking/merging/dedup
    yet — that is deferred to M4.
    """
    parts = ["### Code Review Bot", ""]
    if state.get("truncated"):
        parts.append("> Diff was too large; only the first changed files were reviewed.\n")
    parts.append("## Summary")
    parts.append("")
    parts.append(state.get("summary_result") or "No summary provided.")
    parts.append("")
    parts.append("## Reviewer")
    parts.append("")
    parts.append(_format_issue_section(state.get("reviewer_result") or []))
    parts.append("")
    parts.append("## Security")
    parts.append("")
    parts.append(_format_issue_section(state.get("security_result") or []))
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
    builder.add_node("combine", combine_node)
    builder.add_edge(START, "reviewer")
    builder.add_edge(START, "security")
    builder.add_edge(START, "tests")
    builder.add_edge(START, "summary")
    for node in ("reviewer", "security", "tests", "summary"):
        builder.add_edge(node, "combine")
    builder.add_edge("combine", END)
    return builder.compile()
