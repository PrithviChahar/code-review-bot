"""M4 live demo: full pipeline + skip + FP — three scenarios.

Uses real Groq LLM for all agent + supervisor calls.
"""
import sys
import os
import time
import json
import tempfile
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from graph import build_graph
from supervisor import should_skip_review

GRAPH = build_graph()

PASSED = 0
FAILED = 0


def check(label, condition):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {label}")
    else:
        FAILED += 1
        print(f"  [FAIL] {label}")


# --- Scenario 1: Full PR1 demo (all agents + supervisor) ---

print("=" * 60)
print("Scenario 1: Full pipeline (PR1-style demo bugs)")
print("=" * 60)

PR1_DIFF = """\
@@ -1,10 +1,20 @@
 import os
+import sqlite3

 SYSTEM_PROMPT = "You are a helpful assistant"
+DB_PATH = "/tmp/test.db"

 def process_data(items):
-    return items
+    results = []
+    for item in items:
+        results.append(item * 2)
+    return results

-def compute(x, y=3):
-    return x + y
+def compute(x, y=[]):
+    y.append(x)
+    return y
+
+def get_user(user_id):
+    conn = sqlite3.connect(DB_PATH)
+    query = f"SELECT * FROM users WHERE id = {user_id}"
+    return conn.execute(query).fetchall()
"""

print(f"Diff size: {len(PR1_DIFF)} chars")
print(f"Should skip: {should_skip_review(PR1_DIFF)}")
check("PR1 diff not skipped (> 5 lines)", not should_skip_review(PR1_DIFF))

print("\nRunning full graph (4 agents + supervisor)... This takes ~30-60s.")
t0 = time.time()
state = GRAPH.invoke({
    "diff_text": PR1_DIFF,
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
print(f"Done in {elapsed:.1f}s\n")

comment = state.get("comment", "")
print("Generated comment:")
print("-" * 60)
print(comment)
print("-" * 60)

check("Comment has ## Summary", "## Summary" in comment)
check("Comment has ## Issues", "## Issues" in comment)
check("Comment has ## Tests", "## Tests" in comment)

supervisor = state.get("supervisor_result", [])
check("Supervisor produced issues", len(supervisor) > 0)
check("Issues have likely_fp field", all("likely_fp" in i for i in supervisor))

fp_count = sum(1 for i in supervisor if i.get("likely_fp"))
real_count = len(supervisor) - fp_count
print(f"\nSupervisor output: {len(supervisor)} issues ({real_count} real, {fp_count} FP)")

if supervisor:
    print("\nIssues (sorted by severity):")
    for i, iss in enumerate(supervisor):
        fp = " [FP]" if iss.get("likely_fp") else ""
        src = f" ({iss.get('_source', '?')})" if iss.get("_source") else ""
        print(f"  [{i}] {iss['severity']:>8} | {iss.get('file', '?')}:{iss.get('line', '?')} | {iss['message'][:60]}{src}{fp}")

check("SQLi found in issues", any("sql" in i.get("message", "").lower() or "SQL" in i.get("message", "") for i in supervisor))
check("Mutable default found", any("mutable" in i.get("message", "").lower() or "default" in i.get("message", "").lower() for i in supervisor))


# --- Scenario 2: Skip short-circuit (tiny diff) ---

print("\n" + "=" * 60)
print("Scenario 2: Skip short-circuit (tiny diff)")
print("=" * 60)

TINY_DIFF = """\
@@ -10,3 +10,4 @@
 x = 1
 y = 2
+z = 3
"""

should_skip = should_skip_review(TINY_DIFF)
print(f"should_skip_review: {should_skip}")
check("Tiny diff -> skip=True", should_skip)

SMALL_DIFF_COMMENT = (
    "### Code Review Bot\n\n"
    "This diff is too small for a full review (fewer than 5 meaningful "
    "changed lines or whitespace/comment-only). No issues to report."
)
check("Small-diff comment is short", len(SMALL_DIFF_COMMENT) < 300)
print(f"Would post: {SMALL_DIFF_COMMENT[:100]}...")


# --- Scenario 3: FP demo with all-caps constant ---

print("\n" + "=" * 60)
print("Scenario 3: FP filter (all-caps constant)")
print("=" * 60)

from supervisor import filter_false_positives, merge_and_rank

fake_reviewer = [
    {"severity": "warning", "file": "app/config.py", "line": 5,
     "message": "Magic number 42 found; SYSTEM_PROMPT uses an unnamed numeric literal instead of a named constant"},
]
fake_security = [
    {"severity": "warning", "file": "app/main.py", "line": 10,
     "message": "SQL injection vulnerability in database query"},
]

merged = merge_and_rank(fake_reviewer, fake_security)
print(f"Merged: {len(merged)} issues")
for i, iss in enumerate(merged):
    print(f"  [{i}] {iss['severity']:>8} | {iss.get('file', '?')}:{iss.get('line', '?')} | {iss['message'][:60]}")

print("\nRunning FP filter (real LLM)...")
t0 = time.time()
flagged = filter_false_positives(merged)
elapsed = time.time() - t0
print(f"Done in {elapsed:.1f}s\n")

for i, iss in enumerate(flagged):
    fp = " [FP]" if iss.get("likely_fp") else ""
    print(f"  [{i}] {iss['severity']:>8} | {iss.get('file', '?')}:{iss.get('line', '?')} | fp={iss.get('likely_fp')} | {iss['message'][:50]}{fp}")

config_fp = any(i.get("likely_fp") and "config" in i.get("file", "") for i in flagged)
check("Config constant flagged as FP", config_fp)

sqli_real = any(not i.get("likely_fp") and "sql" in i.get("message", "").lower() for i in flagged)
check("SQLi kept as real", sqli_real)

print("\n" + "=" * 60)
print(f"Overall: {PASSED} passed, {FAILED} failed")
print("=" * 60)
sys.exit(1 if FAILED else 0)
