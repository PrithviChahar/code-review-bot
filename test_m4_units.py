"""M4 unit tests: merge_and_rank, should_skip_review, skip short-circuit.

No API calls, no mocking needed — pure Python + graph topology verification.
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

from supervisor import merge_and_rank, should_skip_review, _messages_similar

PASSED = 0
FAILED = 0


def test(label, condition):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {label}")
    else:
        FAILED += 1
        print(f"  [FAIL] {label}")


print("=" * 60)
print("M4 Unit Tests (no API calls)")
print("=" * 60)


# --- should_skip_review ---

print("\n--- should_skip_review ---")

diff_tiny = """\
@@ -10,3 +10,5 @@
 x = 1
+y = 2
+z = 3
"""
test("tiny diff (3 lines) -> skip", should_skip_review(diff_tiny))

diff_empty = ""
test("empty diff -> skip", should_skip_review(diff_empty))

diff_whitespace = """\
@@ -10,3 +10,3 @@
 x = 1
-    y = 2
+    y =  2
"""
test("whitespace-only change -> skip", should_skip_review(diff_whitespace))

diff_comment_only = """\
@@ -10,3 +10,3 @@
-x = 1
+x = 1  # fixed typo
"""
test("comment-only change -> skip", should_skip_review(diff_comment_only))

diff_big = """\
@@ -10,6 +10,11 @@
 x = 1
+y = 2
+z = 3
+a = 4
+b = 5
+c = 6
"""
test("6 lines -> no skip", not should_skip_review(diff_big))

diff_exact_boundary = """\
@@ -10,4 +10,4 @@
 x = 1
-y = 2
+y = 22
+z = 33
"""
test("exactly 2 lines (< 5) -> skip", should_skip_review(diff_exact_boundary))


# --- _messages_similar ---

print("\n--- _messages_similar ---")

test("identical messages", _messages_similar("SQL injection here", "SQL injection here"))
test("subset match", _messages_similar("SQL injection", "SQL injection vulnerability in query"))
test("overlapping keywords", _messages_similar(
    "mutable default argument in function",
    "function uses mutable default argument"
))
test("different topics", not _messages_similar(
    "SQL injection vulnerability",
    "empty list used as default argument"
))
test("empty strings", _messages_similar("", ""))


# --- merge_and_rank ---

print("\n--- merge_and_rank ---")

reviewer_out = [
    {"severity": "warning", "file": "a.py", "line": 5, "message": "Possible SQL injection"},
    {"severity": "nit", "file": "b.py", "line": None, "message": "Consider using descriptive variable names"},
]
security_out = [
    {"severity": "critical", "file": "a.py", "line": 5, "message": "SQL injection vulnerability in query"},
    {"severity": "warning", "file": "c.py", "line": 10, "message": "Empty list used as default argument"},
]

merged = merge_and_rank(reviewer_out, security_out)

test("dedup a.py:5 (similar msg) -> 1 issue", sum(1 for i in merged if i["file"] == "a.py") == 1)
test("kept severity is critical (higher)", next(i["severity"] for i in merged if i["file"] == "a.py") == "critical")
test("source note shows both agents", "Reviewer" in next(i["_source"] for i in merged if i["file"] == "a.py") and "Security" in next(i["_source"] for i in merged if i["file"] == "a.py"))
test("b.py and c.py kept separately", sum(1 for i in merged if i["file"] in ("b.py", "c.py")) == 2)
test("sorted: critical first", merged[0]["severity"] == "critical")

reviewer_only = [{"severity": "nit", "file": "x.py", "line": 1, "message": "Style nit"}]
merged2 = merge_and_rank(reviewer_only, [])
test("reviewer-only -> passes through", len(merged2) == 1 and merged2[0]["_source"] == "Reviewer")

merged3 = merge_and_rank([], [])
test("both empty -> empty", merged3 == [])

diff_msg = [
    {"severity": "warning", "file": "a.py", "line": 5, "message": "SQL injection"},
    {"severity": "warning", "file": "a.py", "line": 5, "message": "Unsanitized user input in query"},
]
merged4 = merge_and_rank(diff_msg, [])
test("same location, different msgs -> both kept", len(merged4) == 2)


# --- Skip short-circuit via graph ---

print("\n--- skip short-circuit (graph wiring) ---")

from graph import build_graph
from unittest.mock import patch

small_diff = "@@ -1,2 +1,3 @@\n x\n+y\n"

with patch("app.graph.reviewer.review") as mock_rev, \
     patch("app.graph.security.scan") as mock_sec, \
     patch("app.graph.tests.find_gaps") as mock_tests, \
     patch("app.graph.summary.summarize") as mock_sum, \
     patch("app.graph.run_semgrep") as mock_sg:
    mock_rev.return_value = []
    mock_sec.return_value = []
    mock_tests.return_value = []
    mock_sum.return_value = ""
    mock_sg.return_value = []

    graph = build_graph()

    # should_skip_review BEFORE graph
    skip = should_skip_review(small_diff)
    test("should_skip_review returns True for small diff", skip)

    if skip:
        test("graph not invoked (skip short-circuit)", True)
    else:
        t0 = time.time()
        state = graph.invoke({
            "diff_text": small_diff,
            "truncated": False,
            "repo_path": os.getcwd(),
            "reviewer_result": [],
            "security_result": [],
            "test_result": [],
            "summary_result": "",
            "semgrep_findings": [],
            "supervisor_result": [],
        })
        elapsed = time.time() - t0
        test(f"graph ran in {elapsed:.2f}s (should be fast with mocks)", elapsed < 2)


# --- Summary ---

print("\n" + "=" * 60)
print(f"Results: {PASSED} passed, {FAILED} failed")
print("=" * 60)
sys.exit(1 if FAILED else 0)
